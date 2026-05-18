// Tool-call card: tool-name header + in/out card with expandable input and
// output, both rendered via JsonRenderer. No tool-specific card overrides —
// every call shows the same JSON shape since every tool just returns the
// upstream HTTP body.

import { useState } from "react";
import { ChevronDown, ChevronUp, Wrench } from "lucide-react";
import { JsonRenderer, looksLikeError, parseObservation } from "./JsonRenderer";
import { MessageReactions } from "./MessageReactions";
import { cn } from "../lib/cn";

export interface TraceStep {
  thought: string;
  action: string | null;
  action_input: Record<string, unknown> | null;
  observation: string | null;
}

// One row: clickable header that toggles between a one-line preview and a
// JsonRenderer tree below. Shared by both `in` and `out` rows so they behave
// identically.
function CollapsibleJsonRow({
  label,
  value,
  errorStyling = false,
  defaultExpanded = false,
  divider = false,
}: {
  label: "in" | "out";
  value: unknown;
  errorStyling?: boolean;
  defaultExpanded?: boolean;
  divider?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  // Compact preview — first 120 chars on a single line. We unwrap the
  // agent's run_tool `{result: ...}` envelope first so the preview
  // reflects the actual payload — otherwise `"result":` would chew up
  // the leading ~12 chars of every collapsed OUT row. The expanded view
  // (JsonRenderer) does the same unwrap independently, so both surfaces
  // agree.
  const preview = (() => {
    if (value === null || value === undefined) return "";
    let v: unknown = value;
    if (
      typeof v === "object" &&
      v !== null &&
      !Array.isArray(v) &&
      Object.keys(v as object).length === 1 &&
      "result" in (v as object)
    ) {
      v = (v as { result: unknown }).result;
    }
    const raw = typeof v === "string" ? v : JSON.stringify(v);
    return raw.slice(0, 120).replace(/\s+/g, " ");
  })();
  const isTruncated = preview.length >= 120;

  const headerBg = errorStyling
    ? "bg-red-50 hover:bg-red-100"
    : label === "in"
      ? "bg-gray-50 hover:bg-gray-100"
      : "bg-white hover:bg-gray-50";
  const labelColor = errorStyling ? "text-red-400" : "text-gray-400";
  const previewColor = errorStyling ? "text-red-500" : "text-gray-500";
  const dividerCls = divider ? "border-t border-gray-100" : "";

  return (
    <>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={cn(
          "w-full flex items-center gap-2 px-3 py-2 text-left transition-colors cursor-pointer",
          headerBg,
          dividerCls,
        )}
      >
        <span className={cn("font-semibold w-5 shrink-0", labelColor)}>
          {label}
        </span>
        {!expanded && (
          <span
            className={cn(
              "truncate font-mono flex-1 min-w-0",
              previewColor,
            )}
          >
            {preview}
            {isTruncated ? "…" : ""}
          </span>
        )}
        {expanded ? (
          <ChevronUp className="h-3.5 w-3.5 text-gray-500 flex-shrink-0 ml-auto" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5 text-gray-500 flex-shrink-0 ml-auto" />
        )}
      </button>

      {expanded && (
        <div
          className={cn(
            "px-3 py-2 border-t",
            errorStyling
              ? "border-red-100 bg-red-50"
              : "border-gray-100 bg-white",
          )}
        >
          <JsonRenderer value={value} />
        </div>
      )}
    </>
  );
}

export function ToolCallBlock({
  step,
  timestamp,
}: {
  step: TraceStep;
  timestamp?: number;
}) {
  const toolName = step.action ?? "(no tool)";
  const args = step.action_input ?? {};
  const obs = step.observation ? parseObservation(step.observation) : null;
  const isError = obs !== null && looksLikeError(obs);
  const hasOutput = obs !== null;
  const cardBorder = isError ? "border-red-200" : "border-gray-200";

  return (
    <div className="min-w-0">
      {/* Tool name */}
      <div className="flex items-center gap-1.5 mb-1.5">
        <Wrench className="h-3.5 w-3.5 text-gray-600 flex-shrink-0" />
        <span className="text-xs font-mono font-bold text-gray-700">
          {toolName}
        </span>
      </div>

      {/* In / Out card — both rows behave identically (click to toggle
          between collapsed preview and full JsonRenderer tree). */}
      <div
        className={cn("rounded-lg border overflow-hidden text-xs", cardBorder)}
      >
        <CollapsibleJsonRow label="in" value={args} />
        {hasOutput && (
          <CollapsibleJsonRow
            label="out"
            value={obs}
            errorStyling={isError}
            divider
          />
        )}

        {/* Per-tool-call footer: timestamp + thumbs reactions. */}
        {timestamp != null && (
          <div className="bg-gray-50/70 px-3 py-1.5 border-t border-gray-100">
            <MessageReactions timestamp={timestamp} />
          </div>
        )}
      </div>
    </div>
  );
}
