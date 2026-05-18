// Syntax-highlighted JSON tree renderer for tool I/O. Blue keys, green
// strings, blue numbers.
//
// We deliberately do NOT offer a table view here. All tool I/O renders the
// same way — indented JSON, blue/green/orange tokens — because mixing
// table and JSON treatments for different shapes was visually inconsistent
// across the trace.
//
// We do still unwrap the agent's `{result: ...}` envelope so the displayed
// JSON matches the inner payload (and not the wire-format wrapper).

import { useMemo } from "react";

const JSON_COLORS: Record<string, string> = {
  key: "text-blue-700",
  string: "text-green-700",
  number: "text-blue-600",
  boolean: "text-orange-600",
  null: "text-gray-400",
  plain: "text-gray-600",
};

// ---------------------------------------------------------------------------
// JSON syntax-highlighting tokenizer
// ---------------------------------------------------------------------------

function tokenize(json: string): Array<{ text: string; type: string }> {
  const out: Array<{ text: string; type: string }> = [];
  const re =
    /(("(?:[^"\\]|\\.)*")\s*:)|("(?:[^"\\]|\\.)*")|(\b(?:true|false)\b)|(\bnull\b)|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(json)) !== null) {
    if (m.index > last) out.push({ text: json.slice(last, m.index), type: "plain" });
    if (m[1]) {
      out.push({ text: m[2], type: "key" });
      out.push({ text: m[1].slice(m[2].length), type: "plain" });
    } else if (m[3]) out.push({ text: m[3], type: "string" });
    else if (m[4]) out.push({ text: m[4], type: "boolean" });
    else if (m[5]) out.push({ text: m[5], type: "null" });
    else if (m[6]) out.push({ text: m[6], type: "number" });
    last = m.index + m[0].length;
  }
  if (last < json.length) out.push({ text: json.slice(last), type: "plain" });
  return out;
}

function HighlightedJson({ value }: { value: unknown }) {
  const json = useMemo(() => JSON.stringify(value, null, 2), [value]);
  const tokens = useMemo(() => tokenize(json), [json]);
  return (
    <pre className="font-mono text-xs overflow-auto max-h-96 whitespace-pre-wrap break-all leading-relaxed">
      {tokens.map((t, i) => (
        <span key={i} className={JSON_COLORS[t.type] ?? JSON_COLORS.plain}>
          {t.text}
        </span>
      ))}
    </pre>
  );
}

// ---------------------------------------------------------------------------
// Top-level renderer
// ---------------------------------------------------------------------------

export function JsonRenderer({ value }: { value: unknown }) {
  // Unwrap our agent's run_tool envelope: {result: ...}. Single-key {result}
  // wrappers add a layer of nesting that's pure overhead at display time —
  // the inner payload is what the user actually wants to see.
  let unwrapped = value;
  if (
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    "result" in (value as object) &&
    Object.keys(value as object).length === 1
  ) {
    unwrapped = (value as { result: unknown }).result;
  }
  return <HighlightedJson value={unwrapped} />;
}

// Helper: best-effort parse the agent's observation string into a JS value.
export function parseObservation(raw: string): unknown {
  const t = raw.trim();
  if (!t) return null;
  try {
    return JSON.parse(t);
  } catch {
    return raw;
  }
}

// Heuristic for "this looks like an error".
export function looksLikeError(value: unknown): boolean {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const o = value as Record<string, unknown>;
  if ("error" in o) return true;
  // Unwrap once: { result: { error } }
  if ("result" in o && typeof o.result === "object" && o.result !== null) {
    return "error" in (o.result as Record<string, unknown>);
  }
  return false;
}
