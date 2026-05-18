"""`/api/sessions/*` — chat persistence + server-owned agent runs.

State lives in two tables (renamed from chat_sessions/chat_llm_calls):

  chats          — one row per chat thread (sidebar entry). Carries title
                   and a free-form `attributes` JSON bag (currently
                   `public_ip`).
  chat_requests  — every Gemini generateContent round-trip plus a placeholder
                   row per user turn. Denormalized: `user_message` is set on
                   every row in a single agent run so the wire assembler can
                   group rows into user→assistant pairs without a separate
                   messages table.

The wire shape `{turns: [...]}` is assembled by walking chat_requests per chat
ordered by `date_created` and grouping consecutive rows that share the same
`user_message`. Each group emits one user turn (from `user_message`) and one
assistant turn (trace from `tool_calls`/`tool_results`, reply from the last
row's `reply_text`, error from any row's `error`).

`POST /sessions/{session_id}/messages` writes a placeholder chat_requests row
(only `user_message` set, response fields null) so the user bubble renders
immediately, then schedules an asyncio background task. The bg task INSERTs
one full chat_requests row per LLM round-trip; the wire assembler picks them
up on polling.

Status derivation: there's no `status` column on `chats` anymore. Whether a
chat is "running" is purely an in-memory question — `session_id` is in
`_running_tasks` AND its task isn't done. Process restart wipes the map;
any chat that was running becomes "idle" with the last persisted
chat_requests row showing whatever the agent had managed to write. No
recovery sweep needed.

User interrupt: POST `/sessions/{session_id}/interrupt` cancels the
asyncio.Task. CancelledError propagates at the next await boundary; the bg
task writes a final chat_requests row with error set.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from agent import (
    MODEL,
    LlmCallRecord,
    MaxIterationsReached,
    UpstreamModelError,
    run_agent,
)
from db.models import Chat, ChatRequest
from db.session import SessionLocal
from deps import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


_ID_RE = re.compile(r"^[a-z0-9]{6,32}$")


# Tracks the bg agent task per chat so the interrupt endpoint can cancel
# it AND the wire layer can derive `status` without a DB round-trip.
# Single-process only; if you ever scale beyond one uvicorn worker, this
# would move to a Redis pub/sub channel keyed on chat_id.
_running_tasks: dict[str, asyncio.Task] = {}


def _is_running(chat_id: str) -> bool:
    task = _running_tasks.get(chat_id)
    return task is not None and not task.done()


def _check_id(chat_id: str) -> str:
    if not _ID_RE.match(chat_id):
        raise HTTPException(400, detail={
            "error": "invalid session id (lowercase hex, 6-32 chars)",
            "code": "invalid_param",
        })
    return chat_id


# --- Pydantic IO models -----------------------------------------------------

class SessionPatchIn(BaseModel):
    """Partial update for title. Insurer state is client-only
    (localStorage), so it's not patchable through this endpoint."""
    model_config = {"extra": "ignore"}

    title: Optional[str] = None


class SessionMessageIn(BaseModel):
    """Body for POST /sessions/{session_id}/messages.

    `message` is what gets sent to the model; `display_text` is what shows in
    the chat bubble. If omitted, falls back to `message`.
    """
    message: str
    display_text: Optional[str] = None
    client_timezone: Optional[str] = None


# --- DB-row → wire-shape helpers --------------------------------------------

def _to_ms(dt: Optional[datetime]) -> Optional[int]:
    """DATETIME → JS-millis. MySQL stores naive UTC; assume UTC if no tzinfo."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _iso(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat(timespec="seconds")


def _make_title(text: str) -> str:
    text = " ".join((text or "").split()).strip()
    return text[:60] + ("…" if len(text) > 60 else "")


def _normalize_error(err: Optional[dict]) -> Optional[dict]:
    """Translate upstream-model errors into the wire shape the frontend
    expects.

    The agent loop persists Gemma failures as `{status, body, model}`
    (see agent.py: `UpstreamModelError` writer). The frontend renders
    `{msg, hint?, code?}`. Without normalization the user sees a red
    "Chat failed" bubble with an empty body. Here we parse Google AI
    Studio's JSON error envelope and surface the human-readable message.

    Pass-through for already-normalized rows ({msg, hint?, code?}) and
    `None`.
    """
    if not err or "msg" in err:
        return err
    if "status" not in err and "body" not in err:
        return err
    status = err.get("status")
    body = err.get("body") or ""
    model = err.get("model") or ""
    # Google AI Studio error envelope: `{"error": {"code", "message", "status"}}`
    detail = body
    google_status = None
    try:
        parsed = json.loads(body)
        inner = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(inner, dict):
            if inner.get("message"):
                detail = inner["message"]
            google_status = inner.get("status")
    except (json.JSONDecodeError, ValueError):
        pass  # fall through to raw body
    msg = (
        f"Gemma returned HTTP {status}." if status
        else "The model call failed."
    )
    if detail:
        msg = f"{msg} {detail}"
    hint_parts: list[str] = []
    if model:
        hint_parts.append(f"model: {model}")
    if google_status:
        hint_parts.append(f"status: {google_status}")
    return {
        "msg": msg,
        "hint": " · ".join(hint_parts) if hint_parts else None,
        "code": "upstream",
    }


def _set_attribute(c: Chat, key: str, value: Any) -> None:
    """Write a single key into the attributes JSON. Pass None to remove it."""
    attrs = dict(c.attributes or {})
    if value is None:
        attrs.pop(key, None)
    else:
        attrs[key] = value
    c.attributes = attrs or None


def _request_to_trace_steps(req: ChatRequest) -> list[dict[str, Any]]:
    """Expand one chat_requests row into 0..N TraceStep dicts for the wire.

    Each tool_call in the request's response becomes a step with the tool
    result attached as `observation`.

    Intermediate "thought" text — the prose the model emits alongside its
    function_call parts in a non-terminal iteration — is persisted on
    `chat_requests.reply_text` (see agent.py: `reply_text=thought or None`
    when call_parts is non-empty). We surface it as the FIRST step's
    `thought` so the frontend can render it as a "thinking aloud" bubble
    above the tool call. Only the first step carries it; subsequent
    parallel-tool steps in the same iteration get "" so the bubble doesn't
    duplicate.
    """
    tool_calls = req.tool_calls or []
    tool_results = req.tool_results or []
    if isinstance(tool_results, str):
        try:
            tool_results = json.loads(tool_results)
        except (json.JSONDecodeError, ValueError):
            tool_results = []

    steps: list[dict[str, Any]] = []
    if not tool_calls:
        return steps

    iter_thought = req.reply_text or ""

    for i, tc in enumerate(tool_calls):
        result = tool_results[i] if i < len(tool_results) else None
        # `result` is {name, result: <tool_envelope>} as written by the agent.
        if result and isinstance(result, dict) and "result" in result:
            obs_obj = result["result"]
        else:
            obs_obj = result
        obs = json.dumps(obs_obj, indent=2) if obs_obj is not None else None
        steps.append({
            "thought": iter_thought if i == 0 else "",
            "action": tc.get("name"),
            "action_input": tc.get("args") or {},
            "observation": obs,
        })
    return steps


def _assemble_turns(requests: list[ChatRequest]) -> list[dict[str, Any]]:
    """Walk chat_requests in date order and emit Turn[] for the wire.

    Grouping rule: rows that share the same `user_message` belong to the
    same turn block. Each block produces:
      - one user turn  (text = the shared user_message)
      - one assistant turn (trace from all rows' tool_calls/tool_results,
                            reply from the last row's reply_text, error from
                            any row's error)

    A "placeholder" row written by post_message — `user_message` set,
    everything else null — is enough to render the user bubble before any
    LLM call has landed. Assistant turn renders with empty reply + trace-so-far
    once any extracts land (the ThinkingMessage in the UI fills the rest).
    """
    turns: list[dict[str, Any]] = []
    if not requests:
        return turns

    current_user_msg: Optional[str] = None
    current_block: list[ChatRequest] = []

    def flush_block():
        if not current_block:
            return
        user_msg = current_block[0].user_message or ""
        user_ts = current_block[0].date_created
        turns.append({
            "role": "user",
            "text": user_msg,
            "trace": [],
            "timestamp": _to_ms(user_ts),
        })
        # Walk requests in the block to build the assistant turn
        trace: list[dict[str, Any]] = []
        reply_text: Optional[str] = None
        error: Optional[dict] = None
        assistant_ts: Optional[datetime] = None
        # Sum token usage across every LLM iteration in this turn block.
        # `thought_tokens` is Gemini 2.5's internal-reasoning count (rolled
        # into `total` by the API); we forward it separately so the UI can
        # break it out if useful, but the user-facing total is what we
        # display by default.
        input_tokens = 0
        output_tokens = 0
        thought_tokens = 0
        total_tokens = 0
        # The model that produced this turn block. Every row in a block
        # carries the same model (the bg task pins it for the whole run),
        # so taking the last row's value is correct.
        turn_model: str = ""
        for r in current_block:
            assistant_ts = r.date_created
            trace.extend(_request_to_trace_steps(r))
            # `reply_text` on a row with tool_calls is the intermediate
            # "thought" prose for that iteration (surfaced via trace step
            # `thought`), not the terminal assistant reply. Only the terminal
            # iteration's reply_text (the row with no tool_calls) should
            # become the assistant turn's `reply`.
            if r.reply_text and not r.tool_calls:
                reply_text = r.reply_text
            if r.error:
                error = _normalize_error(r.error)
            turn_model = r.model
            input_tokens += r.input_tokens or 0
            output_tokens += r.output_tokens or 0
            thought_tokens += r.thought_tokens or 0
            total_tokens += r.total_tokens or 0
        # Only emit an assistant turn when we have something to show beyond
        # the user-message placeholder.
        if trace or reply_text or error:
            wire: dict[str, Any] = {
                "role": "assistant",
                "reply": reply_text or "",
                "trace": trace,
                "timestamp": _to_ms(assistant_ts),
                "tokens": {
                    "input": input_tokens,
                    "output": output_tokens,
                    "thought": thought_tokens,
                    "total": total_tokens,
                },
                "model": turn_model,
            }
            if error is not None:
                wire["error"] = error
            turns.append(wire)

    for r in requests:
        if r.user_message != current_user_msg:
            flush_block()
            current_block = [r]
            current_user_msg = r.user_message
        else:
            current_block.append(r)
    flush_block()

    return turns


def _session_to_wire(
    c: Chat,
    *,
    include_turns: bool,
    requests: Optional[list[ChatRequest]] = None,
) -> dict[str, Any]:
    """Wire shape: chat metadata + assembled `turns` when requested.

    `status` is derived at call time from the in-memory task map — there's
    no persisted column. Process restart → empty map → everything reads as
    idle, which is correct.

    If the most recent assistant turn has tool-call rows but no terminal
    reply (and the session isn't currently running), the agent was killed
    mid-flight — typically by a uvicorn `--reload` restart that wiped
    `_running_tasks` before the bg task could write a terminal row. We
    detect that on read and inject a soft error into the wire turn so the
    UI shows "agent stopped unexpectedly" instead of a silent empty bubble.
    Done at serialization time — no DB writes, so the marker disappears if
    the user sends a new message and starts a fresh turn block.
    """
    running = _is_running(c.id)
    payload: dict[str, Any] = {
        "id": c.id,
        "title": c.title or "Untitled chat",
        "created_at": _iso(c.date_created),
        "status": "running" if running else "idle",
    }
    if include_turns:
        turns = _assemble_turns(requests or [])
        # Mark every assistant turn that has trace steps but no reply and
        # no error as "stopped". Includes historical turns too — once the
        # user sends a new message, the previous broken turn is no longer
        # at the tail, but it's still broken and the marker should stay so
        # the conversation history reads honestly. The only assistant turn
        # we skip is the one currently in flight (running=True): that
        # one's emptiness is legitimate, not abandonment.
        for i, t in enumerate(turns):
            if t.get("role") != "assistant":
                continue
            if t.get("reply") or t.get("error"):
                continue
            if not t.get("trace"):
                continue
            # The currently-running turn is always the last one — skip it.
            if running and i == len(turns) - 1:
                continue
            t["error"] = {
                "msg": (
                    "The agent stopped before finishing this turn. "
                    "Likely the server restarted mid-run. Send a new "
                    "message to continue."
                ),
                "code": "stopped",
            }
        payload["turns"] = turns
    return payload


def _load_session_payload(
    db: Session, chat_id: str,
) -> tuple[Chat, list[ChatRequest]]:
    """Fetch chat + its chat_requests ordered by date."""
    c = db.get(Chat, chat_id)
    if c is None:
        raise HTTPException(404, detail={
            "error": f"session {chat_id} not found", "code": "not_found",
        })
    requests = list(db.execute(
        select(ChatRequest)
        .where(ChatRequest.chat_id == chat_id)
        .order_by(ChatRequest.date_created.asc(), ChatRequest.id.asc())
    ).scalars())
    return c, requests


# --- Endpoints --------------------------------------------------------------

@router.get("")
def list_sessions(
    ids: Optional[str] = None,
    db: Session = Depends(get_db),
) -> dict:
    """Look up the chats whose ids are in the supplied comma-separated list.

    Each browser keeps its own list of "my chat ids" in `localStorage` —
    isolation is client-driven, no cookies, no auth. The sidebar passes
    its list here as `?ids=a,b,c` and gets back metadata for just those
    chats, newest first. Missing or empty `ids` returns `{"data": []}`
    rather than leaking everyone's chats to a bare GET. Unknown ids are
    silently skipped (no enumeration via 404 oracle).
    """
    if not ids:
        return {"data": []}
    id_list = [
        i.strip() for i in ids.split(",")
        if i.strip() and _ID_RE.match(i.strip())
    ]
    if not id_list:
        return {"data": []}
    # Defensive cap — request URL is bounded (~2 KB practical limit) but
    # also guards against pathological cases.
    id_list = id_list[:500]
    rows = db.execute(
        select(Chat)
        .where(Chat.id.in_(id_list))
        .order_by(Chat.date_updated.desc())
    ).scalars().all()
    return {"data": [_session_to_wire(c, include_turns=False) for c in rows]}


@router.get("/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)) -> dict:
    _check_id(session_id)
    c, requests = _load_session_payload(db, session_id)
    return {"data": _session_to_wire(c, include_turns=True, requests=requests)}


@router.patch("/{session_id}")
def patch_session(
    session_id: str, body: SessionPatchIn, db: Session = Depends(get_db),
) -> dict:
    """Partial update — title rename. Doesn't touch chat_requests."""
    _check_id(session_id)
    c = db.get(Chat, session_id)
    if c is None:
        raise HTTPException(404, detail={
            "error": f"session {session_id} not found", "code": "not_found",
        })

    sent = body.model_fields_set
    update_values: dict[str, Any] = {}

    if "title" in sent:
        new_title = (body.title or "").strip()
        if not new_title:
            raise HTTPException(400, detail={
                "error": "title cannot be empty",
                "code": "invalid_param",
            })
        update_values["title"] = new_title[:255]

    if update_values:
        # Preserve date_updated so renames don't bump the sidebar position.
        update_values["date_updated"] = c.date_updated
        db.execute(
            update(Chat)
            .where(Chat.id == session_id)
            .values(**update_values)
        )
        db.commit()
        db.refresh(c)

    return {"data": _session_to_wire(c, include_turns=False)}


@router.delete("/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)) -> dict:
    """Hard-delete the chat row + cascade chat_requests."""
    _check_id(session_id)
    task = _running_tasks.pop(session_id, None)
    if task and not task.done():
        task.cancel()
    c = db.get(Chat, session_id)
    if c is None:
        return {"ok": True, "deleted": False}
    db.delete(c)
    db.commit()
    return {"ok": True, "deleted": True}


# --- Server-owned agent run -------------------------------------------------

@router.post("/{session_id}/messages")
async def post_message(
    session_id: str, body: SessionMessageIn, request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Append a user message and kick off a background agent run."""
    _check_id(session_id)
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(500, detail={
            "error": "GOOGLE_API_KEY not set in apps/api/.env",
            "code": "missing_api_key",
        })

    display_text = (body.display_text or body.message).strip()
    if not display_text:
        raise HTTPException(400, detail={
            "error": "empty message", "code": "invalid_param",
        })

    if _is_running(session_id):
        raise HTTPException(409, detail={
            "error": "agent is still working on the previous message; wait for it to finish",
            "code": "session_running",
        })

    c = db.get(Chat, session_id)
    if c is None:
        c = Chat(id=session_id, title=_make_title(display_text))
        db.add(c)
        db.flush()

    # Build request_context BEFORE scheduling the task — any failure here
    # raises before the user bubble is committed. Also captures public IP
    # (and its derived geo: city/region/zip/lat/lng) into chat.attributes
    # so the agent can answer "near me" without the user volunteering a
    # zip. We only call ip_to_geo once per chat — subsequent turns reuse
    # the cached geo, which keeps us well inside ip-api.com's 45 req/min
    # free quota and avoids latency on every message.
    from geo import (
        client_ip, fetch_public_ip, _is_private_ipv4, ip_to_geo,
    )
    direct_ip = client_ip(request)
    attrs_existing = c.attributes or {}
    public_ip = attrs_existing.get("public_ip")
    if not public_ip:
        if direct_ip and not _is_private_ipv4(direct_ip):
            public_ip = direct_ip
        else:
            public_ip = await fetch_public_ip()
        if public_ip:
            _set_attribute(c, "public_ip", public_ip)
    user_geo = attrs_existing.get("user_geo")
    if user_geo is None and public_ip:
        user_geo = ip_to_geo(public_ip)
        # Cache even on miss (store {}) so we don't re-query a known-bad IP
        # on every turn. ip_to_geo returns None for private / non-US / errors.
        _set_attribute(c, "user_geo", user_geo or {})
    request_context = {
        "client_ip": direct_ip,
        "public_ip": public_ip or direct_ip,
        "client_timezone": body.client_timezone,
        "user_agent": request.headers.get("user-agent"),
        "session_id": session_id,
        "user_geo": user_geo or None,
    }

    # Write the placeholder row: user_message set, response fields null.
    # The wire assembler renders the user bubble immediately from this row
    # while the bg task waits on Gemini. `model` pins the server default
    # for the whole run.
    db.add(ChatRequest(
        chat_id=session_id, user_message=display_text, model=MODEL,
    ))
    if not c.title:
        c.title = _make_title(display_text)

    db.commit()
    db.refresh(c)

    task = asyncio.create_task(
        _run_agent_bg(
            session_id, body.message, display_text, api_key, request_context,
        ),
    )
    _running_tasks[session_id] = task

    c, requests = _load_session_payload(db, session_id)
    return {"data": _session_to_wire(c, include_turns=True, requests=requests)}


@router.post("/{session_id}/interrupt")
async def interrupt_session(session_id: str) -> dict:
    """Cancel an in-flight agent run AND wait for the task to actually
    stop before returning. Awaiting here means the client knows the agent
    is truly done by the time the response comes back — protects against
    the next user message racing a still-cancelling task (which would
    otherwise hit the 409 `session_running` guard in post_message)."""
    _check_id(session_id)
    task = _running_tasks.get(session_id)
    if task and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            # We don't care WHY it stopped — only that it has.
            pass
        return {"interrupted": True}
    return {"interrupted": False}


# --- Background agent task --------------------------------------------------

async def _run_agent_bg(
    session_id: str,
    message: str,
    display_text: str,
    api_key: str,
    request_context: Optional[dict] = None,
) -> None:
    """Run the agent, streaming each LLM call into chat_requests.

    `message` is what we send to the model; `display_text` is what we tag
    every chat_requests row with as `user_message` — the value the wire
    assembler uses to render the user bubble.
    """
    # Build history from prior turns. We reconstruct it by walking
    # chat_requests grouped by user_message; each group contributes one user
    # content (display_text) and one model content (terminal reply_text).
    with SessionLocal() as db:
        prior = list(db.execute(
            select(ChatRequest)
            .where(ChatRequest.chat_id == session_id)
            .order_by(ChatRequest.date_created.asc(), ChatRequest.id.asc())
        ).scalars())

    history: list[dict] = []
    current_user: Optional[str] = None
    current_reply: Optional[str] = None
    for r in prior:
        if r.user_message != current_user:
            # Close out prior block before starting new one.
            if current_user is not None:
                history.append({"role": "user", "content": current_user})
                if current_reply:
                    history.append({"role": "model", "content": current_reply})
            current_user = r.user_message
            current_reply = r.reply_text
        else:
            if r.reply_text:
                current_reply = r.reply_text
    # The most recent block is the just-appended placeholder for this run —
    # exclude it from history (the agent gets the new user_message via the
    # `message` arg directly).
    if current_user is not None and current_user != display_text:
        history.append({"role": "user", "content": current_user})
        if current_reply:
            history.append({"role": "model", "content": current_reply})

    async def on_llm_call(rec: LlmCallRecord) -> None:
        """Persist one generateContent round-trip into chat_requests.

        LlmCallRecord fields match chat_requests columns 1:1 — no renames.
        The client picks the row up on its next poll tick.
        """
        with SessionLocal() as db:
            db.add(ChatRequest(
                chat_id=session_id,
                user_message=rec.user_message,
                request=rec.request,
                response=rec.response,
                tool_calls=rec.tool_calls,
                tool_results=(
                    json.dumps(rec.tool_results)
                    if rec.tool_results is not None else None
                ),
                reply_text=rec.reply_text,
                input_tokens=rec.input_tokens,
                output_tokens=rec.output_tokens,
                thought_tokens=rec.thought_tokens,
                total_tokens=rec.total_tokens,
                model=rec.model,
                error=rec.error,
            ))
            db.commit()

    def _finalize_error(msg: str, hint: str = "", code: str = "") -> None:
        """Write a synthetic chat_requests row carrying the error so the wire
        assembler renders an assistant error turn. Used when the failure
        happens outside the on_llm_call path (CancelledError, catch-all)."""
        err: dict[str, Any] = {"msg": msg}
        if hint:
            err["hint"] = hint
        if code:
            err["code"] = code
        with SessionLocal() as db:
            db.add(ChatRequest(
                chat_id=session_id,
                user_message=display_text,
                model=MODEL,
                error=err,
            ))
            db.commit()

    try:
        await run_agent(
            message, history, api_key,
            on_llm_call=on_llm_call,
            request_context=request_context,
        )
    except asyncio.CancelledError:
        _finalize_error(
            "You interrupted the agent. Send a new message to continue.",
            code="interrupted",
        )
    except MaxIterationsReached as e:
        # Loop cap hit without a final reply. Surface a clear note so the
        # UI shows it as a terminal turn instead of leaving the assistant
        # bubble empty.
        logger.warning("session %s: %s", session_id, e)
        _finalize_error(
            "I couldn't reach a final answer within the step budget for "
            "this turn. The information you asked for may not be in our "
            "MRF data — try narrowing the question or rephrasing.",
            code="max_iterations",
        )
    except UpstreamModelError as e:
        # Already logged via on_llm_call(error=...); nothing more to record.
        logger.warning(
            "session %s: upstream model %s returned %s",
            session_id, MODEL, e.status,
        )
    except Exception as e:
        logger.exception("session %s: agent loop failed", session_id)
        _finalize_error(f"Agent crashed: {e}", hint="code: server_error")
    finally:
        _running_tasks.pop(session_id, None)
