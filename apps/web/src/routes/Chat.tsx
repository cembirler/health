// /chat and /chat/:sessionId — price-transparency agent, wired to
// POST /api/sessions/:id/messages and persisted via PATCH /api/sessions/:id.
//
// Sidebar (25%) lists past sessions. New sessions get a 12-char hex id minted
// on the first user message; URL is rewritten to /chat/<id>. Reloading the
// URL or clicking a sidebar entry hydrates the session via GET /api/sessions/<id>.

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Plus, Trash2, X, Menu } from "lucide-react";
import { Conversation } from "../components/Conversation";
import {
  AssistantMessage,
  ThinkingMessage,
  UserMessage,
} from "../components/Message";
import { Composer } from "../components/Composer";
import { SiteHeader } from "../components/SiteHeader";
import type { TraceStep } from "../components/ToolCallBlock";
import { cn } from "../lib/cn";

type TokenUsage = {
  input: number;
  output: number;
  thought: number;
  total: number;
};

type Turn =
  | { role: "user"; text: string; timestamp?: number }
  | {
    role: "assistant";
    reply: string;
    trace: TraceStep[];
    timestamp?: number;
    tokens?: TokenUsage;
    model?: string;
    error?: { msg: string; hint?: string; code?: string };
  };

type SessionStatus = "idle" | "running";

type SessionSummary = {
  id: string;
  title: string;
  // ISO timestamp the session was first created. The wire intentionally
  // doesn't carry an `updated_at` field — the server still uses one
  // internally to order the sidebar (most-recently-active first), but the
  // bubble shows "when this chat started", which is more useful for
  // recognizing entries.
  created_at: string;
  status?: SessionStatus;
  message_count: number;
};

type SessionDetail = SessionSummary & {
  turns: Turn[];
};

type WhoamiData = {
  ip: string | null;
  city: string | null;
  region: string | null;
  region_name: string | null;
  zip: string | null;
};

const WELCOME =
  "👋 Hi — I find U.S. hospital prices from MRFs that the CMS requires hospitals to publish.\n\n• **Costs** at hospitals near you or by name\n• **What your insurer pays** — name them (Anthem, Aetna, BCBS, UHC…)\n• **Compare** hospitals or check if a price is fair\n\nWhat brings you here today?";

// Welcome chips shown ONLY on a fresh conversation, before the first
// agent turn. After any assistant reply, follow-up suggestions come from
// the agent's <SUGGESTIONS> tail (context-aware) instead.
//
// The location slot is filled from the visitor's IP-derived geo so the
// very first chip set already feels like "near me"; when no geo is
// available it collapses to the literal phrase "near me".
function starterExamples(whoami: WhoamiData | null): string[] {
  const place =
    whoami?.city ?? whoami?.region_name ?? whoami?.region ?? null;
  const cityPhrase = place ? `in ${place}` : "near me";
  return [
    `What % does Anthem cover for a therapy session ${cityPhrase}?`,
    `Cheapest hospitals near me for an annual checkup?`,
    `How much does Ozempic cost, with and without insurance?`,
  ];
}

// 12-char lowercase hex id — short enough for URLs, ~10^14 collision space
// (plenty for hackathon scale; not security-grade).
function newSessionId(): string {
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

// localStorage-backed "my chats" list. Per-browser isolation: each
// visitor keeps their own list and the sidebar fetches just those. No
// cookies, no server-side ownership — a URL shared with someone else is
// still viewable by them (chat lookup by id is open), but the sidebar
// stays scoped to chats they themselves have interacted with.
const CHAT_IDS_KEY = "chat_ids";

function loadChatIds(): string[] {
  try {
    const raw = localStorage.getItem(CHAT_IDS_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // Defensive shape check — anything non-string-ish gets dropped.
    return parsed.filter(
      (x): x is string => typeof x === "string" && /^[a-z0-9]{6,32}$/.test(x),
    );
  } catch {
    return [];
  }
}

function saveChatIds(ids: string[]): void {
  try {
    localStorage.setItem(CHAT_IDS_KEY, JSON.stringify(ids));
  } catch {
    // Quota errors are best-effort; ignore.
  }
}

function rememberChatId(id: string): void {
  const ids = loadChatIds();
  if (ids.includes(id)) return;
  ids.push(id);
  saveChatIds(ids);
}

function forgetChatId(id: string): void {
  saveChatIds(loadChatIds().filter((x) => x !== id));
}

export function Chat() {
  const { sessionId } = useParams<{ sessionId?: string }>();
  const navigate = useNavigate();

  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  // Server-owned chat status. The agent runs as a background task on the
  // backend and writes incremental updates to disk; we poll while it's
  // running. `pending` (composer disabled, ThinkingMessage shown) is just
  // derived from this — there's no separate client-side "is this fetch in
  // flight" flag anymore.
  const [status, setStatus] = useState<SessionStatus>("idle");
  const pending = status === "running";
  const [scrollSignal, setScrollSignal] = useState(0);
  // Welcome timestamp is captured on mount for fresh chats, but rehydrated
  // from the session's `created_at` when loading an existing one — otherwise
  // a refresh would bump the timestamp every time.
  const [welcomeTs, setWelcomeTs] = useState<number>(() => Date.now());
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loadingSession, setLoadingSession] = useState(false);
  // What the agent will see about the visitor on the next message. Fetched
  // once on mount from /api/meta/whoami — same lookup chain the backend
  // runs when handling a real message, so the banner shows the actual
  // values that would flow into `request_context`.
  const [whoami, setWhoami] = useState<WhoamiData | null>(null);
  // Sidebar drawer state on mobile (<md). Inline on md+ so this flag is
  // ignored above the breakpoint. Auto-closes whenever the active session
  // changes so picking a chat from the drawer dismisses it.
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  useEffect(() => {
    setMobileSidebarOpen(false);
  }, [sessionId]);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/meta/whoami")
      .then(async (r) => (r.ok ? ((await r.json()) as { data: WhoamiData }) : null))
      .then((j) => {
        if (!cancelled && j) setWhoami(j.data);
      })
      .catch(() => { /* banner is best-effort */ });
    return () => {
      cancelled = true;
    };
  }, []);

  // Tracks which session id the chat page is currently focused on. Updated
  // whenever the URL :sessionId param changes. Used by `send()` so that an
  // in-flight fetch only writes its result into UI state if the user is still
  // looking at the same session — but it ALWAYS persists to disk so the
  // result survives navigation.
  const activeSessionRef = useRef<string | undefined>(sessionId);

  function bump() {
    setScrollSignal((n) => n + 1);
  }

  const refreshSessions = useCallback(async () => {
    const ids = loadChatIds();
    if (ids.length === 0) {
      setSessions([]);
      return;
    }
    try {
      const r = await fetch(
        `/api/sessions?ids=${encodeURIComponent(ids.join(","))}`,
      );
      if (!r.ok) return;
      const j = (await r.json()) as { data: SessionSummary[] };
      setSessions(j.data);
      // Self-heal: any id we sent but the server didn't return is a
      // chat that's been deleted (typically from another browser or by
      // a DB cleanup). Prune it from localStorage so the list doesn't
      // accumulate dead refs over time.
      const returned = new Set(j.data.map((s) => s.id));
      const survivors = ids.filter((id) => returned.has(id));
      if (survivors.length !== ids.length) saveChatIds(survivors);
    } catch {
      // Sidebar is best-effort; ignore.
    }
  }, []);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  // Load session content when :sessionId in URL changes (or clear when absent).
  useEffect(() => {
    activeSessionRef.current = sessionId;
    if (!sessionId) {
      setTurns([]);
      setStatus("idle");
      return;
    }
    let cancelled = false;
    setLoadingSession(true);
    (async () => {
      try {
        const r = await fetch(`/api/sessions/${sessionId}`);
        if (!r.ok) {
          if (!cancelled) {
            setTurns([]);
            setStatus("idle");
          }
          return;
        }
        const j = (await r.json()) as { data: SessionDetail };
        if (!cancelled) {
          setTurns(j.data.turns ?? []);
          setStatus(j.data.status ?? "idle");
          // Upsert into the sidebar list so the header title resolves even
          // when this URL was opened in a browser that never owned the
          // chat (no entry in localStorage → refreshSessions skipped it).
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          const { turns: _t, ...summary } = j.data;
          setSessions((prev) =>
            prev.some((s) => s.id === summary.id)
              ? prev.map((s) => (s.id === summary.id ? { ...s, ...summary } : s))
              : [summary, ...prev],
          );
          // Pin the welcome timestamp to the session's created_at so it
          // doesn't change on every refresh.
          if (j.data.created_at) {
            const ts = new Date(j.data.created_at).getTime();
            if (!Number.isNaN(ts)) setWelcomeTs(ts);
          }
          bump();
        }
      } finally {
        if (!cancelled) setLoadingSession(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Polling loop: while the server reports `status: running`, GET the
  // session every 2 s and update the UI. The agent appends each tool
  // step to disk as it completes, so the trace streams in. Stops as
  // soon as status flips to "idle".
  //
  // (We tried SSE here; the dev proxy buffered the stream and the loop
  // would silently freeze. Polling is dumb but it always recovers on
  // the next tick.)
  useEffect(() => {
    if (!sessionId || status !== "running") return;
    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      try {
        const r = await fetch(`/api/sessions/${sessionId}`);
        if (!r.ok || cancelled) return;
        const j = (await r.json()) as { data: SessionDetail };
        if (cancelled) return;
        setTurns(j.data.turns ?? []);
        const nextStatus = j.data.status ?? "idle";
        setStatus(nextStatus);
        bump();
        if (nextStatus !== "running") {
          // Agent finished — refresh the sidebar so the title/timestamp
          // update.
          refreshSessions();
        }
      } catch {
        // Transient network failure — keep polling.
      }
    };
    const id = setInterval(tick, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [sessionId, status, refreshSessions]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || pending) return;

    setInput("");

    // Mint a session id on the first user message of a fresh chat. Navigate
    // updates the URL but doesn't unmount us — we still pass `effectiveId`
    // to the POST so we don't race the param update.
    const effectiveId = sessionId ?? newSessionId();
    if (!sessionId) {
      navigate(`/chat/${effectiveId}`, { replace: true });
    }
    // Claim this chat as "mine" in this browser. Idempotent — also
    // covers the case where someone opens a chat URL someone else
    // shared and then sends a message; from that point on, it's in
    // their sidebar too.
    rememberChatId(effectiveId);

    // Optimistic user-turn paint + flip to running so the polling effect
    // starts immediately and the composer locks. The POST returns <100ms
    // with the authoritative state; the agent itself runs as a server-side
    // background task that survives tab navigation / close.
    const turnsAfterUser: Turn[] = [
      ...turns,
      { role: "user", text: trimmed, timestamp: Date.now() },
    ];
    setTurns(turnsAfterUser);
    setStatus("running");
    bump();

    let r: Response;
    try {
      r = await fetch(`/api/sessions/${effectiveId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: trimmed,
          display_text: trimmed,
          client_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        }),
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (activeSessionRef.current === effectiveId) {
        setTurns([
          ...turnsAfterUser,
          {
            role: "assistant",
            reply: "",
            trace: [],
            error: { msg: `Network error: ${msg}`, hint: "Is the API running?" },
            timestamp: Date.now(),
          },
        ]);
        setStatus("idle");
        bump();
      }
      return;
    }

    if (!r.ok) {
      let detail: unknown = null;
      try {
        const j = await r.json();
        detail = (j as { detail?: unknown })?.detail ?? j;
      } catch {
        detail = `HTTP ${r.status} ${r.statusText}`;
      }
      const d =
        (detail && typeof detail === "object"
          ? (detail as Record<string, unknown>)
          : {}) ?? {};
      const msg =
        (d.error as string) ||
        (typeof detail === "string" ? detail : `HTTP ${r.status}`);
      const meta: string[] = [];
      if (d.code) meta.push(`code: ${String(d.code)}`);
      if (activeSessionRef.current === effectiveId) {
        setTurns([
          ...turnsAfterUser,
          {
            role: "assistant",
            reply: "",
            trace: [],
            error: { msg, hint: meta.join(" · ") },
            timestamp: Date.now(),
          },
        ]);
        setStatus("idle");
        bump();
      }
      return;
    }

    // Server already appended the user turn and flipped status to "running".
    // Sync the authoritative state; the polling effect will then stream tool
    // steps and the final reply into UI as the bg task makes progress.
    try {
      const j = (await r.json()) as { data: SessionDetail };
      if (activeSessionRef.current === effectiveId) {
        setTurns(j.data.turns ?? turnsAfterUser);
        setStatus(j.data.status ?? "running");
        bump();
      }
    } catch {
      // Body parse failed — polling will reconcile on the next tick.
    }
    refreshSessions();
  }

  function startNewChat() {
    navigate("/chat");
    setTurns([]);
    setInput("");
  }

  // Stop button handler — fires the interrupt endpoint and flips status
  // to idle optimistically so the composer unlocks instantly. The backend
  // cancels the asyncio task AND writes a synthetic assistant turn carrying
  // `error.code: "interrupted"`, which renders as a soft "chat interrupted"
  // note in the thread. We refetch once after the POST resolves so that
  // turn lands in the UI — the polling loop won't do it for us because we
  // just flipped status to idle.
  async function interruptCurrent() {
    if (!sessionId || !pending) return;
    const id = sessionId;
    setStatus("idle");  // optimistic — UI unlocks immediately
    try {
      await fetch(`/api/sessions/${id}/interrupt`, { method: "POST" });
    } catch {
      // Best-effort. Continue to refetch even on POST failure — the
      // backend may still have recorded the interrupt.
    }
    if (activeSessionRef.current !== id) return;
    try {
      const r = await fetch(`/api/sessions/${id}`);
      if (!r.ok || activeSessionRef.current !== id) return;
      const j = (await r.json()) as { data: SessionDetail };
      setTurns(j.data.turns ?? []);
      setStatus(j.data.status ?? "idle");
      bump();
    } catch {
      // Best-effort.
    }
  }

  // Hard-delete — removes the row entirely (cascade drops turns + steps).
  // Wrapped in the sidebar's confirmation toast so an accidental click
  // doesn't lose data.
  async function deleteSession(id: string) {
    setSessions((prev) => prev.filter((s) => s.id !== id));
    forgetChatId(id);
    if (id === sessionId) {
      navigate("/chat");
      setTurns([]);
    }
    try {
      await fetch(`/api/sessions/${id}`, { method: "DELETE" });
    } catch {
      // Best-effort.
    }
  }


  // Static welcome chips — ONLY shown on a brand-new chat (no turns yet).
  // Once the conversation starts, follow-up suggestions come from the
  // agent's `render_followups` card (so they're context-aware), not from
  // the static list — otherwise the user would see two suggestion strips.
  const showChips = !pending && !loadingSession && turns.length === 0;
  const promptSet = starterExamples(whoami);

  return (
    <div className="flex flex-col h-screen bg-white">
      <SiteHeader />

      <div className="flex flex-1 min-h-0 relative">
        <ChatSidebar
          sessions={sessions}
          currentId={sessionId}
          onNew={startNewChat}
          onDelete={deleteSession}
          mobileOpen={mobileSidebarOpen}
          onMobileClose={() => setMobileSidebarOpen(false)}
        />
        {/* Backdrop — visible only when the drawer is open on a mobile
            viewport. Click anywhere to dismiss. Hidden on md+ where the
            sidebar is inline and the drawer state is meaningless. */}
        {mobileSidebarOpen && (
          <div
            className="fixed inset-0 z-20 bg-black/30 md:hidden"
            onClick={() => setMobileSidebarOpen(false)}
            aria-hidden
          />
        )}

        <div className="flex flex-1 flex-col min-w-0">
          {/* Hamburger toggle — only rendered below md. Sits above the
              thread header so it's reachable whether or not a session is
              loaded. */}
          <button
            type="button"
            onClick={() => setMobileSidebarOpen(true)}
            className="md:hidden flex items-center gap-2 px-3 py-2 border-b border-gray-200 text-sm text-gray-700 hover:bg-gray-50 transition"
            aria-label="Open chat list"
          >
            <Menu className="h-4 w-4" />
            <span>Chats</span>
          </button>
          <Conversation className="bg-white" scrollSignal={scrollSignal}>
            <div className="px-3 md:px-[15%]">
              <AssistantMessage
                steps={[]}
                reply={WELCOME}
                timestamp={welcomeTs}
                agentName="Health Price Transparency Agent"
              />

              {turns.map((t, i) => {
                if (t.role === "user") {
                  return (
                    <UserMessage
                      key={i}
                      text={t.text}
                      timestamp={t.timestamp}
                    />
                  );
                }
                const isLastTurn = i === turns.length - 1;
                return (
                  <AssistantMessage
                    key={i}
                    steps={t.trace}
                    reply={t.reply}
                    error={t.error}
                    timestamp={t.timestamp}
                    tokens={t.tokens}
                    model={t.model}
                    agentName="Health Price Transparency Agent"
                    onSendNext={(text) => send(text)}
                    isLatestTurn={isLastTurn}
                  />
                );
              })}
              {pending && <ThinkingMessage agentName="Health Price Transparency Agent" />}

              {showChips && (
                <div className="w-full max-w-full md:max-w-[85%] mr-auto py-2">
                  <ExampleChips prompts={promptSet} onPick={send} />
                </div>
              )}
            </div>
          </Conversation>

          <Composer
            value={input}
            onChange={setInput}
            onSend={() => send(input)}
            onStop={interruptCurrent}
            pending={pending}
          />
        </div>
      </div>
    </div>
  );
}

function ChatSidebar({
  sessions,
  currentId,
  onNew,
  onDelete,
  mobileOpen,
  onMobileClose,
}: {
  sessions: SessionSummary[];
  currentId: string | undefined;
  onNew: () => void;
  onDelete: (id: string) => void;
  // Mobile-only: drawer open state + dismiss callback. Ignored on md+
  // where the sidebar is permanently inline.
  mobileOpen: boolean;
  onMobileClose: () => void;
}) {
  return (
    <aside
      className={cn(
        // Shared chrome (border / surface / column layout).
        "border-r border-gray-200 bg-gray-50 flex flex-col min-h-0",
        // Mobile (<md): fixed-position drawer that slides in from the
        // left when `mobileOpen` is true. We always render it so the
        // CSS transition has something to animate against, but it lives
        // off-screen (-translate-x-full) when closed.
        "fixed inset-y-0 left-0 z-30 w-72 transition-transform duration-200",
        mobileOpen ? "translate-x-0" : "-translate-x-full",
        // md+ : revert to a static, inline column. The transform reset
        // is important — Tailwind's `md:translate-x-0` would still hold,
        // but we also need `md:relative` so it joins the flex row instead
        // of overlaying it.
        "md:relative md:translate-x-0 md:w-[30%] md:min-w-[240px] md:max-w-[400px] md:flex-shrink-0",
      )}
    >
      <div className="px-3 py-3 border-b border-gray-200 flex items-center gap-2">
        <button
          type="button"
          onClick={onNew}
          className="flex flex-1 items-center justify-center gap-2 rounded-md bg-blue-900 text-white text-sm font-medium px-3 py-2 hover:bg-blue-950 transition"
        >
          <Plus className="h-4 w-4" /> New chat
        </button>
        {/* Close-drawer button — only meaningful below md. On md+ the
            sidebar is inline and there's nothing to close. */}
        <button
          type="button"
          onClick={onMobileClose}
          className="md:hidden grid h-9 w-9 place-items-center rounded-md text-gray-500 hover:bg-gray-200 transition"
          aria-label="Close chat list"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {sessions.length === 0 ? (
          <div className="px-3 py-3 text-xs text-gray-400">No chats yet.</div>
        ) : (
          <ul className="flex flex-col divide-y divide-gray-200 px-2">
            {sessions.map((s) => (
              <li key={s.id} className="group">
                <Link
                  to={`/chat/${s.id}`}
                  className={cn(
                    "block rounded-md px-3 py-2 text-sm leading-tight transition",
                    s.id === currentId
                      ? "bg-blue-50 text-blue-900"
                      : "text-gray-700 hover:bg-gray-100",
                  )}
                >
                  <div className="truncate text-black">{s.title}</div>
                  <div className="flex items-center justify-between gap-2 mt-1">
                    <span className="text-xs text-gray-400 truncate">
                      {formatTimestamp(s.created_at)}
                    </span>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        if (window.confirm(`Delete "${s.title}"?`)) {
                          onDelete(s.id);
                        }
                      }}
                      className="grid h-6 w-6 flex-shrink-0 place-items-center rounded text-gray-400 hover:bg-gray-200 hover:text-red-600 transition"
                      aria-label="Delete chat"
                      title="Delete chat (permanent)"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}

function formatTimestamp(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  // Match the AM/PM time format used by the in-bubble message timestamps.
  return d.toLocaleString([], {
    month: "numeric",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function ExampleChips({
  prompts,
  onPick,
}: {
  prompts: readonly string[];
  onPick: (text: string) => void;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-gray-400 pb-2 mb-3 border-b border-gray-200 font-medium">
        Suggestions
      </div>
      <ul className="space-y-1.5">
        {prompts.map((q) => (
          <li key={q}>
            <button
              type="button"
              onClick={() => onPick(q)}
              className="rounded-full border border-orange-200 bg-orange-50 px-3.5 py-1.5 text-sm text-left text-black hover:bg-orange-100 hover:border-orange-300 transition"
            >
              {q}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

