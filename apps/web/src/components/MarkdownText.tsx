// Lightweight markdown renderer for assistant replies.
//
// Gemini commonly returns text with **bold**, *italic*, `inline code`, bullet
// lists, numbered lists, fenced code blocks (```json ...```) and pipe-style
// tables. Rather than pull in `react-markdown` + `remark-gfm`, we parse the
// few constructs we actually see and render them with the existing app
// styles. JSON code fences pass through `JsonRenderer` so they pick up the
// table/JSON toggle automatically.

import { useMemo } from "react";
import { JsonRenderer, parseObservation } from "./JsonRenderer";

type Block =
  | { type: "p"; lines: string[] }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "h"; level: number; text: string }
  | { type: "code"; lang: string; body: string }
  | { type: "table"; headers: string[]; rows: string[][] };

const TABLE_SEPARATOR_RE = /^\s*\|?[\s:|-]+\|[\s:|-]+\|?\s*$/;

function isTableHeader(line: string, next: string | undefined): boolean {
  return Boolean(
    next && line.includes("|") && TABLE_SEPARATOR_RE.test(next),
  );
}

function parsePipeRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

function parseBlocks(md: string): Block[] {
  const blocks: Block[] = [];
  const lines = md.split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    const fence = line.match(/^```(\w*)\s*$/);
    if (fence) {
      const lang = fence[1] || "";
      const body: string[] = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) {
        body.push(lines[i]);
        i++;
      }
      i++; // skip closing fence
      blocks.push({ type: "code", lang, body: body.join("\n") });
      continue;
    }

    // Markdown table
    if (isTableHeader(line, lines[i + 1])) {
      const headers = parsePipeRow(line);
      i += 2; // skip header + separator
      const rows: string[][] = [];
      while (
        i < lines.length &&
        lines[i].includes("|") &&
        lines[i].trim() !== ""
      ) {
        rows.push(parsePipeRow(lines[i]));
        i++;
      }
      blocks.push({ type: "table", headers, rows });
      continue;
    }

    // Heading
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      blocks.push({ type: "h", level: h[1].length, text: h[2] });
      i++;
      continue;
    }

    // Bullet list
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i++;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    // Numbered list
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i++;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    // Blank line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Paragraph: gather until blank line / next-block marker
    const paraLines: string[] = [line];
    i++;
    while (i < lines.length) {
      const l = lines[i];
      if (l.trim() === "") break;
      if (/^```/.test(l)) break;
      if (/^#{1,6}\s/.test(l)) break;
      if (/^\s*[-*]\s+/.test(l)) break;
      if (/^\s*\d+\.\s+/.test(l)) break;
      if (isTableHeader(l, lines[i + 1])) break;
      paraLines.push(l);
      i++;
    }
    blocks.push({ type: "p", lines: paraLines });
  }
  return blocks;
}

// Inline tokens: **bold**, *italic*, `code`. Plain text otherwise.
type InlineToken =
  | { type: "bold"; text: string }
  | { type: "italic"; text: string }
  | { type: "code"; text: string }
  | { type: "plain"; text: string };

const INLINE_RE =
  /(\*\*([^*\n]+?)\*\*|`([^`\n]+?)`|\*([^*\s][^*\n]*?[^*\s]|[^*\s])\*)/g;

function tokenizeInline(text: string): InlineToken[] {
  const out: InlineToken[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  INLINE_RE.lastIndex = 0;
  while ((m = INLINE_RE.exec(text)) !== null) {
    if (m.index > last) {
      out.push({ type: "plain", text: text.slice(last, m.index) });
    }
    if (m[2] !== undefined) out.push({ type: "bold", text: m[2] });
    else if (m[3] !== undefined) out.push({ type: "code", text: m[3] });
    else if (m[4] !== undefined) out.push({ type: "italic", text: m[4] });
    last = INLINE_RE.lastIndex;
  }
  if (last < text.length) out.push({ type: "plain", text: text.slice(last) });
  return out;
}

function Inline({ text }: { text: string }) {
  const tokens = useMemo(() => tokenizeInline(text), [text]);
  return (
    <>
      {tokens.map((t, i) => {
        if (t.type === "bold") {
          return (
            <strong key={i} className="font-semibold text-gray-900">
              {t.text}
            </strong>
          );
        }
        if (t.type === "italic") return <em key={i}>{t.text}</em>;
        if (t.type === "code") {
          return (
            <code
              key={i}
              className="font-mono text-[0.85em] px-1 py-0.5 rounded bg-gray-200/70 text-gray-800"
            >
              {t.text}
            </code>
          );
        }
        return <span key={i}>{t.text}</span>;
      })}
    </>
  );
}

const HEADING_SIZE: Record<number, string> = {
  1: "text-base font-semibold",
  2: "text-base font-semibold",
  3: "text-sm font-semibold",
  4: "text-sm font-semibold",
  5: "text-sm font-semibold",
  6: "text-sm font-semibold",
};

export function MarkdownText({ text }: { text: string }) {
  const blocks = useMemo(() => parseBlocks(text), [text]);
  return (
    <div className="text-sm text-gray-800 leading-relaxed space-y-2">
      {blocks.map((b, i) => {
        switch (b.type) {
          case "p":
            return (
              <p key={i}>
                {b.lines.map((line, j) => (
                  <span key={j}>
                    <Inline text={line} />
                    {j < b.lines.length - 1 && <br />}
                  </span>
                ))}
              </p>
            );
          case "h": {
            const level = Math.min(6, Math.max(1, b.level));
            const cls = `${HEADING_SIZE[level]} text-gray-900`;
            return (
              <p key={i} className={cls}>
                <Inline text={b.text} />
              </p>
            );
          }
          case "ul":
            return (
              <ul key={i} className="list-disc pl-5 space-y-0.5">
                {b.items.map((it, j) => (
                  <li key={j}>
                    <Inline text={it} />
                  </li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={i} className="list-decimal pl-5 space-y-0.5">
                {b.items.map((it, j) => (
                  <li key={j}>
                    <Inline text={it} />
                  </li>
                ))}
              </ol>
            );
          case "code": {
            // ```json``` → render via JsonRenderer (table/JSON toggle).
            if (b.lang.toLowerCase() === "json") {
              const parsed = parseObservation(b.body);
              if (parsed && typeof parsed === "object") {
                return (
                  <div
                    key={i}
                    className="rounded-md border border-gray-200 bg-white overflow-hidden"
                  >
                    <JsonRenderer value={parsed} />
                  </div>
                );
              }
            }
            return (
              <pre
                key={i}
                className="rounded-md bg-gray-200/70 p-2 text-xs font-mono overflow-auto"
              >
                <code>{b.body}</code>
              </pre>
            );
          }
          case "table":
            return (
              <div
                key={i}
                className="overflow-auto rounded-md border border-gray-200"
              >
                <table className="w-full text-xs border-collapse">
                  <thead className="bg-gray-100">
                    <tr>
                      {b.headers.map((cell, j) => (
                        <th
                          key={j}
                          className="text-left px-2.5 py-1.5 border-b border-gray-200 font-semibold text-gray-700"
                        >
                          <Inline text={cell} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((row, ri) => (
                      <tr
                        key={ri}
                        className="border-b border-gray-100 last:border-0 even:bg-gray-50/50"
                      >
                        {row.map((cell, ci) => (
                          <td
                            key={ci}
                            className="px-2.5 py-1 align-top break-words"
                          >
                            <Inline text={cell} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
        }
      })}
    </div>
  );
}
