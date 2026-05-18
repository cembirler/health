// Rich result cards drawn AUTOMATICALLY from each tool call's output.
// No `render_*` tools — the dispatcher inspects step.action + the parsed
// observation and picks the matching card. Cards consume the raw tool
// output directly (no synthesized "render payload" middleman).
//
// Wire-up: Message.tsx renders this below each ToolCallBlock. Empty
// empty results return null — the agent's prose + <SUGGESTIONS> tail
// explains what couldn't be found.

import { useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Hospital,
  Shield,
  Trophy,
} from "lucide-react";
import { SourceChip, SourceChipMulti } from "./SourceChip";
import type { TraceStep } from "./ToolCallBlock";
import { cn } from "../lib/cn";

// ============================================================================
// Final-reply parser + suggestions card
// ============================================================================
//
// The agent's last reply has up to three parts (system prompt rule 7):
//   1. prose summary
//   2. optional <STRUCTURED_CARD> block — list of tool names whose latest
//      call's output should mount a rich card under the bubble.
//   3. optional <SUGGESTIONS> block — up to 3 follow-up prompts as
//      click-to-send pills.
// This util pulls both tail blocks out and returns the clean prose.

// Tolerant matchers — close on the explicit closing tag, the next
// block's opener, or end-of-string. Lets us recover when the model
// forgets the closing `</SUGGESTIONS>` (seen with Gemini Flash) instead
// of leaking the literal tag into the rendered prose.
const _STRUCTURED_CARD_RE = /<STRUCTURED_CARD>([\s\S]*?)(?:<\/STRUCTURED_CARD>|(?=<SUGGESTIONS>)|$)/;
const _SUGGESTIONS_RE = /<SUGGESTIONS>([\s\S]*?)(?:<\/SUGGESTIONS>|$)/;

function _splitLines(block: string): string[] {
  return block
    .split("\n")
    .map((s) => s.trim())
    // Tolerate stray bullets and quotes around individual lines.
    .map((s) => s.replace(/^[-*•]\s*/, "").trim())
    .map((s) => s.replace(/^["'](.*)["']$/, "$1").trim())
    .filter((s) => s.length > 0);
}

export function parseReplyTail(reply: string): {
  cleanReply: string;
  cardToolNames: string[];
  suggestions: string[];
} {
  if (!reply) {
    return { cleanReply: reply, cardToolNames: [], suggestions: [] };
  }

  const cardMatch = _STRUCTURED_CARD_RE.exec(reply);
  const suggestionsMatch = _SUGGESTIONS_RE.exec(reply);

  const cardToolNames = cardMatch ? _splitLines(cardMatch[1]) : [];
  // Dedupe in order — latest call of each tool wins downstream.
  const seenTools = new Set<string>();
  const dedupedTools = cardToolNames.filter((n) =>
    seenTools.has(n) ? false : (seenTools.add(n), true),
  );
  // Hard cap at 3 — if the model emits more, we silently drop the tail.
  const suggestions = suggestionsMatch
    ? _splitLines(suggestionsMatch[1]).slice(0, 3)
    : [];

  // Strip both blocks from the prose, wherever they ended up.
  const cleanReply = reply
    .replace(_STRUCTURED_CARD_RE, "")
    .replace(_SUGGESTIONS_RE, "")
    .trimEnd();

  return { cleanReply, cardToolNames: dedupedTools, suggestions };
}

export function SuggestedActionsCard({
  suggestions,
  onSendNext,
}: {
  suggestions: string[];
  onSendNext?: (text: string) => void;
}) {
  if (suggestions.length === 0 || !onSendNext) return null;
  return (
    <div className="mb-2">
      <div className="text-xs uppercase tracking-wide text-gray-400 font-medium">
        Suggestions
      </div>
      <hr className="border-t border-gray-200 my-2" />
      <ul className="space-y-1.5">
        {suggestions.map((s, i) => (
          <li key={i}>
            <button
              type="button"
              onClick={() => onSendNext(s)}
              className="rounded-full border border-orange-200 bg-orange-50 px-3.5 py-1.5 text-sm text-left text-black hover:bg-orange-100 hover:border-orange-300 transition"
            >
              {s}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ============================================================================
// Dispatcher
// ============================================================================

export function ToolResultCard({
  step,
  onSendNext,
}: {
  step: TraceStep;
  onSendNext?: (text: string) => void;
}) {
  const action = step.action;
  if (!action || !step.observation) return null;

  // The agent loop wraps every observation as `{result: <payload>}`.
  // Unwrap once here so the cards consume the raw tool output directly.
  let result: unknown;
  try {
    const obs = JSON.parse(step.observation);
    result = obs && typeof obs === "object" && "result" in obs
      ? (obs as { result: unknown }).result
      : obs;
  } catch {
    return null;
  }

  // ListResponse / SingleResponse envelopes from the CRUD endpoints —
  // unwrap `{data: ...}` for cards that consume the inner data directly.
  function envelopeData(r: unknown): unknown {
    if (r && typeof r === "object" && "data" in r) {
      return (r as { data: unknown }).data;
    }
    return r;
  }

  // Empty-result handling: return null and let the agent's prose +
  // <SUGGESTIONS> tail explain what couldn't be found. We used to mount
  // a NoResultsCard with hardcoded retry pills here, but it stacked
  // poorly with the agent's own context-aware suggestions. The agent's
  // system prompt now owns the "no matches" explanation.
  switch (action) {
    case "find_prices": {
      const r = result as FindPricesResult;
      if (!r?.data?.length) return null;
      return <PriceListCard result={r} />;
    }

    case "price_distribution": {
      const r = result as DistributionResult;
      const total =
        (r?.stats?.discounted_cash_price?.count ?? 0) +
        (r?.stats?.gross_charge?.count ?? 0) +
        (r?.stats?.negotiated_dollar?.count ?? 0);
      if (total === 0) return null;
      return <DistributionCard result={r} />;
    }

    case "compare_hospitals": {
      const r = result as ComparisonResult;
      if (!r?.data?.length) return null;
      return <ComparisonGrid result={r} />;
    }

    case "corpus_stats": {
      const data = envelopeData(result) as CorpusStats | undefined;
      if (!data) return null;
      return <CorpusStatsCard data={data} />;
    }

    case "find_procedure":
    case "list_codes_for_charge": {
      const codes = (envelopeData(result) as CodeRow[] | undefined) ?? [];
      if (codes.length === 0) return null;
      return <CodeListCard codes={codes} onSendNext={onSendNext} />;
    }

    case "get_code": {
      const code = envelopeData(result) as CodeRow | undefined;
      if (!code) return null;
      return <CodeListCard codes={[code]} onSendNext={onSendNext} />;
    }

    case "find_hospital": {
      const hospitals =
        (envelopeData(result) as HospitalRow[] | undefined) ?? [];
      if (hospitals.length === 0) return null;
      return <HospitalListCard hospitals={hospitals} />;
    }

    case "find_hospitals_nearby": {
      const r = result as NearbyHospitalsResult | undefined;
      const hospitals = r?.data ?? [];
      if (hospitals.length === 0) return null;
      return (
        <HospitalListCard
          hospitals={hospitals}
          radiusMiles={r?.radius_miles}
        />
      );
    }

    case "get_hospital": {
      const h = envelopeData(result) as HospitalRow | undefined;
      if (!h) return null;
      return <HospitalListCard hospitals={[h]} />;
    }

    case "get_charge": {
      const charge = envelopeData(result) as ChargeRow | undefined;
      if (!charge) return null;
      return <ChargeInfoCard charge={charge} />;
    }

    case "list_charges_for_code": {
      const charges =
        (envelopeData(result) as ChargeRow[] | undefined) ?? [];
      if (charges.length === 0) return null;
      return <ChargeListCard charges={charges} />;
    }

    case "list_payer_rates_for_charge": {
      const rates =
        (envelopeData(result) as PayerRateRow[] | undefined) ?? [];
      if (rates.length === 0) return null;
      return <PayerRateListCard rates={rates} />;
    }

    default:
      return null;
  }
}

// ============================================================================
// Shared types — mirror server-side tool output shapes
// ============================================================================

interface CodeShort {
  code: string;
  description: string | null;
}

interface HospitalShort {
  id: number;
  name: string | null;
  city: string | null;
  state: string | null;
  zip: string | null;
}

interface PayerRateShort {
  payer_name_raw: string;
  plan_name: string | null;
  negotiated_dollar: number | null;
  negotiated_percentage: number | null;
  methodology: string | null;
}

interface PriceBlock {
  gross_charge: number | null;
  discounted_cash_price: number | null;
  min_negotiated_charge: number | null;
  max_negotiated_charge: number | null;
}

interface PricedChargeRow {
  charge_id: number;
  mrf_id: number;
  hospital: HospitalShort;
  prices: PriceBlock;
  setting: string | null;
  description: string | null;
  top_payer_rates: PayerRateShort[];
}

interface FindPricesResult {
  matched_codes: CodeShort[];
  matched_payers: string[] | null;
  sort_by: string;
  data: PricedChargeRow[];
}

interface StatsBlock {
  count: number;
  min?: number;
  p10?: number;
  p25?: number;
  median?: number;
  p75?: number;
  p90?: number;
  max?: number;
  avg?: number;
}

interface DistributionResult {
  matched_codes: CodeShort[];
  matched_payers: string[] | null;
  stats: {
    discounted_cash_price: StatsBlock;
    gross_charge: StatsBlock;
    negotiated_dollar: StatsBlock;
  };
  source_mrf_ids: number[];
}

interface ComparisonRow {
  hospital?: HospitalShort;
  hospital_id?: number;
  missing?: boolean;
  no_data?: boolean;
  charge_id?: number;
  mrf_id?: number;
  prices?: PriceBlock;
  top_payer_rates?: PayerRateShort[];
}

interface ComparisonResult {
  code: CodeShort;
  data: ComparisonRow[];
}

interface CorpusStats {
  total_hospitals: number;
  total_codes: number;
  total_charges_est: number;
  total_payer_rates_est: number;
  total_mrfs: number;
  source_mrf_ids: number[];
}

interface CodeRow {
  id: number;
  code: string;
  official_description: string | null;
  most_common_description: string | null;
  gemma_description: string | null;
  category: string | null;
  typical_setting: string | null;
}

interface HospitalRow {
  id: number;
  ein: string | null;
  hospital_name: string | null;
  location_name: string;
  hospital_address: string | null;
  city: string | null;
  state: string | null;
  zip: string | null;
  lat: number | null;
  lng: number | null;
  license_number: string | null;
  license_state: string | null;
  // Only present on rows from find_hospitals_nearby (or future geo-sorted
  // endpoints). Rendered as a pill on the list item when set.
  distance_miles?: number;
}

interface NearbyHospitalsResult {
  data: HospitalRow[];
  center: { lat: number; lng: number };
  radius_miles: number;
}

interface ChargeRow {
  id: number;
  hospital_id: number;
  mrf_id: number;
  setting: string | null;
  description: string | null;
  modifiers: string | null;
  drug_unit_of_measurement: string | null;
  drug_type_of_measurement: string | null;
  additional_generic_notes: string | null;
  gross_charge: number | null;
  discounted_cash_price: number | null;
  min_negotiated_charge: number | null;
  max_negotiated_charge: number | null;
}

interface PayerRateRow {
  id: number;
  hospital_code_charge_id: number;
  payer_name_raw: string;
  plan_name: string | null;
  negotiated_dollar: number | null;
  negotiated_percentage: number | null;
  negotiated_algorithm: string | null;
  methodology: string | null;
  estimated_allowed_amount: number | null;
  median_allowed_amount: number | null;
  p10_allowed_amount: number | null;
  p90_allowed_amount: number | null;
  allowed_amounts_count: string | null;
  additional_payer_notes: string | null;
}

// ============================================================================
// Shared helpers
// ============================================================================

function fmtUsd(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v >= 10000) return `$${Math.round(v).toLocaleString("en-US")}`;
  return `$${v.toFixed(0)}`;
}

// Title-case any human-readable column label. Used for the header above
// the price column in PriceListCard and any other card that surfaces a
// raw column / field name. Skips short connector words (of/and/the/etc.)
// so "min of negotiated charge" doesn't read "Min Of Negotiated Charge".
const _STOPWORDS = new Set([
  "a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or",
  "the", "to", "vs", "with",
]);

function titleCaseColumn(s: string): string {
  return s
    .split(/\s+/)
    .map((word, i) => {
      const lower = word.toLowerCase();
      if (i > 0 && _STOPWORDS.has(lower)) return lower;
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(" ");
}

function CardFrame({
  title,
  subtitle,
  titleRight,
  children,
}: {
  title?: string;
  subtitle?: string;
  // Optional right-aligned label that sits on the same baseline as the
  // title — useful for column-style cards (e.g. price listings) where the
  // header doubles as a column header above the right-hand value column.
  titleRight?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden mb-2">
      {title && (
        <div className="px-4 pt-3 pb-2 border-b border-gray-100">
          <div className="flex items-baseline justify-between gap-3">
            <div className="text-sm font-semibold text-gray-800">{title}</div>
            {titleRight && (
              <div className="text-sm font-semibold text-gray-800 flex-shrink-0">
                {titleRight}
              </div>
            )}
          </div>
          {subtitle && (
            <div className="text-xs text-gray-500 mt-0.5">{subtitle}</div>
          )}
        </div>
      )}
      {children}
    </div>
  );
}

// ============================================================================
// PriceListCard — find_prices
// ============================================================================

// One charge per (hospital, price) — collapses the common pattern where
// a hospital prices several variant codes (e.g. with/without modifier)
// at the same dollar amount. `count` is how many original rows merged
// into this entry; payer rates pulled from the representative row.
interface GroupedPriceRow {
  hospital: HospitalShort;
  price: number;
  mrf_id: number;
  setting: string | null;
  representative: PricedChargeRow;
  count: number;
}

function groupPriceRows(
  rows: PricedChargeRow[],
  sortBy: string,
): GroupedPriceRow[] {
  const byKey = new Map<string, GroupedPriceRow>();
  for (const row of rows) {
    const price = priceForSort(row, sortBy);
    const hospId = row.hospital?.id ?? row.hospital?.name ?? "?";
    const key = `${hospId}|${price}`;
    const existing = byKey.get(key);
    if (existing) {
      existing.count += 1;
    } else {
      byKey.set(key, {
        hospital: row.hospital,
        price,
        mrf_id: row.mrf_id,
        setting: row.setting,
        representative: row,
        count: 1,
      });
    }
  }
  return Array.from(byKey.values());
}

function PriceListCard({ result }: { result: FindPricesResult }) {
  const [showAll, setShowAll] = useState(false);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);
  const COLLAPSED = 5;
  const grouped = groupPriceRows(result.data, result.sort_by);
  const maxPrice = Math.max(...grouped.map((r) => r.price));
  const visible = showAll ? grouped : grouped.slice(0, COLLAPSED);
  const hidden = grouped.length - visible.length;

  // When the same hospital shows up in more than one (hospital, price) group,
  // surface the per-row description as a differentiator so the viewer can see
  // *which variant* of the charge each price belongs to (e.g. base vs.
  // modifier-50, different drug strengths, distinct line-item descriptions).
  // Hidden fields like `modifiers` / `drug_unit_of_measurement` aren't in the
  // wire shape today — if descriptions also match, the hospital is publishing
  // multiple charge rows that only differ on those hidden columns.
  const hospitalCounts = new Map<string | number, number>();
  for (const r of grouped) {
    const k = r.hospital?.id ?? r.hospital?.name ?? "?";
    hospitalCounts.set(k, (hospitalCounts.get(k) ?? 0) + 1);
  }
  const codeLabel =
    result.matched_codes.length === 1
      ? `${result.matched_codes[0].code} — ${result.matched_codes[0].description ?? ""}`
      : `${result.matched_codes.length} matching codes`;
  const collapsedSummary =
    grouped.length < result.data.length
      ? ` (${result.data.length} matched charges)`
      : "";

  return (
    <CardFrame
      title={`${grouped.length} priced result${grouped.length === 1 ? "" : "s"}${collapsedSummary}`}
      subtitle={codeLabel}
      titleRight={sortLabel(result.sort_by)}
    >
      <ul className="divide-y divide-gray-100">
        {visible.map((row, i) => {
          const widthPct = maxPrice > 0 ? Math.max(4, (row.price / maxPrice) * 100) : 0;
          const isExpanded = expandedRow === i;
          const payerRates = row.representative.top_payer_rates;
          const hasPayers = (payerRates?.length ?? 0) > 0;
          const hospKey = row.hospital?.id ?? row.hospital?.name ?? "?";
          const showDifferentiator = (hospitalCounts.get(hospKey) ?? 0) > 1;
          const variantDesc = row.representative.description?.trim();

          return (
            <li key={`${row.hospital.id}-${row.price}`} className="px-4 py-3">
              <div className="flex items-baseline gap-3">
                <span className="text-xs font-semibold text-gray-400 w-6 flex-shrink-0">
                  #{i + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-gray-800 truncate">
                    {row.hospital.name ?? "Unknown"}
                  </div>
                  <div className="text-xs text-gray-500 mt-0.5 flex items-center gap-1.5 flex-wrap">
                    {row.setting && (
                      <span className="inline-flex items-center rounded bg-gray-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-gray-600">
                        {row.setting}
                      </span>
                    )}
                    {row.hospital.city && row.hospital.state && (
                      <span>
                        {row.hospital.city}, {row.hospital.state}
                      </span>
                    )}
                    {row.count > 1 && (
                      <span className="text-[10px] text-gray-500">
                        · {row.count} matching codes at this price
                      </span>
                    )}
                  </div>
                  {showDifferentiator && variantDesc && (
                    <div
                      className="text-[11px] text-gray-600 mt-1 line-clamp-2"
                      title={variantDesc}
                    >
                      {variantDesc}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <div className="text-right">
                    <div className="text-sm font-semibold text-gray-900">
                      {fmtUsd(row.price)}
                    </div>
                    <div className="w-20 h-1.5 bg-gray-100 rounded mt-1">
                      <div
                        className="h-full bg-blue-400 rounded"
                        style={{ width: `${widthPct}%` }}
                      />
                    </div>
                  </div>
                  <SourceChip mrf_id={row.mrf_id} />
                </div>
              </div>

              {hasPayers && (
                <div className="mt-2 ml-9">
                  <button
                    type="button"
                    onClick={() => setExpandedRow(isExpanded ? null : i)}
                    className="text-xs text-gray-600 hover:text-gray-800 inline-flex items-center gap-1"
                  >
                    {isExpanded ? (
                      <ChevronUp className="h-3 w-3" />
                    ) : (
                      <ChevronDown className="h-3 w-3" />
                    )}
                    {payerRates.length} payer rates
                  </button>
                  {isExpanded && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {payerRates.map((p, j) => (
                        <span
                          key={j}
                          className="inline-flex items-center gap-1 rounded bg-payer-50 border border-payer-100 px-2 py-0.5 text-xs text-gray-800"
                        >
                          <span className="font-medium">{p.payer_name_raw}</span>
                          <span>{fmtUsd(p.negotiated_dollar)}</span>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>

      {hidden > 0 && !showAll && (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          className="w-full px-4 py-2 text-xs text-blue-700 hover:bg-blue-50 border-t border-gray-100 transition"
        >
          Show {hidden} more
        </button>
      )}
    </CardFrame>
  );
}

function priceForSort(row: PricedChargeRow, sortBy: string): number {
  const map: Record<string, number | null> = {
    discounted_cash_price: row.prices.discounted_cash_price,
    gross_charge: row.prices.gross_charge,
    min_negotiated_charge: row.prices.min_negotiated_charge,
    max_negotiated_charge: row.prices.max_negotiated_charge,
  };
  return map[sortBy] ?? row.prices.discounted_cash_price ?? 0;
}

// Human-readable label for the canonical MRF price fields the agent may
// sort by. Surfaced as the column header above the price column in
// PriceListCard so a viewer doesn't have to know the snake_case API name.
const _SORT_LABELS: Record<string, string> = {
  discounted_cash_price: "Discounted cash price",
  gross_charge: "Gross charge",
  min_negotiated_charge: "Min negotiated charge",
  max_negotiated_charge: "Max negotiated charge",
};

function sortLabel(sortBy: string): string {
  return titleCaseColumn(_SORT_LABELS[sortBy] ?? sortBy.replace(/_/g, " "));
}

// ============================================================================
// DistributionCard — price_distribution
// ============================================================================

function DistributionCard({ result }: { result: DistributionResult }) {
  const seriesList = [
    { key: "discounted_cash_price" as const, label: "Cash price" },
    { key: "gross_charge" as const, label: "Gross" },
    { key: "negotiated_dollar" as const, label: "Negotiated" },
  ].filter((s) => result.stats[s.key]?.count > 0);

  const [activeIdx, setActiveIdx] = useState(0);
  if (seriesList.length === 0) return null;
  const active = seriesList[activeIdx];
  const s = result.stats[active.key];
  const codeLabel =
    result.matched_codes.length === 1
      ? `${result.matched_codes[0].code} — ${result.matched_codes[0].description ?? ""}`
      : `${result.matched_codes.length} matching codes`;

  if (
    s.min == null ||
    s.max == null ||
    s.p10 == null ||
    s.median == null ||
    s.p90 == null
  ) {
    return null;
  }

  const range = s.max - s.min;
  const pct = (v: number) =>
    range > 0 ? Math.min(100, Math.max(0, ((v - s.min!) / range) * 100)) : 50;

  return (
    <CardFrame
      title={`Distribution — ${active.label}`}
      subtitle={`${codeLabel} · ${s.count.toLocaleString()} priced items`}
    >
      <div className="px-4 py-4">
        <div className="relative h-6 mb-1">
          <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-2 bg-gradient-to-r from-green-200 via-yellow-200 to-red-200 rounded" />
          {(["p10", "median", "p90"] as const).map((q) => (
            <div
              key={q}
              className="absolute top-1/2 -translate-y-1/2 h-3 w-px bg-gray-500"
              style={{ left: `${pct(s[q]!)}%` }}
            />
          ))}
        </div>
        <div className="flex justify-between text-[10px] text-gray-500 mb-3">
          <span>{fmtUsd(s.min)}</span>
          <span>median {fmtUsd(s.median)}</span>
          <span>{fmtUsd(s.max)}</span>
        </div>

        <div className="grid grid-cols-4 gap-2 text-center mt-2 mb-3">
          {(["min", "median", "avg", "max"] as const).map((k) => (
            <div key={k} className="bg-gray-50 rounded py-1.5">
              <div className="text-[10px] uppercase tracking-wide text-gray-500">
                {k}
              </div>
              <div className="text-xs font-semibold text-gray-800">
                {fmtUsd(s[k] ?? null)}
              </div>
            </div>
          ))}
        </div>

        {seriesList.length > 1 && (
          <div className="flex gap-1.5 mb-2">
            {seriesList.map((sr, i) => (
              <button
                key={sr.key}
                type="button"
                onClick={() => setActiveIdx(i)}
                className={cn(
                  "text-xs px-2.5 py-1 rounded-full border transition",
                  i === activeIdx
                    ? "bg-blue-100 border-blue-300 text-blue-900"
                    : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50",
                )}
              >
                {sr.label}
              </button>
            ))}
          </div>
        )}

        <div className="mt-2 pt-2 border-t border-gray-100">
          <SourceChipMulti mrf_ids={result.source_mrf_ids} />
        </div>
      </div>
    </CardFrame>
  );
}

// ============================================================================
// ComparisonGrid — compare_hospitals
// ============================================================================

function ComparisonGrid({ result }: { result: ComparisonResult }) {
  const cheapestId = (() => {
    let bestId: number | null = null;
    let bestPrice = Infinity;
    for (const c of result.data) {
      const p = c.prices?.discounted_cash_price;
      if (p != null && p < bestPrice) {
        bestPrice = p;
        bestId = c.charge_id ?? null;
      }
    }
    return bestId;
  })();

  return (
    <CardFrame
      title="Side-by-side comparison"
      subtitle={`${result.code.code} — ${result.code.description ?? ""}`}
    >
      <div className="overflow-x-auto">
        <div
          className="grid gap-3 p-4"
          style={{
            gridTemplateColumns: `repeat(${result.data.length}, minmax(200px, 1fr))`,
          }}
        >
          {result.data.map((col, i) => {
            if (col.missing) {
              return (
                <div
                  key={i}
                  className="rounded-lg border border-gray-200 bg-white p-3 flex flex-col gap-2"
                >
                  <div className="text-sm font-semibold text-gray-800">
                    Hospital {col.hospital_id}
                  </div>
                  <div className="text-xs text-gray-500 italic py-2">
                    Hospital not in our data.
                  </div>
                </div>
              );
            }
            if (col.no_data) {
              return (
                <div
                  key={i}
                  className="rounded-lg border border-gray-200 bg-white p-3 flex flex-col gap-2"
                >
                  <div className="text-sm font-semibold text-gray-800">
                    {col.hospital?.name ?? "Unknown"}
                  </div>
                  <div className="text-xs text-gray-500 italic py-2">
                    No charge published for this code.
                  </div>
                </div>
              );
            }
            const isHighlight =
              cheapestId != null && col.charge_id === cheapestId;
            return (
              <div
                key={i}
                className={cn(
                  "rounded-lg border p-3 flex flex-col gap-2",
                  isHighlight
                    ? "border-green-300 bg-green-50"
                    : "border-gray-200 bg-white",
                )}
              >
                <div>
                  <div className="text-sm font-semibold text-gray-800 flex items-center gap-1.5">
                    {col.hospital?.name ?? "Unknown"}
                    {isHighlight && (
                      <Trophy className="h-3.5 w-3.5 text-green-700" />
                    )}
                  </div>
                  {col.hospital?.city && col.hospital?.state && (
                    <div className="text-xs text-gray-500 mt-0.5">
                      {col.hospital.city}, {col.hospital.state}
                    </div>
                  )}
                </div>

                <div className="space-y-1 mt-1">
                  {[
                    ["Cash", col.prices?.discounted_cash_price],
                    ["Gross", col.prices?.gross_charge],
                    ["Min", col.prices?.min_negotiated_charge],
                    ["Max", col.prices?.max_negotiated_charge],
                  ].map(([label, value]) => (
                    <div
                      key={String(label)}
                      className="flex justify-between items-baseline text-xs"
                    >
                      <span className="text-gray-500">{label as string}</span>
                      <span className="font-semibold text-gray-800">
                        {fmtUsd(value as number | null | undefined)}
                      </span>
                    </div>
                  ))}
                </div>

                {col.top_payer_rates && col.top_payer_rates.length > 0 && (
                  <div className="mt-2 pt-2 border-t border-gray-100">
                    <div className="text-[10px] uppercase tracking-wide text-gray-400 mb-1">
                      Top payers
                    </div>
                    <div className="space-y-0.5">
                      {col.top_payer_rates.map((p, j) => (
                        <div
                          key={j}
                          className="flex justify-between items-baseline text-xs"
                        >
                          <span className="text-gray-600 truncate">
                            {p.payer_name_raw}
                          </span>
                          <span className="text-gray-800 ml-2 flex-shrink-0">
                            {fmtUsd(p.negotiated_dollar)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {col.mrf_id != null && (
                  <div className="mt-auto pt-2 border-t border-gray-100 flex justify-end">
                    <SourceChip mrf_id={col.mrf_id} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </CardFrame>
  );
}

// ============================================================================
// CorpusStatsCard — corpus_stats
// ============================================================================

function CorpusStatsCard({ data }: { data: CorpusStats }) {
  const tiles = [
    { value: data.total_hospitals.toLocaleString(), label: "hospitals" },
    { value: shortNum(data.total_codes), label: "billing codes" },
    { value: shortNum(data.total_charges_est), label: "priced items" },
    { value: data.total_mrfs.toLocaleString(), label: "source files" },
  ];

  return (
    <CardFrame title="What's in our database">
      <div className="px-4 py-4 space-y-4">
        <div className="grid grid-cols-4 gap-2">
          {tiles.map((t, i) => (
            <div
              key={i}
              className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center"
            >
              <div className="text-xl font-bold text-gray-900">{t.value}</div>
              <div className="text-[11px] uppercase tracking-wide text-gray-500 mt-1">
                {t.label}
              </div>
            </div>
          ))}
        </div>
        <div className="text-xs text-gray-500 pt-2 border-t border-gray-100">
          Sourced from CMS-mandated hospital price files.
        </div>
      </div>
    </CardFrame>
  );
}

function shortNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`;
  return n.toLocaleString();
}

// ============================================================================
// CodeListCard — find_procedure / list_codes_for_charge / get_code
// 1 row → info layout, N rows → pickable list
// ============================================================================

function CodeListCard({
  codes,
  onSendNext,
}: {
  codes: CodeRow[];
  onSendNext?: (text: string) => void;
}) {
  if (codes.length === 1) {
    const c = codes[0];
    return (
      <CardFrame title={c.code} subtitle="Billing code">
        <div className="px-4 py-3 space-y-2 text-sm">
          {c.gemma_description && (
            <DescBlock label="Plain-language" text={c.gemma_description} />
          )}
          {c.official_description && (
            <DescBlock label="Official" text={c.official_description} />
          )}
          {c.most_common_description &&
            c.most_common_description !== c.official_description && (
              <DescBlock label="Most common" text={c.most_common_description} />
            )}
          {(c.category || c.typical_setting) && (
            <div className="flex flex-wrap gap-1.5 pt-1">
              {c.category && <Pill>{c.category}</Pill>}
              {c.typical_setting && <Pill>{c.typical_setting}</Pill>}
            </div>
          )}
        </div>
      </CardFrame>
    );
  }

  return (
    <CardFrame
      title={`${codes.length} matching codes`}
      subtitle="Click a code for prices"
    >
      <ul className="divide-y divide-gray-100">
        {codes.map((c) => {
          const desc =
            c.most_common_description ??
            c.official_description ??
            c.gemma_description ??
            "";
          return (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => onSendNext?.(`How much does ${c.code} cost?`)}
                className="w-full px-4 py-2.5 flex items-center gap-3 hover:bg-blue-50 transition text-left"
              >
                <span className="font-mono text-xs font-semibold text-blue-900 flex-shrink-0 w-32">
                  {c.code}
                </span>
                <span className="text-sm text-gray-700 flex-1 truncate">
                  {desc}
                </span>
                <span className="text-blue-600 text-xs flex-shrink-0">↗</span>
              </button>
            </li>
          );
        })}
      </ul>
    </CardFrame>
  );
}

function DescBlock({ label, text }: { label: string; text: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-gray-400 mb-0.5">
        {label}
      </div>
      <div className="text-gray-800">{text}</div>
    </div>
  );
}

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex rounded bg-gray-100 px-2 py-0.5 text-[11px] text-gray-700">
      {children}
    </span>
  );
}

// ============================================================================
// HospitalListCard — find_hospital / get_hospital
// ============================================================================

function HospitalListCard({
  hospitals,
  radiusMiles,
}: {
  hospitals: HospitalRow[];
  radiusMiles?: number;
}) {
  if (hospitals.length === 1) {
    const h = hospitals[0];
    const addrLine = [h.city, h.state, h.zip].filter(Boolean).join(", ");
    return (
      <CardFrame
        title={h.hospital_name ?? h.location_name}
        subtitle={
          h.location_name && h.location_name !== h.hospital_name
            ? h.location_name
            : undefined
        }
      >
        <div className="px-4 py-3 space-y-2 text-sm">
          {h.hospital_address && (
            <div className="flex items-start gap-2">
              <Hospital className="h-3.5 w-3.5 text-gray-400 mt-0.5 flex-shrink-0" />
              <div className="text-gray-800">
                <div>{h.hospital_address}</div>
                {addrLine && (
                  <div className="text-xs text-gray-500">{addrLine}</div>
                )}
              </div>
            </div>
          )}
          {!h.hospital_address && addrLine && (
            <div className="text-gray-800">{addrLine}</div>
          )}
          <div className="flex flex-wrap gap-1.5">
            {h.ein && <Pill>EIN {h.ein}</Pill>}
            {h.license_number && (
              <Pill>
                License {h.license_number}
                {h.license_state ? ` (${h.license_state})` : ""}
              </Pill>
            )}
          </div>
        </div>
      </CardFrame>
    );
  }

  const title =
    radiusMiles !== undefined
      ? `${hospitals.length} hospitals within ${radiusMiles} mi`
      : `${hospitals.length} matching hospitals`;
  return (
    <CardFrame title={title}>
      <ul className="divide-y divide-gray-100">
        {hospitals.map((h) => {
          const label = h.hospital_name ?? h.location_name;
          return (
            <li
              key={h.id}
              className="px-4 py-2.5 flex items-center gap-3 text-left"
            >
              <Hospital className="h-4 w-4 text-blue-600 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-gray-800 truncate">
                  {label}
                </div>
                {h.hospital_address && (
                  <div className="text-xs text-gray-600 truncate">
                    {h.hospital_address}
                  </div>
                )}
                {!h.hospital_address && (h.city || h.state) && (
                  <div className="text-xs text-gray-500">
                    {[h.city, h.state, h.zip].filter(Boolean).join(", ")}
                  </div>
                )}
              </div>
              {h.distance_miles !== undefined && (
                <span className="text-xs font-medium text-blue-700 bg-blue-50 rounded px-1.5 py-0.5 flex-shrink-0">
                  {h.distance_miles.toFixed(1)} mi
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </CardFrame>
  );
}

// ============================================================================
// ChargeInfoCard — get_charge
// ============================================================================

function ChargeInfoCard({ charge }: { charge: ChargeRow }) {
  return (
    <CardFrame
      title={`Charge #${charge.id}`}
      subtitle={charge.description ?? undefined}
    >
      <div className="px-4 py-3 space-y-2 text-sm">
        <div className="grid grid-cols-2 gap-2">
          {[
            ["Cash", charge.discounted_cash_price],
            ["Gross", charge.gross_charge],
            ["Min", charge.min_negotiated_charge],
            ["Max", charge.max_negotiated_charge],
          ].map(([label, value]) => (
            <div
              key={String(label)}
              className="flex justify-between items-baseline text-xs bg-gray-50 rounded px-2 py-1"
            >
              <span className="text-gray-500">{label as string}</span>
              <span className="font-semibold text-gray-800">
                {fmtUsd(value as number | null)}
              </span>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {charge.setting && <Pill>{charge.setting}</Pill>}
          {charge.modifiers && <Pill>mod {charge.modifiers}</Pill>}
        </div>
        <div className="flex justify-end pt-1 border-t border-gray-100">
          <SourceChip mrf_id={charge.mrf_id} />
        </div>
      </div>
    </CardFrame>
  );
}

// ============================================================================
// ChargeListCard — list_charges_for_code
// ============================================================================

function ChargeListCard({ charges }: { charges: ChargeRow[] }) {
  return (
    <CardFrame title={`${charges.length} charges`}>
      <ul className="divide-y divide-gray-100">
        {charges.map((c) => (
          <li
            key={c.id}
            className="px-4 py-2.5 flex items-center gap-3 text-sm"
          >
            <div className="flex-1 min-w-0">
              <div className="text-gray-800 text-xs truncate">
                {c.description ?? `Charge #${c.id}`}
              </div>
              {c.setting && (
                <div className="text-[10px] uppercase tracking-wide text-gray-400 mt-0.5">
                  {c.setting}
                </div>
              )}
            </div>
            <div className="text-xs font-semibold text-gray-800 w-20 text-right flex-shrink-0">
              {fmtUsd(c.discounted_cash_price)}
            </div>
            <SourceChip mrf_id={c.mrf_id} />
          </li>
        ))}
      </ul>
    </CardFrame>
  );
}

// ============================================================================
// PayerRateListCard — list_payer_rates_for_charge
// ============================================================================

function PayerRateListCard({ rates }: { rates: PayerRateRow[] }) {
  return (
    <CardFrame title={`${rates.length} payer rates`}>
      <ul className="divide-y divide-gray-100">
        {rates.map((r) => (
          <li
            key={r.id}
            className="px-4 py-2 flex items-center gap-3 text-sm"
          >
            <Shield className="h-4 w-4 text-blue-600 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-gray-800 font-medium truncate">
                {r.payer_name_raw}
              </div>
              {r.plan_name && (
                <div className="text-xs text-gray-500 truncate">
                  {r.plan_name}
                </div>
              )}
            </div>
            <div className="text-xs font-semibold text-gray-800 flex-shrink-0">
              {r.negotiated_dollar != null
                ? fmtUsd(r.negotiated_dollar)
                : r.negotiated_percentage != null
                  ? `${r.negotiated_percentage}%`
                  : "—"}
            </div>
          </li>
        ))}
      </ul>
    </CardFrame>
  );
}

