# How it all fits together

This walks through what happens between you typing a message and seeing the
final answer: which process holds which state, how the agent loop drives
tool calls, and how the client stays in sync with the server-side run.

---

## 1. The 30-second mental model

```
   YOU (browser)              SERVER (one uvicorn process)         GOOGLE
 ─────────────────         ─────────────────────────────────       ───────
   React (Vite)             FastAPI ── asyncio bg tasks            AI Studio
   localhost:5173           localhost:8000                         (model
        │                        │                                  selected
        │  HTTP for sends        │                                  via MODEL
        │  HTTP polling for      │  generateContent (POST)          env var)
        │  live updates (2 s)    │ ─────────────────────────────────►  │
        │ ───────────────────►   │                                     │
        │                        │ ◄─────────────────────────────────  │
        │                        │  uses tools → query MySQL           │
        │                        │       │                             │
        │                        │       ▼                             │
        │                        │   ┌───────┐                         │
        │                        │   │ MySQL │  health DB              │
        │                        │   └───────┘                         │
```

The upstream model is selected via the `MODEL` env var (default
`gemini-flash-latest`; was `gemma-4-26b-a4b-it` during the Gemma 4
Good hackathon push). Both go through the same Google AI Studio
`generateContent` endpoint and the same function-calling spec, so
the code is model-agnostic — the only difference is which URL path
`_call_model` builds and what limits the model is under.

Three things to keep in mind:

- **The agent runs on the server, not in your browser.** It's a Python
  `asyncio.Task` living inside the FastAPI process. Closing your tab
  doesn't stop it.
- **`chat_requests` rows are the source of truth.** Every Gemma
  round-trip writes one row. The "wire shape" the frontend sees is
  *assembled on read* by grouping consecutive rows that share the
  same `user_message`.
- **There is no client-side conversation state worth speaking of.**
  React just renders whatever the server says. The server is the brain.
- **The UI polls.** While an agent run is in flight, the client
  GETs `/api/sessions/{id}` every 2 s. Dumb but robust — survives
  proxy buffering, browser tab throttling, and connection blips
  without any reconnect logic.

---

## 2. Components and what they own

```
┌────────────────────────────────────────────────────────────────────────┐
│ apps/web                        React + Vite                           │
│ ────────                                                                │
│ • routes/Chat.tsx     orchestrates: polling loop + send + UI           │
│ • components/Message  renders one user/assistant turn                  │
│ • components/Composer textarea + send/stop button                      │
│ • components/...      ToolCallBlock, StructuredCards, SourceChip, etc. │
│                                                                         │
│ No state lives here except UI-only flags (mobile drawer open, editing  │
│ the title, etc.) and the latest snapshot of turns/status from the      │
│ server.                                                                 │
└────────────────────────────────────────────────────────────────────────┘
                                  │ HTTP + SSE
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│ apps/api                        FastAPI                                │
│ ────────                                                                │
│ • routers/sessions.py   /api/sessions/*  (chat CRUD, messages)         │
│ • routers/agent.py      /api/agent/tools/* (data tools the agent calls)│
│ • routers/meta.py       /api/meta/health, /api/meta/whoami             │
│                                                                         │
│ In-memory state (single uvicorn worker — wiped on restart):            │
│   _running_tasks: dict[chat_id, asyncio.Task]                          │
└────────────────────────────────────────────────────────────────────────┘
                                  │ imports
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│ apps/agent-cli                  The agent loop                         │
│ ───────────────                                                         │
│ • agent_cli/agent.py    run_agent() — the for-loop over Gemma turns    │
│ • agent_cli/tools.py    tool registry (each tool wraps an HTTP call    │
│                         to /api/agent/tools/*)                         │
│                                                                         │
│ Used by:                                                                │
│   - sessions.py bg task (the chat path you actually use)               │
│   - agent_cli CLI (`uv run agent-cli` for local debugging)             │
└────────────────────────────────────────────────────────────────────────┘
                                  │ SQLAlchemy
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│ packages/db                     MySQL (homebrew, local)                │
│ ────────────                                                            │
│ Chat tables (orthogonal to pricing):                                   │
│   chats(id, title, attributes, ...)                                    │
│   chat_requests(chat_id, user_message, request, response,              │
│                 tool_calls, tool_results, reply_text, tokens, ...)     │
│                                                                         │
│ Pricing tables (queried by the agent's tools, never written to by      │
│ the chat path): hospitals, mrfs_csv, hospital_code_charges, ...        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. The full lifecycle of one message

You hit Send. Here's everything that fires, in order:

```
┌──────────┐                ┌────────────┐               ┌────────────┐         ┌────────┐
│ Browser  │                │ FastAPI    │               │ asyncio    │         │ Gemma  │
│ (Chat.tsx)│               │ /messages  │               │ bg task    │         │ API    │
└────┬─────┘                └─────┬──────┘               └─────┬──────┘         └───┬────┘
     │                            │                            │                    │
     │ 1. POST /sessions/{id}/    │                            │                    │
     │    messages {message}      │                            │                    │
     │ ─────────────────────────► │                            │                    │
     │                            │ 2. INSERT placeholder      │                    │
     │                            │    chat_request row        │                    │
     │                            │    (user_message set,      │                    │
     │                            │     response NULL)         │                    │
     │                            │                            │                    │
     │                            │ 3. asyncio.create_task(    │                    │
     │                            │      _run_agent_bg(...))   │                    │
     │                            │    _running_tasks[id] = t  │                    │
     │                            │                            │                    │
     │                            │ ────── kicks off ────────► │                    │
     │                            │                            │                    │
     │ 4. 200 OK with current     │                            │                    │
     │    turns (placeholder is   │                            │                    │
     │    visible, status=running)│                            │                    │
     │ ◄─────────────────────────│                            │                    │
     │                            │                            │ 5. build history   │
     │                            │                            │    from prior      │
     │                            │                            │    chat_requests   │
     │ user bubble paints         │                            │                    │
     │ ThinkingMessage shows      │                            │ 6. POST            │
     │ composer locks             │                            │    generateContent │
     │                            │                            │    (Gemma 4)       │
     │                            │                            │ ─────────────────► │
     │                            │                            │                    │
     │ 7. polling loop fires      │                            │ ◄───────────────── │
     │    every 2 s while       │                            │    response has    │
     │    status === "running"    │                            │    functionCall    │
     │                            │                            │    parts           │
     │                            │                            │                    │
     │                            │                            │ 8. run each tool   │
     │                            │                            │    (HTTP self-call │
     │                            │                            │    to /api/agent/  │
     │                            │                            │    tools/*)        │
     │                            │                            │                    │
     │                            │                            │ 9. INSERT          │
     │                            │                            │    chat_request    │
     │                            │                            │    row             │
     │                            │                            │                    │
     │ 10. next poll tick         │                            │                    │
     │ ─────────────────────────► │                            │                    │
     │     GET /sessions/{id}     │ assemble turns from rows   │                    │
     │ 11. {data: {turns, ...}}   │                            │                    │
     │ ◄─────────────────────────│                            │                    │
     │                            │                            │                    │
     │ trace step renders         │                            │ loop until         │
     │                            │                            │ Gemma replies      │
     │                            │                            │ with plain text    │
     │                            │                            │                    │
     │                            │                            │ 12. terminal row   │
     │                            │                            │     INSERT         │
     │                            │                            │ 13. task done →    │
     │                            │                            │     pop from       │
     │                            │                            │     _running_tasks │
     │                            │                            │                    │
     │ 14. next poll tick sees    │                            │                    │
     │     status === "idle"      │                            │                    │
     │ ─────────────────────────► │                            │                    │
     │ 15. {data: {turns, status: │                            │                    │
     │      "idle", ...}}         │                            │                    │
     │ ◄─────────────────────────│                            │                    │
     │                            │                            │                    │
     │ polling effect tears down  │                            │                    │
     │ composer unlocks           │                            │                    │
```

Steps 7 → 11 repeat per poll tick while the agent loops. Step 12 is
the final round-trip where Gemma returns plain text instead of a
`functionCall`. The next poll tick after that (step 14) sees the task
out of `_running_tasks` and flips the client to idle.

Latency cost: up to 2 s between a row landing and the UI rendering
it. Worth it for "I don't have to think about reconnects, proxy
buffering, or backgrounded tabs."

---

## 4. The agent loop itself

This is what `_run_agent_bg` runs (via `run_agent` in `agent_cli/agent.py`):

```
                       ┌──────────────────────────┐
                       │  build initial `contents` │
                       │  from history + new user  │
                       │  message                  │
                       └────────────┬─────────────┘
                                    │
                                    ▼
        ┌──────────────────────────────────────────────────┐
        │  for _ in range(max_iterations=50):              │
        └──────────────────────────────────────────────────┘
                                    │
                                    ▼
                       ┌──────────────────────────┐
                       │  POST generateContent    │
                       │  with full system prompt │
                       │  + tool decls + contents │
                       │  (retries on 5xx / 429)  │
                       └────────────┬─────────────┘
                                    │
                                    ▼
                       ┌──────────────────────────┐
                       │  inspect response.parts  │
                       └─┬─────────────────────┬──┘
              has        │                     │     has functionCall
              text only  │                     │     parts (one or more)
                         ▼                     ▼
              ┌─────────────────┐   ┌──────────────────────┐
              │ TERMINAL        │   │ for each tool call:  │
              │                 │   │   run tool (with     │
              │ persist row     │   │   in-turn dedup      │
              │ (reply_text=…)  │   │   cache)             │
              │ return          │   │                      │
              └─────────────────┘   │ append model parts   │
                                    │ + functionResponse   │
                                    │ to contents          │
                                    │                      │
                                    │ persist row          │
                                    │ (tool_calls,         │
                                    │  tool_results,       │
                                    │  reply_text=thought) │
                                    │                      │
                                    │ continue loop ───────┘
                                    └──────────────────────┘
                                    │
                                    ▼ loop hits 50 iterations
                       ┌──────────────────────────┐
                       │  raise                   │
                       │  MaxIterationsReached    │
                       │  → bg task writes a      │
                       │    "I ran out of steps"  │
                       │    error row             │
                       └──────────────────────────┘
```

The **per-turn cache** (just a `dict[(name, args), result]`) means if
the model retries the same tool with the same arguments inside one
turn it gets the cached result back — saves a DB round-trip and
keeps the trace honest (the user sees the same answer if they look at
both calls).

---

## 5. The polling loop

```
client (Chat.tsx)                       server (sessions.py)
─────────────────                       ────────────────────

useEffect on [sessionId, status]:
  if status !== "running": return       (no poll while idle)

  setInterval(tick, 2000):
    GET /api/sessions/{id}        ────► _load_session_payload
                                          ↓
                                        assemble turns from
                                        chat_requests rows
    ◄─── {data: {turns, status, …}}      derive status from
                                        _running_tasks[id]

    setTurns(turns)
    setStatus(nextStatus)
    if status flipped to "idle":
      refreshSessions()                 (update sidebar)

  cleanup: clearInterval                 (fires on unmount or
                                          when status flips idle)
```

**Why polling and not SSE.** We had an SSE push working in code, but
in dev (Vite's proxy → uvicorn) it would intermittently buffer chunks
and the UI would stall at the 3-dot "thinking" bubble while the bg
task had already finished. The cost of fixing it properly (correct
proxy headers, browser keepalive tuning, fallback timer if no event
arrives within N seconds) was higher than just polling. Polling is
dumb but it always recovers on the next tick — no reconnect logic,
no proxy edge cases. At hackathon scale the extra ~5 redundant
requests per agent run is invisible.

**Why polling stops cleanly.** The effect's dep array is
`[sessionId, status, refreshSessions]`. The moment a tick sees
`status: "idle"` in the response and calls `setStatus("idle")`, React
re-runs the effect — which now returns early because of the
`status !== "running"` guard, and the previous interval is cleared
in the cleanup function. No manual teardown needed.

---

## 6. Chat state — running vs idle

There are only two states. They're not stored in the database; they're
derived at read time from `_running_tasks` in-memory.

```
                  POST /sessions/{id}/messages
                       (creates asyncio.Task)
        ┌─────────┐ ─────────────────────────────► ┌──────────┐
        │  IDLE   │                                │ RUNNING  │
        │         │ ◄───────────────────────────── │          │
        └─────────┘     task done (finally:                   │
             │           _running_tasks.pop)                  │
             │                                                │
             │           ┌────────────────────────────────────┤
             │           │                                    │
             │           │ POST /sessions/{id}/interrupt      │
             │           │ (task.cancel() then await)         │
             │           │                                    │
             │           │ uvicorn restart wipes              │
             │           │ _running_tasks                     │
             │           │                                    │
             │           ▼                                    │
             │   any of these reasons transition              │
             │   running → idle.                              │
             │                                                │
             ▼                                                ▼
        Composer enabled                              Composer locked,
        ThinkingMessage hidden                        send button → Stop,
        No polling                                    ThinkingMessage visible,
        409 on 2nd POST is impossible                 polling every 2 s,
        by definition                                 409 on 2nd POST
```

**Subtle edge case the wire layer handles.** If you opened a chat
that's idle BUT the last assistant turn has tool-call rows and no
terminal reply, the bg task died mid-flight (usually because uvicorn
`--reload` killed the process). The serializer injects a soft
`error.code: "stopped"` so the UI shows *"the agent stopped before
finishing this turn"* instead of a silent empty bubble.

---

## 7. Failure modes and what the UI shows

| Failure | What the bg task does | What the UI sees |
|---|---|---|
| Model returns 5xx, 429 | `_call_model` retries (30/60/120s on 429, expo backoff on 5xx). On 429: synthetic `__rate_limited` trace step persisted so user sees "retrying in 60s" yellow note | Yellow `TriangleAlert` bubble inside the trace, with the wait time and timestamp inline |
| Model returns 4xx (bad request) | `UpstreamModelError` raised after one row written with `error={status, body, model}` | Red `OctagonAlert` bubble: "Chat failed. <Model> returned HTTP 400. <message>" + hint with model + Google status code, timestamp inline on the last line |
| User clicks Stop | `interrupt` route → `task.cancel()` → `CancelledError` in `run_agent` → `_finalize_error("You interrupted…", code="interrupted")` writes a synthetic row | Yellow note: "You interrupted the agent. Send a new message to continue." |
| Agent loop hits 50 iterations | `MaxIterationsReached` raised → `_finalize_error("I couldn't reach a final answer…", code="max_iterations")` | Red `OctagonAlert` bubble: "Chat failed." + step-budget message |
| uvicorn restarts mid-run | `_running_tasks` wiped, task dead. Wire layer's read-time check injects `error.code: "stopped"` on the orphan assistant turn | Red `OctagonAlert` bubble: "Chat failed. The agent stopped before finishing this turn. Likely the server restarted mid-run." |
| Connection drops (wifi flip) | Nothing — bg task is decoupled from the client | Polling fetch fails silently; next tick succeeds (~2 s blind window) |
| Tab closed during run | Nothing — bg task keeps running on the server | When the user comes back and opens the chat, the initial GET shows whatever rows landed |
| Generic exception in agent loop | `_finalize_error("Agent crashed: <err>", hint="code: server_error")` writes a synthetic row | Red `OctagonAlert` bubble: "Chat failed. Agent crashed: <err>" + hint `code: server_error` |

---

## 8. Reply-tail parsing (`<STRUCTURED_CARD>` + `<SUGGESTIONS>`)

The agent's terminal reply has three parts (defined in the system
prompt's REPLY FORMAT section):

1. Prose summary (1–3 sentences).
2. Optional `<STRUCTURED_CARD>` block — newline-separated tool names
   whose latest call's data should mount as a rich card.
3. Required `<SUGGESTIONS>` block — exactly 3 next-user-message prompts.

`parseReplyTail` in `apps/web/src/components/StructuredCards.tsx`
extracts both blocks and returns the cleaned prose. Critically, the
regexes are **tolerant of unclosed tags**:

```js
/<STRUCTURED_CARD>([\s\S]*?)(?:<\/STRUCTURED_CARD>|(?=<SUGGESTIONS>)|$)/
/<SUGGESTIONS>([\s\S]*?)(?:<\/SUGGESTIONS>|$)/
```

Each block matches up to its explicit closing tag, OR (for
`STRUCTURED_CARD`) the next-block opener, OR end-of-string. This
heals model output that drops the closing tag — which Gemini Flash
has been observed to do under pressure. Without this fallback, a
missing `</SUGGESTIONS>` would leak the literal `<SUGGESTIONS>` text
into the rendered bubble and emit zero chips.

The system prompt also reinforces the closing-tag rule with a
CRITICAL line and a fully-closed example. Belt and suspenders:
prompt reduces frequency of bad output, parser handles whatever
slips through.

---

## 9. Timestamps on every bubble

Every visible message-shaped element in the chat carries a
right-aligned `text-xs text-gray-400` timestamp:

- User bubble, assistant reply, tool-call card → `MessageReactions`
  footer (also surfaces token usage + model id when present)
- ThinkingMessage (3-dot pulse), ThoughtBubble → `MessageReactions`
  at the bottom of the bubble
- Info / warning / error bubbles (PrivacyBanner, rate-limited,
  interrupted, Chat failed) → inline `<span>{formatTime(ts)}</span>`
  on the **last line** of the bubble's text content, using
  `flex items-end justify-between` so single-line bubbles share the
  row and multi-line bubbles align the timestamp to the bottom-right
  corner

Timestamps are pinned via `useMemo` so they don't drift on poll-tick
re-renders. ThinkingMessage captures its timestamp on mount; all
others use the row's `date_created` (assistant turns) or
`Date.now()` (the optimistic user-bubble paint before the POST
returns).

---

## 10. Two paths that aren't obvious from the directory layout

**The agent calls into the *same* server it runs on.** When the
agent's `find_prices` tool fires, it doesn't query MySQL directly —
it makes an HTTP request to `http://127.0.0.1:8000/api/agent/tools/find_prices`.
This is a loop, but a useful one: it means the CLI agent and the
chat agent share the exact same data layer, and the tool surface is
documented as an HTTP API (in `docs/database_and_api.md`) rather than
a Python module. The `API_BASE_URL` env var lets you point the CLI
at a deployed API for remote debugging.

**The "turn" abstraction is a frontend invention.** The DB stores
flat `chat_requests` rows — one per Gemma round-trip. The wire layer
walks them in `date_created` order and groups consecutive rows that
share the same `user_message` into a `Turn`. That's why the
placeholder row (just `user_message` set, no response yet) is enough
to render the user bubble before the bg task has done anything: the
group of "rows with this user_message" has one row, and the group
serializes to one user turn + an empty assistant turn (which renders
as `ThinkingMessage` while running).

If you ever wanted to add e.g. user-edited messages, branching, or
retries, the `chat_requests`-as-flat-log model is what you'd extend
— add a `branch_id` column, group by `(branch_id, user_message)`,
and the wire layer stays largely the same.
