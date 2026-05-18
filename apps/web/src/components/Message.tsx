// User message: orange bubble that hugs its text and right-aligns to the
// message column. Used in both /chat and / (the sample conversation on Home).
// Matches the orange suggestion chips so user-side accents stay consistent.
//
// Assistant message: a single column with an "Agent name" header (styled like
// the tool-name header inside ToolCallBlock), then the tool-call cards, then
// the reply bubble. No avatar, no timeline dots, no connecting line — just
// the agent label, the cards, and the reply.

import { useMemo } from "react";
import { Brain, HeartPulse, OctagonAlert, TriangleAlert } from "lucide-react";
import { ToolCallBlock, type TraceStep } from "./ToolCallBlock";
import {
  ToolResultCard,
  SuggestedActionsCard,
  parseReplyTail,
} from "./StructuredCards";
import { MessageReactions, formatTime } from "./MessageReactions";
import { MarkdownText } from "./MarkdownText";
import { cn } from "../lib/cn";

export function UserMessage({
  text,
  timestamp,
}: {
  text: string;
  timestamp?: number;
}) {
  // Stable timestamp: capture once on mount if not supplied.
  const ts = useMemo(() => timestamp ?? Date.now(), [timestamp]);
  return (
    <div className="flex w-full py-2 justify-end">
      <div className="overflow-hidden text-sm break-words px-4 py-3 rounded-2xl bg-orange-50 text-black rounded-br-md whitespace-pre-wrap border border-orange-100 max-w-full md:max-w-[85%]">
        {text}
        <MessageReactions timestamp={ts} className="mt-2" />
      </div>
    </div>
  );
}

export type TokenUsage = {
  input: number;
  output: number;
  thought: number;
  total: number;
};

export function AssistantMessage({
  steps,
  reply,
  error,
  timestamp,
  tokens,
  model,
  agentName = "Agent",
  onSendNext,
  isLatestTurn = false,
}: {
  steps: TraceStep[];
  reply: string;
  error?: { msg: string; hint?: string; code?: string };
  timestamp?: number;
  // Per-turn Gemini token usage, summed across every LLM iteration in
  // this turn block. Shown in the footer next to the timestamp.
  tokens?: TokenUsage;
  model?: string;
  // Shown at the top of the message in the same style as tool-call labels.
  agentName?: string;
  // Click-to-send handler used by interactive cards (e.g. CodeListCard
  // and HospitalListCard picker rows).
  onSendNext?: (text: string) => void;
  // Only render the <SUGGESTIONS> strip on the most-recent assistant
  // turn. Older turns' suggestions are stale (the user has already
  // moved past them) and stacking them looks redundant.
  isLatestTurn?: boolean;
}) {
  const toolSteps = steps.filter((s) => s.action);
  // Stable timestamp: capture once on mount if not supplied. useMemo with
  // [timestamp] dep means re-renders don't bump the time on the welcome card.
  const ts = useMemo(() => timestamp ?? Date.now(), [timestamp]);

  // Skip the agent label on tool-execution turns — the tool-name
  // labels above each call (🔧 tool_name) already mark the agent's voice,
  // and stacking another label on top reads as duplicate noise.
  const showAgentLabel = toolSteps.length === 0;

  // The agent's last reply has up to three structured parts: prose,
  // <STRUCTURED_CARD> (which tool outputs to surface), and <SUGGESTIONS>.
  const { cleanReply, cardToolNames, suggestions } = parseReplyTail(reply);

  // Resolve each requested tool name to the latest matching trace step.
  const cardSteps: TraceStep[] = cardToolNames
    .map((name) => {
      for (let i = toolSteps.length - 1; i >= 0; i--) {
        if (toolSteps[i].action === name) return toolSteps[i];
      }
      return null;
    })
    .filter((s): s is TraceStep => s !== null);

  return (
    <div className="flex w-full flex-col py-2 mr-auto max-w-full md:max-w-[85%] gap-2">
      {showAgentLabel && <AgentLabel name={agentName} />}

      {toolSteps.map((s, i) => {
        // Synthetic "agent is recovering" step emitted by _call_model when
        // it hits a 429 and is about to sleep + retry. Renders as a soft
        // yellow note instead of a ToolCallBlock so users see the agent
        // working through a rate limit rather than a frozen spinner.
        if (s.action === "__rate_limited") {
          const args = s.action_input ?? {};
          const secs =
            typeof args.retry_after_seconds === "number"
              ? Math.round(args.retry_after_seconds)
              : null;
          const msg =
            secs !== null
              ? `Rate limited, retrying in ${secs}s…`
              : "Rate limited, retrying…";
          return (
            <div
              key={i}
              className="flex items-start gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700 leading-snug"
            >
              <OctagonAlert
                className="h-4 w-4 flex-shrink-0 mt-0.5"
                strokeWidth={2.5}
              />
              <div className="min-w-0 flex-1 flex items-end justify-between gap-2">
                <span>{msg}</span>
                <span className="text-xs text-red-700/70 tabular-nums shrink-0">
                  {formatTime(ts)}
                </span>
              </div>
            </div>
          );
        }
        const cleanThought = sanitizeThought(s.thought);
        return (
          <div key={i} className="flex flex-col gap-1.5">
            {cleanThought && <ThoughtBubble text={cleanThought} timestamp={ts} />}
            <ToolCallBlock step={s} timestamp={ts} />
          </div>
        );
      })}

      {error && (
        error.code === "interrupted" ? (
          // User clicked Stop — not a failure, so renders as a soft
          // yellow note from the `warning` palette (defined in
          // index.css's @theme block).
          <div className="flex items-start gap-1.5 rounded-lg border border-warning-200 bg-warning-50 px-3 py-2.5 text-sm text-warning leading-snug">
            <TriangleAlert
              className="h-3.5 w-3.5 flex-shrink-0 mt-0.5"
              strokeWidth={2.5}
            />
            <div className="min-w-0 flex-1 flex items-end justify-between gap-2">
              <span>{error.msg}</span>
              <span className="text-xs text-warning/70 tabular-nums shrink-0">
                {formatTime(ts)}
              </span>
            </div>
          </div>
        ) : (
          // Everything else — Gemma 4xx/5xx (`code: "upstream"`),
          // max-iterations cap, server-restart-mid-run (`stopped`),
          // generic catch-all. Same single-row layout as the rate-limit
          // bubble (above) so error variants stay visually consistent.
          // `hint` (status code + model id) is preserved as a tooltip
          // for debug rather than a second row.
          <div
            className="flex items-start gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700 leading-snug"
            title={error.hint ?? undefined}
          >
            <OctagonAlert
              className="h-4 w-4 flex-shrink-0 mt-0.5"
              strokeWidth={2.5}
            />
            <div className="min-w-0 flex-1 flex items-end justify-between gap-2">
              <span>{error.msg}</span>
              <span className="text-xs text-red-700/70 tabular-nums shrink-0">
                {formatTime(ts)}
              </span>
            </div>
          </div>
        )
      )}

      {cleanReply && (
        <div className="rounded-lg border border-gray-200 bg-gray-100 px-3 py-2.5">
          <MarkdownText text={cleanReply} />
          <MessageReactions timestamp={ts} tokens={tokens} model={model} className="mt-2" />
        </div>
      )}

      {/* Rich data cards the agent explicitly chose to surface via its
          <STRUCTURED_CARD> tail. Each tool name resolves to the latest matching
          step in the trace. */}
      {cardSteps.map((s, i) => (
        <ToolResultCard key={i} step={s} onSendNext={onSendNext} />
      ))}

      {/* Suggested follow-ups, parsed from the agent's <SUGGESTIONS>
          tail. Only show on the latest turn — older suggestions are
          stale once the user has moved past them. */}
      {isLatestTurn && suggestions.length > 0 && (
        <SuggestedActionsCard
          suggestions={suggestions}
          onSendNext={onSendNext}
        />
      )}
    </div>
  );
}

// "Thinking aloud" bubble — Gemini's thought summary above the tool call
// it precedes. Persisted in chat_requests.reply_text on rows with
// tool_calls (see agent.py: reply_text=thought_summary when call_parts
// is non-empty). Mirrors the tool-call layout: a small icon+label header
// above the content card.
function ThoughtBubble({ text, timestamp }: { text: string; timestamp?: number }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-1.5 mb-1.5">
        <Brain className="h-3.5 w-3.5 text-gray-600 flex-shrink-0" />
        <span className="text-xs font-mono font-bold text-gray-700">
          thinking
        </span>
      </div>
      <div className="rounded-lg border border-gray-200 bg-gray-50/60 px-3 py-2 text-sm italic text-gray-600 whitespace-pre-wrap">
        <MarkdownText text={text} />
        {timestamp != null && (
          <MessageReactions timestamp={timestamp} className="mt-2 not-italic" />
        )}
      </div>
    </div>
  );
}

// Gemini's thought summaries occasionally narrate internal protocol —
// "I'll include the <STRUCTURED_CARD> block...", "I should output <SUGGESTIONS>",
// "structure as three parts", etc. — which is meaningless and confusing
// to a user. Strip lines that mention those tags or related framing,
// and drop the bubble entirely if nothing useful is left.
//
// Heuristic only: kills lines (and trailing punctuation) that contain
// any of the protocol tokens. We err on the side of keeping content;
// a stray meta line is worse than nothing, but cutting real reasoning
// is worse than a stray line.
const _META_TOKEN_RE = /<\/?(STRUCTURED_CARD|SUGGESTIONS)>|STRUCTURED_CARD block|SUGGESTIONS block|structured_card block|suggestions block/i;

function sanitizeThought(text: string): string {
  if (!text) return "";
  const kept = text
    .split("\n")
    .filter((line) => !_META_TOKEN_RE.test(line))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return kept;
}

export function ThinkingMessage({ agentName = "Agent" }: { agentName?: string }) {
  return (
    <div className="flex w-full flex-col py-2 mr-auto max-w-full md:max-w-[85%] gap-2">
      <AgentLabel name={agentName} />
      <div className="inline-flex items-center gap-1 px-4 py-3 rounded-2xl bg-gray-100 text-gray-900 rounded-bl-md w-fit">
        <Dot delay="0ms" />
        <Dot delay="120ms" />
        <Dot delay="240ms" />
      </div>
    </div>
  );
}

// Tiny label shown above an assistant message — uses the HeartPulse icon
// (same as the SiteHeader brand mark and favicon) so the agent feels visually
// branded with the rest of the app. Icon stroke matches the label text color
// (dark gray) to read as a quiet header alongside tool-call labels.
function AgentLabel({ name }: { name: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <HeartPulse className="h-3.5 w-3.5 text-blue-900 flex-shrink-0" />
      <span className="text-xs font-mono font-bold text-gray-700">{name}</span>
    </div>
  );
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      className={cn("inline-block h-1.5 w-1.5 rounded-full bg-gray-400 animate-bounce")}
      style={{ animationDelay: delay }}
    />
  );
}
