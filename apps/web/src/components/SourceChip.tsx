// `ⓘ` info icon attached to MRF-sourced data. Lazy-fetches the MRF row
// (URL + linked hospitals + publish date) once per id and caches in a
// module-level map so multiple chips with the same mrf_id share one
// request. The hover popover machinery (portal, viewport clamping, hide
// delay) is shared with other tooltips via `InfoTooltip`.

import { useEffect, useState } from "react";
import { ExternalLink, Info } from "lucide-react";
import { cn } from "../lib/cn";
import { InfoTooltip } from "./InfoTooltip";
import { WarningNote } from "./WarningNote";

interface MrfRow {
  id: number;
  mrf_url: string;
  last_updated_on?: string;
  // get_mrf joins through hospital_mrfs and returns the hospitals this
  // file covers. Usually 1; multi-location MRFs (Cottage Health, Kaiser,
  // Berkshire MC) can list many.
  hospitals?: { id: number; name: string }[];
}

// Render an MRF's `last_updated_on` consistently across both the single
// and multi tooltip variants. Input from the API is typically ISO
// `YYYY-MM-DD`; we render as `MM/DD/YYYY`. Anything unparseable falls
// through as the raw string so we never blank-out data.
function formatMrfDate(raw: string | undefined): string | null {
  if (!raw) return null;
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(d.getUTCDate()).padStart(2, "0");
  const yyyy = d.getUTCFullYear();
  return `${mm}/${dd}/${yyyy}`;
}

// Module-level cache so multiple chips for the same mrf_id share one
// fetch. Only successful results are cached — failures are evicted so
// the next render retries instead of cementing a "Loading…" placeholder.
const _mrfCache = new Map<number, Promise<MrfRow>>();

function fetchMrf(id: number): Promise<MrfRow | null> {
  let p = _mrfCache.get(id);
  if (!p) {
    p = fetch(`/api/agent/tools/get_mrf?id=${id}`).then(async (r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as { data?: MrfRow };
      if (!j?.data) throw new Error("empty response");
      return j.data;
    });
    p.catch(() => _mrfCache.delete(id));
    _mrfCache.set(id, p);
  }
  return p.catch(() => null);
}

export function SourceChip({
  mrf_id,
  className,
}: {
  mrf_id: number;
  className?: string;
}) {
  const [row, setRow] = useState<MrfRow | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchMrf(mrf_id).then((r) => {
      if (!cancelled) setRow(r);
    });
    return () => {
      cancelled = true;
    };
  }, [mrf_id]);

  const label =
    row?.hospitals && row.hospitals.length > 0
      ? `Source: ${row.hospitals[0].name}`
      : `MRF #${mrf_id}`;

  return (
    <InfoTooltip
      ariaLabel={label}
      triggerClassName={cn(
        "h-4 w-4 text-gray-400",
        !row && "opacity-60",
        className,
      )}
      contentClassName="space-y-1"
    >
      {row ? (
        <>
          <div className="font-bold text-black break-words">
            Source:{" "}
            {row.hospitals && row.hospitals.length > 0 ? (
              <>
                {row.hospitals[0].name}
                {row.hospitals.length > 1
                  ? ` +${row.hospitals.length - 1} more`
                  : ""}{" "}
                MRF
              </>
            ) : (
              "Hospital MRF"
            )}
          </div>
          {formatMrfDate(row.last_updated_on) && (
            <div>Last Updated: {formatMrfDate(row.last_updated_on)}</div>
          )}
          <a
            href={row.mrf_url}
            target="_blank"
            rel="noopener noreferrer"
            className="block text-blue-600 hover:underline break-all"
          >
            {row.mrf_url}
          </a>
          <WarningNote className="pt-1 border-t border-gray-100 mt-2">
            Some links auto-download the raw MRF file. Click at your own
            discretion.
          </WarningNote>
        </>
      ) : (
        <div className="text-gray-500">Loading…</div>
      )}
    </InfoTooltip>
  );
}

// Aggregate variant — one chip standing in for a list of source MRF ids.
// Uses the same `InfoTooltip` popover as the single-row variant, but
// collapses each MRF into a compact one-line row (hospital · date · link)
// so dozens of sources stay readable.
const MULTI_LIMIT = 20;

export function SourceChipMulti({
  mrf_ids,
  className,
}: {
  mrf_ids: number[];
  className?: string;
}) {
  const [rows, setRows] = useState<(MrfRow | null)[]>([]);

  useEffect(() => {
    let cancelled = false;
    Promise.all(mrf_ids.slice(0, MULTI_LIMIT).map(fetchMrf)).then((rs) => {
      if (!cancelled) setRows(rs);
    });
    return () => {
      cancelled = true;
    };
  }, [mrf_ids]);

  const resolved = rows.filter((r): r is MrfRow => r !== null);
  const remaining = mrf_ids.length - MULTI_LIMIT;

  return (
    <InfoTooltip
      width={400}
      ariaLabel={`${mrf_ids.length} MRF source files`}
      triggerClassName="h-4 w-4 text-gray-400"
      icon={<Info className="h-3.5 w-3.5" strokeWidth={2.5} />}
      contentClassName={className}
    >
      <div className="font-bold text-black mb-1">
        {mrf_ids.length} MRF source files
      </div>
      <ul className="divide-y divide-gray-100 max-h-72 overflow-y-auto">
        {resolved.map((r) => {
          const label =
            r.hospitals && r.hospitals.length > 0
              ? r.hospitals[0].name +
                (r.hospitals.length > 1 ? ` +${r.hospitals.length - 1}` : "")
              : `MRF #${r.id}`;
          const date = formatMrfDate(r.last_updated_on);
          return (
            <li
              key={r.id}
              className="flex items-center gap-2 py-1"
            >
              <span className="flex-1 truncate" title={label}>
                {label}
              </span>
              {date && (
                <span className="text-gray-400 tabular-nums flex-shrink-0">
                  {date}
                </span>
              )}
              <a
                href={r.mrf_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:text-blue-800 flex-shrink-0"
                aria-label="Open MRF file"
              >
                <ExternalLink className="h-3 w-3" />
              </a>
            </li>
          );
        })}
      </ul>
      {remaining > 0 && (
        <div className="text-gray-400 pt-1 mt-1 border-t border-gray-100">
          … +{remaining} more
        </div>
      )}
      <WarningNote className="pt-1 border-t border-gray-100 mt-2">
        Some links auto-download the raw MRF file. Click at your own
        discretion.
      </WarningNote>
    </InfoTooltip>
  );
}
