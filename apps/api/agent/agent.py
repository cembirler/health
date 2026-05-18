"""Function-calling agent loop over a Google AI Studio model.

Each iteration: send the transcript + tool schemas -> model returns either
plain text (done) or one-or-more functionCall parts -> we run each tool and
append a functionResponse part -> loop, up to max_iterations.

Model is selectable via the MODEL env var; default is `gemini-flash-latest`.
"""
import asyncio
import inspect
import json
import os
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import httpx

from .request_context import reset_request_context, set_request_context
from .tools import Tool, TOOLS


# Callback invoked after each generateContent round-trip with everything we
# sent + got back + token usage. The session router writes one chat_requests
# row per fire — that's the cost-auditing / replay trail.
LlmCallCallback = Callable[["LlmCallRecord"], Awaitable[None]]


MODEL = os.getenv("MODEL", "gemma-4-26b-a4b-it")


def _model_url(model: str) -> str:
    return (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )


@dataclass
class AgentResult:
    """The terminal text the model returned for this turn. The CLI prints
    this; the API route doesn't use it (the wire is rebuilt from the
    chat_requests rows written via `on_llm_call`)."""
    answer: str


@dataclass
class LlmCallRecord:
    """Captures one generateContent round-trip for `chat_requests` insertion.

    Field names match the `chat_requests` columns 1:1 — no translation needed
    in the writer callback. Filled incrementally inside the agent loop: the
    LLM-side fields come back from the API; `tool_results` is populated after
    we execute the tools the model asked for, so a single record carries the
    full "model asked, we answered" pair.
    """
    # The user-typed message that initiated this turn block. Same value on
    # every record fired during one agent run — the wire assembler groups
    # rows by this to rebuild user→assistant pairs without a separate
    # messages table.
    user_message: str
    # What we POSTed — full `contents` array including the system instruction
    # prepended to the first user turn.
    request: list[dict]
    # Raw response body. None if the call failed before yielding one.
    response: Optional[dict] = None
    # Extracted from response.candidates[0].content.parts. None when the model
    # returned plain text instead of tool calls.
    tool_calls: Optional[list[dict]] = None
    # [{name, result}, ...] — what we executed and plugged back in next call.
    # Same length as tool_calls; null when there were none.
    tool_results: Optional[list[dict]] = None
    # Final text reply if the model returned text. Null when it returned
    # tool calls instead.
    reply_text: Optional[str] = None
    # Usage metadata. Gemini 2.5+ populates thought_tokens; older models 0.
    input_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    total_tokens: int = 0
    # The model ID this round-trip targeted (e.g. "gemma-4-26b-a4b-it").
    # Persisted onto chat_requests so the wire can show which model
    # produced each historical turn even after the user switches.
    model: str = ""
    # {status, body} if the call failed.
    error: Optional[dict] = None


def _extract_usage(response: Optional[dict]) -> dict:
    """Pull token counts out of Gemini's `usageMetadata` block."""
    if not response or not isinstance(response, dict):
        return {"input_tokens": 0, "output_tokens": 0, "thought_tokens": 0, "total_tokens": 0}
    usage = response.get("usageMetadata") or {}
    return {
        "input_tokens": int(usage.get("promptTokenCount") or 0),
        "output_tokens": int(usage.get("candidatesTokenCount") or 0),
        "thought_tokens": int(usage.get("thoughtsTokenCount") or 0),
        "total_tokens": int(usage.get("totalTokenCount") or 0),
    }


SYSTEM_INSTRUCTION = """\
You help U.S. consumers find hospital prices for medical procedures,
backed by CMS-mandated Machine-Readable Files (MRFs). You can answer
"what does <payer> pay at <hospital> for <procedure>" because every
charge links to per-payer rate rows. You CANNOT answer benefits
questions (copay, deductible, prior auth, in-network status) — those
aren't in MRF data; say so plainly.

GROUNDING — the core rule
- ONLY report values that came back from a tool call in this
  conversation (this turn OR a prior turn — both count). Never invent
  prices, hospital names, billing codes, MRF dates, payer names, or
  any other data point.
- If a tool returned no rows for the user's scope, say so:
  "I couldn't find <X> at <Y> in our MRF data." Don't paper over an
  empty result with general medical knowledge.
- When the user pushes back on a prior number ("are you sure?"),
  verify with `get_charge(charge_id=<id from the earlier row>)`.
  A row that's missing from a new ranked `find_prices` result is NOT
  evidence the prior answer was wrong — the new query just surfaced a
  different slice. Never invent a "correction".

SKU IDENTITY — especially for drugs
- Two rows are the same product only when their `code` fields match
  exactly (same TYPE:value). Description similarity is not enough.
  E.g. "SEMAGLUTIDE 2 MG/DOSE (8 MG/3 ML)" and "SEMAGLUTIDE 0.25 MG
  OR 0.5 MG (2 MG/3 ML)" share the substring "2 MG" but are different
  NDCs at different prices.
- A hospital may list the same SKU under multiple `charge_id`s
  (inpatient vs outpatient billing lines). The code is canonical;
  charge_id isn't.

TOOLS
- `find_prices` — main pricing tool. Pass EITHER `code='<TYPE>:<value>'`
  (e.g. `CPT:99213`, `MS-DRG:470`, `NDC:00069-0150`) OR
  `procedure_keywords=['MRI','knee']`, never both. Optional:
  `hospital_keywords`, `payer_keywords`, `location`, `sort_by`, `limit`.
  Each row embeds `top_payer_rates` and an `mrf_id` (the UI mounts a
  source chip automatically — you don't need to call `get_mrf` just to
  cite a source).
- `price_distribution` — "is $N fair" stats (percentiles + count) for
  a (code, location, optional payer) slice.
- `compare_hospitals` — side-by-side for one code across N hospitals.
- `find_procedure` — keyword → candidate codes.
- `find_hospital` — keyword → hospital ids (input resolver).
- `find_hospitals_nearby` — for "hospitals near me" with no procedure
  yet; takes (lat, lng, radius_miles).
- `corpus_stats` / `get_mrf(id=<n>)` — "how much data" / "when was
  this MRF published".
- `get_charge` / `get_code` / `get_hospital` / `list_*` — primitives
  for drilling in. `get_charge(id=…)` is how you re-verify a specific
  prior number (no keyword fuzziness).

LOCATION
- The user's approximate city/lat/lng is appended in USER CONTEXT
  below. For "near me" pass `location.near_lat` + `location.near_lng`
  + `location.radius_miles` (default 25). Don't ask for a ZIP if you
  already have coordinates; mention the inferred city so the user can
  correct it.

EMPTY RESULTS
- May retry ONCE with a single medical synonym (MRI ↔ "magnetic
  resonance"; colonoscopy ↔ "endoscopy"; knee ↔ "lower extremity";
  CT ↔ "computed tomography"). Then STOP — explain what you didn't
  find and let the user opt into broader retries via <SUGGESTIONS>.
- DRUGS are in the corpus (~527k NDC rows across ~121 hospitals), but
  these are HOSPITAL-dispensed prices (in-house pharmacy, infusions),
  NOT retail-pharmacy. If a drug query comes up empty, say so
  explicitly so the user knows why.

OUT OF SCOPE
- Coverage/benefits, copays, prior auth, OOP max, in-network status,
  provider quality, patient reviews, retail pharmacy prices. Say
  plainly these aren't in MRF data — don't guess, don't invent a tool
  call.

REPLY FORMAT
Every terminal reply has three parts in this order:

1. A short prose summary (1–3 sentences). Lead with the takeaway.
   If you need to ask the user something, put the question as the
   LAST sentence of the prose.
2. (Optional) A `<STRUCTURED_CARD>` block — one tool name per line,
   no bullets, no JSON. Lists which tool calls' data the UI should
   surface as a rich card (it looks up each name in the trace and
   mounts the latest matching call). Omit the block if no tool this
   turn produced something worth a card. NEVER include `get_mrf`
   (source chips already render). NEVER include a tool whose latest
   result was empty.
3. A `<SUGGESTIONS>` block with EXACTLY 3 next-user-message prompts,
   one per line, no bullets or JSON. Required on every turn. Use the
   WHOLE conversation: reference concrete facts from this turn
   (hospital names, dollar amounts, payer), don't repeat earlier
   suggestions, and progress the conversation (compare → fairness →
   payer-specific → freshness → alternative location).

CRITICAL: every opening tag MUST have a matching closing tag —
`</STRUCTURED_CARD>` and `</SUGGESTIONS>` on their own line. Omitting
either close tag means the UI can't parse the block and the literal
`<SUGGESTIONS>` text leaks into the rendered reply.

Exact shape:

  In San Francisco, an MRI of the knee runs about $4.4k–$7.2k cash at
  California Pacific Medical Center.

  <STRUCTURED_CARD>
  find_prices
  price_distribution
  </STRUCTURED_CARD>

  <SUGGESTIONS>
  Is $4,800 a fair price for this?
  What does Blue Shield pay for this in San Francisco?
  Find cheaper options in Oakland
  </SUGGESTIONS>

Ambiguity: if the request is vague (no location, "surgery"/"scan",
multiple plausible codes, ambiguous payer match), ask in prose and
use <SUGGESTIONS> to offer the 3 most likely candidates.
"""


def _build_user_context_block() -> str:
    """Per-turn USER CONTEXT block appended to SYSTEM_INSTRUCTION.

    Derived from the request_context contextvar — IP-resolved city / zip /
    lat / lng plus client timezone. Returns an empty string when no geo
    is known (private IP, unresolved, non-US), so the model gets a clean
    prompt instead of a "Location: unknown" line that might bias it.

    Kept here (not folded into SYSTEM_INSTRUCTION) because the geo varies
    per chat and would bust Gemini's implicit-context prefix cache if it
    were part of the static prompt; appending it lets the cacheable head
    stay stable."""
    from .request_context import get_request_context
    ctx = get_request_context()
    geo = ctx.get("user_geo") or {}
    tz = ctx.get("client_timezone")
    parts: list[str] = []
    if geo:
        bits: list[str] = []
        if geo.get("city"):
            bits.append(geo["city"])
        if geo.get("region"):
            bits.append(geo["region"])
        if geo.get("zip"):
            bits.append(f"ZIP {geo['zip']}")
        loc_line = ", ".join(bits) if bits else "United States"
        parts.append(f"User's approximate location (IP-derived): {loc_line}.")
        if geo.get("lat") is not None and geo.get("lng") is not None:
            parts.append(
                f"Coordinates: lat={geo['lat']:.4f}, lng={geo['lng']:.4f}. "
                "When the user says 'near me' / 'nearby' / 'closest', "
                "pass these as `location.near_lat` + `location.near_lng` "
                "(and a `radius_miles`, default 25) to `find_prices`, "
                "`price_distribution`, or `find_hospital`, or call "
                "`find_hospitals_nearby` directly for a no-procedure "
                "first turn. Mention the city in your reply so the user "
                "can correct it if the IP guess is wrong."
            )
    if tz:
        parts.append(f"Client timezone: {tz}.")
    if not parts:
        return ""
    return "\n\nUSER CONTEXT (this turn only)\n" + "\n".join(parts)


def _function_declarations(tools: dict[str, Tool]) -> list[dict]:
    return [
        {"name": t.name, "description": t.description, "parameters": t.parameters}
        for t in tools.values()
    ]


async def run_tool(name: str, args: dict, tools: dict[str, Tool]) -> dict:
    """Invoke a tool by name (sync or async) and return its result.

    Citations come from the underlying data — every priced row carries an
    `mrf_id`, aggregates carry `source_mrf_ids`. No outer envelope.
    """
    if name not in tools:
        return {"error": f'unknown tool "{name}"', "available": list(tools)}
    t = tools[name]
    try:
        if inspect.iscoroutinefunction(t.fn):
            raw = await t.fn(**args)
        else:
            raw = t.fn(**args)
    except TypeError as e:
        return {"error": f"bad arguments: {e}"}
    except Exception as e:
        return {"error": str(e)}
    return {"result": raw}


def _cache_key(name: str, args: dict) -> str:
    """Stable string for (tool_name, args) — used to dedupe tool calls within one chat."""
    return name + "|" + json.dumps(args, sort_keys=True, default=str)


# Older tool results in the transcript get rewritten to a small preview
# before the next `_call_model` call. Keeps the most recent N iterations
# fully readable (the model is actively reasoning over them) while
# preventing the transcript from ballooning when a turn fans out into
# many tool calls. A typical `find_prices` result is ~9 KB; this cuts
# each older iteration to under 1 KB.
_KEEP_LAST_FULL = 2
_OLD_RESULT_PREVIEW_CHARS = 600


def _trim_old_tool_results(contents: list[dict]) -> None:
    """Replace older `functionResponse` payloads with a small preview.

    Mutates `contents` in place. Walks every user-role entry, finds the
    ones that carry a `functionResponse`, and rewrites all but the most
    recent `_KEEP_LAST_FULL` to `{"truncated": True, "preview": "..."}`.
    The function-call names + args stay intact in the model's earlier
    `parts` entries, so the model still sees what it called and with
    what args — just not the full data.
    """
    fr_indices = [
        i for i, c in enumerate(contents)
        if c.get("role") == "user"
        and any("functionResponse" in p for p in c.get("parts", []))
    ]
    to_truncate = fr_indices[:-_KEEP_LAST_FULL] if _KEEP_LAST_FULL else fr_indices
    for i in to_truncate:
        new_parts = []
        for p in contents[i].get("parts", []):
            if "functionResponse" in p:
                fr = p["functionResponse"]
                preview = json.dumps(fr.get("response"), default=str)
                if len(preview) > _OLD_RESULT_PREVIEW_CHARS:
                    preview = preview[:_OLD_RESULT_PREVIEW_CHARS] + "…"
                new_parts.append({
                    "functionResponse": {
                        "name": fr.get("name", ""),
                        "response": {"truncated": True, "preview": preview},
                    },
                })
            else:
                new_parts.append(p)
        contents[i] = {**contents[i], "parts": new_parts}


class MaxIterationsReached(Exception):
    """Agent loop hit the iteration cap without emitting a final reply.

    The bg-task handler writes a synthetic terminal turn so the UI shows a
    clear "I ran out of steps" note instead of an empty assistant reply.
    """


class UpstreamModelError(Exception):
    """Raised when the model endpoint fails after all retries."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"upstream model returned {status}")


RetryNoticeCallback = Callable[[float], Awaitable[None]]


async def _call_model(
    api_key: str,
    contents: list[dict],
    tools: dict[str, Tool],
    model: str,
    notify_retry: Optional[RetryNoticeCallback] = None,
) -> dict:
    """POST to the model endpoint with retry on 5xx / network errors.

    Sends the system prompt + tool declarations as a stable prefix on every
    call so Gemini's implicit context caching (auto on 2.5+ models) can
    discount them after the first hit. The growing tail — user message,
    function calls, function responses — is fresh each iteration and
    billed at the normal rate.

    On 429 (per-minute token quota): sleeps 30s / 60s / 120s between
    attempts and fires `notify_retry` so the UI can show a "rate limited,
    retrying" trace step. On 5xx / network errors: exponential backoff
    starting at 0.5s. Other 4xx is fatal — propagated immediately.
    """
    system_text = SYSTEM_INSTRUCTION + _build_user_context_block()
    payload = {
        "systemInstruction": {"parts": [{"text": system_text}]},
        "contents": contents,
        "tools": [{"functionDeclarations": _function_declarations(tools)}],
        "generationConfig": {
            "temperature": 0.2,
            # Surface the model's reasoning summaries as `{thought: true,
            # text: ...}` parts in the response. Without this Gemini 2.5
            # ships a compact opaque `thoughtSignature` for state passing
            # only; no visible thinking text. Default thinking budget
            # (dynamic) is kept — we just want the summary surfaced.
            "thinkingConfig": {"includeThoughts": True},
        },
    }
    # Fixed escalating waits across the three retry slots. We deliberately
    # ignore the server-supplied `retryDelay` — when Google says "retry in
    # 14s" it often refuses again within seconds because the quota window
    # is per-rolling-minute, not a hard timer. Waiting 30s first gives the
    # rolling window enough room to actually clear.
    rate_limit_waits = [30.0, 60.0, 120.0]
    last_status: Optional[int] = None
    last_body = ""
    delay = 0.5
    for attempt in range(len(rate_limit_waits) + 1):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(_model_url(model), params={"key": api_key}, json=payload)
            if 200 <= r.status_code < 300:
                return r.json()
            if r.status_code == 429:
                # Per-minute token quota hit. Surface a "rate limited,
                # retrying" notice to the UI so the user sees the agent
                # recovering, sleep the fixed wait, retry.
                last_status, last_body = r.status_code, r.text
                if attempt < len(rate_limit_waits):
                    wait = rate_limit_waits[attempt]
                    if notify_retry is not None:
                        await notify_retry(wait)
                    await asyncio.sleep(wait)
                    continue
                raise UpstreamModelError(r.status_code, r.text[:500])
            if r.status_code < 500:
                # Other 4xx is fatal — typically malformed request (bad
                # tool schema, invalid model name, expired key). Raise
                # immediately so the body propagates instead of disappearing
                # into a generic httpx exception.
                raise UpstreamModelError(r.status_code, r.text[:500])
            last_status, last_body = r.status_code, r.text
        except httpx.RequestError as e:
            last_status, last_body = 0, f"network: {e}"
        if attempt < len(rate_limit_waits):
            await asyncio.sleep(delay)
            delay *= 3
    raise UpstreamModelError(last_status or 0, last_body[:500])


async def run_agent(
    user_message: str,
    history: list[dict],
    api_key: str,
    tools: dict[str, Tool] = TOOLS,
    max_iterations: int = 50,
    on_llm_call: Optional[LlmCallCallback] = None,
    request_context: Optional[dict] = None,
) -> AgentResult:
    """Execute one turn of the agent loop.

    `request_context` carries per-call user info (client_ip, timezone, …)
    into a contextvar that tools can read from. Set by the route that
    kicks off the bg task — the original Request is gone by the time
    tools execute.

    `on_llm_call` fires once per generateContent round-trip with the full
    request/response payload + usage metadata. The session router writes
    one chat_requests row per fire.
    """
    ctx_token = set_request_context(request_context) if request_context else None
    try:
        return await _run_agent_inner(
            user_message=user_message, history=history, api_key=api_key,
            tools=tools, max_iterations=max_iterations,
            on_llm_call=on_llm_call, model=MODEL,
        )
    finally:
        if ctx_token is not None:
            reset_request_context(ctx_token)


async def _run_agent_inner(
    user_message: str,
    history: list[dict],
    api_key: str,
    tools: dict[str, Tool],
    max_iterations: int,
    model: str,
    on_llm_call: Optional[LlmCallCallback] = None,
) -> AgentResult:
    # SYSTEM_INSTRUCTION is sent via the dedicated `systemInstruction` field
    # in _call_model — see there for why. Keeping it OUT of `contents` makes
    # the request prefix (system_instruction + tool decls) byte-identical
    # across every call, so Gemini's implicit context caching kicks in
    # automatically.
    contents: list[dict] = [
        {"role": h["role"], "parts": [{"text": h["content"]}]} for h in history
    ]
    contents.append(
        {"role": "user", "parts": [{"text": user_message}]}
    )

    # Conversation-scoped tool-result cache: identical (tool, args) within one
    # /api/chat call returns the cached result instead of re-querying. Cuts
    # redundant DB hits when the model retries with the same args after a
    # missed disambiguation, or when a multi-turn plan revisits a lookup.
    cache: dict[str, dict] = {}

    for _ in range(max_iterations):
        # Trim older tool results to a short preview so the transcript
        # doesn't grow ~10 KB per iteration. The latest 2 iterations
        # stay full so the model can reason over the actual data it
        # just fetched.
        _trim_old_tool_results(contents)
        # Snapshot what we're about to send — needed by the on_llm_call
        # writer below, and the loop mutates `contents` in place.
        request_snapshot = [dict(c) for c in contents]

        async def notify_retry(retry_after_seconds: float) -> None:
            """Fired by `_call_model` right before it sleeps on a 429. We
            persist a synthetic row with a `__rate_limited` tool_call so the
            UI sees a yellow "agent is recovering" trace step appear in
            real time. No usage tokens, no terminal reply — just the notice.
            """
            if on_llm_call is None:
                return
            await on_llm_call(LlmCallRecord(
                user_message=user_message,
                request=request_snapshot,
                tool_calls=[{
                    "name": "__rate_limited",
                    "args": {"retry_after_seconds": round(retry_after_seconds, 1)},
                }],
                tool_results=[{"name": "__rate_limited", "result": {"ok": True}}],
                model=model,
            ))

        try:
            data = await _call_model(
                api_key, contents, tools, model, notify_retry=notify_retry,
            )
        except UpstreamModelError as e:
            if on_llm_call:
                await on_llm_call(LlmCallRecord(
                    user_message=user_message,
                    request=request_snapshot,
                    error={"status": e.status, "body": e.body[:1000], "model": model},
                    model=model,
                ))
            raise
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError):
            if on_llm_call:
                rec = LlmCallRecord(
                    user_message=user_message,
                    request=request_snapshot, response=data,
                    model=model,
                )
                for k, v in _extract_usage(data).items():
                    setattr(rec, k, v)
                await on_llm_call(rec)
            return AgentResult(answer="(empty response from model)")

        # `thinkingConfig.includeThoughts` enabled: Gemini returns
        #   - `{thought: true, text: "..."}` — reasoning summary
        #   - `{text: "..."}` — user-facing reply
        # On a tool-calling iteration only the thought summary is meaningful
        # (we surface it as a "thinking aloud" bubble above the tool block).
        # On the terminal iteration the reply is the visible answer.
        thought_summary = "\n".join(
            p["text"].strip() for p in parts
            if "text" in p and p.get("thought") is True and p["text"].strip()
        )
        reply = "\n".join(
            p["text"].strip() for p in parts
            if "text" in p and p.get("thought") is not True and p["text"].strip()
        )
        call_parts = [p["functionCall"] for p in parts if "functionCall" in p]
        # Local var name kept as `thought` for downstream code: it's what
        # gets persisted onto chat_requests.reply_text for this iteration.
        thought = thought_summary if call_parts else reply

        if not call_parts:
            if on_llm_call:
                rec = LlmCallRecord(
                    user_message=user_message,
                    request=request_snapshot, response=data,
                    reply_text=thought,
                    model=model,
                )
                for k, v in _extract_usage(data).items():
                    setattr(rec, k, v)
                await on_llm_call(rec)
            return AgentResult(answer=thought)

        contents.append({"role": "model", "parts": parts})

        response_parts: list[dict] = []
        # Mirror of response_parts but in the {name, result} shape — what
        # gets persisted into chat_llm_calls.tool_results.
        call_records: list[dict] = []
        for call in call_parts:
            name = call.get("name", "")
            args = call.get("args", {}) or {}
            key = _cache_key(name, args)
            cached = cache.get(key)
            if cached is not None:
                result = cached
            else:
                result = await run_tool(name, args, tools)
                cache[key] = result
            response_parts.append(
                {"functionResponse": {"name": name, "response": result}}
            )
            call_records.append({"name": name, "args": args, "result": result})

        # Persist this iteration's LLM call now that we have the tool results.
        if on_llm_call:
            rec = LlmCallRecord(
                user_message=user_message,
                request=request_snapshot, response=data,
                tool_calls=[{"name": r["name"], "args": r["args"]} for r in call_records],
                tool_results=[{"name": r["name"], "result": r["result"]} for r in call_records],
                reply_text=thought or None,
                model=model,
            )
            for k, v in _extract_usage(data).items():
                setattr(rec, k, v)
            await on_llm_call(rec)

        contents.append({"role": "user", "parts": response_parts})

    raise MaxIterationsReached(
        f"Agent loop hit {max_iterations} iterations without producing "
        "a final reply.",
    )
