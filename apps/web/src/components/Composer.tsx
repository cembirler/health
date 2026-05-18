// Bottom composer bar — textarea + Send/Stop button. The button toggles
// to Stop (filled square) while the agent is running so the user can
// interrupt; flips back to Send (arrow) when idle.

import { ArrowUp, Square } from "lucide-react";
import { useEffect, useRef } from "react";
import { cn } from "../lib/cn";

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  pending,
  placeholder = "Ask anything…",
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  // Click handler for the Stop button. When omitted, Stop is hidden even
  // while pending — the Send button just disables instead.
  onStop?: () => void;
  // Agent is currently working. Textarea locks; right-side button becomes
  // Stop (if onStop given) or stays disabled Send (if not).
  pending?: boolean;
  placeholder?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  // Auto-grow textarea up to ~10 lines.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  }, [value]);

  const canSend = !pending && value.trim().length > 0;
  const showStop = pending && !!onStop;

  return (
    <div className="border-t border-gray-200 bg-white py-4">
      <div className="px-3 md:px-[15%]">
        <div className="flex items-end gap-2 rounded-2xl border border-gray-200 bg-transparent px-4 py-3 focus-within:ring-2 focus-within:ring-gray-200 focus-within:border-gray-300 transition">
          <textarea
            ref={ref}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (canSend) onSend();
              }
            }}
            rows={3}
            placeholder={placeholder}
            disabled={pending}
            className="flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-black placeholder:text-gray-500 focus:outline-none disabled:opacity-60 min-h-[72px]"
          />
          {showStop ? (
            <button
              type="button"
              onClick={onStop}
              className="flex h-9 w-9 items-center justify-center rounded-full transition flex-shrink-0 bg-gray-900 text-white hover:bg-gray-700"
              aria-label="Stop"
              title="Stop the agent"
            >
              <Square className="h-3.5 w-3.5" fill="currentColor" />
            </button>
          ) : (
            <button
              type="button"
              onClick={onSend}
              disabled={!canSend}
              className={cn(
                "flex h-9 w-9 items-center justify-center rounded-full transition flex-shrink-0",
                canSend
                  ? "bg-orange-400 text-black hover:bg-orange-500"
                  : "bg-gray-200 text-gray-400 cursor-not-allowed",
              )}
              aria-label="Send"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
