// Footer row for AI messages and tool-call cards: timestamp + optional
// per-turn Gemini token usage (revealed via a debug-icon tooltip).
// Thumbs reactions were removed per request.

import { Bot } from "lucide-react";
import { cn } from "../lib/cn";
import { InfoTooltip } from "./InfoTooltip";

type TokenUsage = {
  input: number;
  output: number;
  thought: number;
  total: number;
};

export function MessageReactions({
  timestamp,
  tokens,
  model,
  className,
}: {
  timestamp: number;
  tokens?: TokenUsage;
  model?: string;
  className?: string;
}) {
  const showDebug = (tokens && tokens.total > 0) || !!model;
  return (
    <div
      className={cn(
        "flex items-center justify-end gap-2 text-xs text-gray-400",
        className,
      )}
    >
      {showDebug && (
        <InfoTooltip
          width={240}
          ariaLabel="Model + token usage (debug)"
          icon={<Bot className="h-3.5 w-3.5" strokeWidth={2.5} />}
          triggerClassName="h-4 w-4 text-gray-400"
          contentClassName="tabular-nums space-y-0.5"
        >
          {model && (
            <div className="pb-1 border-b border-gray-100 mb-1 break-all">
              Model: {model}
            </div>
          )}
          {tokens && tokens.total > 0 && (
            <>
              <div>Input: {tokens.input.toLocaleString()}</div>
              <div>Output: {tokens.output.toLocaleString()}</div>
              {tokens.thought > 0 && (
                <div>Thinking: {tokens.thought.toLocaleString()}</div>
              )}
              <div className="pt-1 border-t border-gray-100 mt-1">
                Total: {tokens.total.toLocaleString()}
              </div>
            </>
          )}
        </InfoTooltip>
      )}
      <span>{formatTime(timestamp)}</span>
    </div>
  );
}

export function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}
