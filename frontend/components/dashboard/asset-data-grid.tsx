"use client";

import { useCallback, useMemo } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowDown,
  ArrowUp,
  ChevronsUpDown,
  Check,
  CircleAlert,
  Minus,
  Clock,
  Search,
  X,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { CpvhStatus, DealStage, RecommendationStatus, TitleSummary } from "@/lib/types";
import { RecommendationBadge, recommendationLabel } from "@/components/recommendation-badge";
import { DealStageBadge, dealStageLabel } from "@/components/deal-stage-badge";

/**
 * AssetDataGrid (R14.2, R14.4, R14.5).
 *
 * The master asset data grid for the Executive Command Dashboard. Lists each
 * title with its asset type, asking price, CPVH status, LTV multiple, and
 * recommendation badge (R14.2). Column headers are sortable (R14.4) and selecting
 * a row navigates to the Title Evaluation view (R14.5).
 *
 * All view state - the free-text title search, the recommendation filter, and the
 * sort column/direction - is mirrored into the URL query string (`?q`, `?rec`,
 * `?sort`, `?dir`). That makes a filtered/sorted view shareable and bookmarkable
 * and lets it survive a reload, while keeping this a pure function of the URL.
 */

/** Columns that can be sorted; the badge column is derived and not sortable. */
type SortableColumn =
  | "title_name"
  | "asset_type"
  | "asking_price"
  | "cpvh_status"
  | "ltv_to_cost_multiple"
  | "deal_stage";

type SortDirection = "asc" | "desc";

interface SortState {
  column: SortableColumn;
  direction: SortDirection;
}

const SORTABLE_COLUMNS: readonly SortableColumn[] = [
  "title_name",
  "asset_type",
  "asking_price",
  "cpvh_status",
  "ltv_to_cost_multiple",
  "deal_stage",
] as const;

/** Deal stages in pipeline order, used for the filter dropdown and sort key. */
const DEAL_STAGES: readonly DealStage[] = [
  "SCREENING",
  "EVALUATED",
  "IN_NEGOTIATION",
  "APPROVED",
  "CLOSED_WON",
  "CLOSED_LOST",
  "PASSED",
] as const;

/** Rank deal stages by pipeline position so sorting follows the lifecycle. */
const DEAL_STAGE_ORDER: Record<DealStage, number> = {
  SCREENING: 0,
  EVALUATED: 1,
  IN_NEGOTIATION: 2,
  APPROVED: 3,
  CLOSED_WON: 4,
  CLOSED_LOST: 5,
  PASSED: 6,
};

const RECOMMENDATION_FILTERS: readonly RecommendationStatus[] = [
  "GREENLIGHT",
  "NEGOTIATE_HARD",
  "PASS",
] as const;

/** Human-readable labels for the enumerated asset types. */
const ASSET_TYPE_LABELS: Record<TitleSummary["asset_type"], string> = {
  ORIGINAL_SERIES: "Original Series",
  ORIGINAL_FILM: "Original Film",
  LICENSED_LIBRARY: "Licensed Library",
  CO_PRODUCTION: "Co-Production",
};

/** Display labels and badge styling for each CPVH status. */
const CPVH_STATUS_META: Record<
  CpvhStatus,
  { label: string; className: string; icon: LucideIcon }
> = {
  PASS: { label: "Pass", className: "text-emerald-400", icon: Check },
  BREACH: { label: "Breach", className: "text-rose-400", icon: CircleAlert },
  NO_CEILING: { label: "No Ceiling", className: "text-slate-400", icon: Minus },
  PENDING: { label: "Pending", className: "text-slate-500", icon: Clock },
};

/** Rank CPVH statuses so sorting is meaningful (best-to-worst / known-first). */
const CPVH_STATUS_ORDER: Record<CpvhStatus, number> = {
  PASS: 0,
  NO_CEILING: 1,
  BREACH: 2,
  PENDING: 3,
};

/** Resolve the comparable key for a row on the active sort column. */
function sortKey(row: TitleSummary, column: SortableColumn): number | string {
  switch (column) {
    case "title_name":
      return row.title_name.toLowerCase();
    case "asset_type":
      return ASSET_TYPE_LABELS[row.asset_type] ?? row.asset_type;
    case "asking_price":
      return row.asking_price;
    case "cpvh_status":
      return CPVH_STATUS_ORDER[row.cpvh_status];
    case "ltv_to_cost_multiple":
      return row.ltv_to_cost_multiple ?? Number.NEGATIVE_INFINITY;
    case "deal_stage":
      return DEAL_STAGE_ORDER[row.deal_stage ?? "SCREENING"];
  }
}

function compareRows(a: TitleSummary, b: TitleSummary, sort: SortState): number {
  const keyA = sortKey(a, sort.column);
  const keyB = sortKey(b, sort.column);

  let result: number;
  if (typeof keyA === "number" && typeof keyB === "number") {
    result = keyA - keyB;
  } else {
    result = String(keyA).localeCompare(String(keyB));
  }

  return sort.direction === "asc" ? result : -result;
}

/** Format a native-currency asking price (not USD-normalized). */
function formatPrice(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${value.toLocaleString("en-US")} ${currency}`;
  }
}

/** Format an LTV multiple as e.g. `3.20×`, or a dash when not yet computed. */
function formatMultiple(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(2)}×`;
}

interface ColumnDef {
  key: SortableColumn;
  label: string;
  numeric?: boolean;
}

const COLUMNS: ColumnDef[] = [
  { key: "title_name", label: "Title" },
  { key: "asset_type", label: "Asset Type" },
  { key: "asking_price", label: "Asking Price", numeric: true },
  { key: "cpvh_status", label: "CPVH Status" },
  { key: "ltv_to_cost_multiple", label: "LTV Multiple", numeric: true },
  { key: "deal_stage", label: "Deal Stage" },
];

function SortIcon({ active, direction }: { active: boolean; direction: SortDirection }) {
  if (!active) {
    return <ChevronsUpDown className="h-3.5 w-3.5 text-muted-foreground/60" aria-hidden />;
  }
  return direction === "asc" ? (
    <ArrowUp className="h-3.5 w-3.5" aria-hidden />
  ) : (
    <ArrowDown className="h-3.5 w-3.5" aria-hidden />
  );
}

/** Parse a sort column from the URL, falling back to the default. */
function parseSortColumn(raw: string | null): SortableColumn {
  return (SORTABLE_COLUMNS as readonly string[]).includes(raw ?? "")
    ? (raw as SortableColumn)
    : "title_name";
}

/** Parse a recommendation filter from the URL, or null for "all". */
function parseRecFilter(raw: string | null): RecommendationStatus | null {
  return (RECOMMENDATION_FILTERS as readonly string[]).includes(raw ?? "")
    ? (raw as RecommendationStatus)
    : null;
}

/** Parse a deal-stage filter from the URL, or null for "all". */
function parseStageFilter(raw: string | null): DealStage | null {
  return (DEAL_STAGES as readonly string[]).includes(raw ?? "")
    ? (raw as DealStage)
    : null;
}

export interface AssetDataGridProps {
  titles: TitleSummary[];
  className?: string;
}

export function AssetDataGrid({ titles, className }: AssetDataGridProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const query = searchParams.get("q") ?? "";
  const recFilter = parseRecFilter(searchParams.get("rec"));
  const stageFilter = parseStageFilter(searchParams.get("stage"));
  const sortParam = searchParams.get("sort");
  const dirParam = searchParams.get("dir");
  const sort: SortState = useMemo(
    () => ({
      column: parseSortColumn(sortParam),
      direction: dirParam === "desc" ? "desc" : "asc",
    }),
    [sortParam, dirParam],
  );

  // Write the given params into the URL (replacing, so filtering does not spam
  // the history stack). A null value drops the key, keeping URLs tidy.
  const updateParams = useCallback(
    (updates: Record<string, string | null>) => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(updates)) {
        if (value === null || value === "") {
          next.delete(key);
        } else {
          next.set(key, value);
        }
      }
      const qs = next.toString();
      router.replace(qs ? `/dashboard?${qs}` : "/dashboard", { scroll: false });
    },
    [router, searchParams],
  );

  const visibleTitles = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = titles.filter((t) => {
      if (needle && !t.title_name.toLowerCase().includes(needle)) return false;
      if (recFilter && t.recommendation_status !== recFilter) return false;
      if (stageFilter && (t.deal_stage ?? "SCREENING") !== stageFilter) return false;
      return true;
    });
    return filtered.sort((a, b) => compareRows(a, b, sort));
  }, [titles, query, recFilter, stageFilter, sort]);

  function toggleSort(column: SortableColumn) {
    if (sort.column === column) {
      updateParams({ sort: column, dir: sort.direction === "asc" ? "desc" : "asc" });
    } else {
      updateParams({ sort: column, dir: "asc" });
    }
  }

  function navigateToTitle(titleId: string) {
    router.push(`/titles/${titleId}`);
  }

  const hasActiveFilters = query.trim() !== "" || recFilter !== null || stageFilter !== null;

  // Empty *pipeline* (no titles at all) keeps the original onboarding state.
  if (titles.length === 0) {
    return (
      <div
        className={cn(
          "flex flex-col items-center gap-4 rounded-lg border border-dashed border-slate-700 bg-slate-900/60 p-12 text-center",
          className,
        )}
      >
        <div className="rounded-full bg-slate-800 p-3">
          <Clock className="h-6 w-6 text-slate-400" aria-hidden />
        </div>
        <div className="space-y-1">
          <p className="text-sm font-medium text-slate-200">
            No active titles in the pipeline yet.
          </p>
          <p className="text-sm text-slate-400">
            Evaluate your first asset to populate the dashboard.
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <Link
            href="/studio"
            className="inline-flex items-center rounded-md bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 hover:bg-emerald-400"
          >
            Evaluate an asset
          </Link>
          <Link
            href="/guide"
            className="inline-flex items-center rounded-md border border-slate-700 px-4 py-2 text-sm font-medium text-slate-200 hover:bg-slate-800"
          >
            How it works
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className={cn("space-y-3", className)}>
      {/* Filter / search toolbar - all state is mirrored into the URL. */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[14rem] flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <input
            type="search"
            value={query}
            onChange={(e) => updateParams({ q: e.target.value })}
            placeholder="Search titles..."
            aria-label="Search titles by name"
            className="w-full rounded-md border border-slate-700 bg-slate-900/60 py-2 pl-9 pr-3 text-sm text-slate-100 placeholder:text-slate-500 focus:border-emerald-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
          />
        </div>

        <div className="flex items-center gap-2">
          <label htmlFor="rec-filter" className="text-sm text-muted-foreground">
            Recommendation
          </label>
          <select
            id="rec-filter"
            value={recFilter ?? ""}
            onChange={(e) => updateParams({ rec: e.target.value || null })}
            className="rounded-md border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
          >
            <option value="">All</option>
            {RECOMMENDATION_FILTERS.map((status) => (
              <option key={status} value={status}>
                {recommendationLabel(status)}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <label htmlFor="stage-filter" className="text-sm text-muted-foreground">
            Deal stage
          </label>
          <select
            id="stage-filter"
            value={stageFilter ?? ""}
            onChange={(e) => updateParams({ stage: e.target.value || null })}
            className="rounded-md border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-100 focus:border-emerald-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
          >
            <option value="">All</option>
            {DEAL_STAGES.map((stage) => (
              <option key={stage} value={stage}>
                {dealStageLabel(stage)}
              </option>
            ))}
          </select>
        </div>

        {hasActiveFilters ? (
          <button
            type="button"
            onClick={() => updateParams({ q: null, rec: null, stage: null })}
            className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
          >
            <X className="h-3.5 w-3.5" aria-hidden />
            Clear
          </button>
        ) : null}

        <span className="text-sm text-muted-foreground" role="status" aria-live="polite">
          {visibleTitles.length} of {titles.length}
        </span>
      </div>

      {visibleTitles.length === 0 ? (
        <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-10 text-center">
          <p className="text-sm font-medium text-slate-200">No titles match your filters.</p>
          <button
            type="button"
            onClick={() => updateParams({ q: null, rec: null, stage: null })}
            className="mt-3 inline-flex items-center gap-1 rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
          >
            <X className="h-3.5 w-3.5" aria-hidden />
            Clear filters
          </button>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900/60">
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">Master asset data grid of pipeline titles</caption>
            <thead>
              <tr className="border-b bg-muted/50 text-left">
                {COLUMNS.map((col) => {
                  const active = sort.column === col.key;
                  return (
                    <th
                      key={col.key}
                      scope="col"
                      aria-sort={
                        active
                          ? sort.direction === "asc"
                            ? "ascending"
                            : "descending"
                          : "none"
                      }
                      className={cn("px-4 py-3 font-medium", col.numeric && "text-right")}
                    >
                      <button
                        type="button"
                        onClick={() => toggleSort(col.key)}
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          col.numeric && "flex-row-reverse",
                          active ? "text-foreground" : "text-muted-foreground",
                        )}
                      >
                        <span>{col.label}</span>
                        <SortIcon active={active} direction={sort.direction} />
                      </button>
                    </th>
                  );
                })}
                <th scope="col" className="px-4 py-3 font-medium text-muted-foreground">
                  Recommendation
                </th>
              </tr>
            </thead>
            <tbody>
              {visibleTitles.map((title) => {
                const cpvh = CPVH_STATUS_META[title.cpvh_status];
                return (
                  <tr
                    key={title.title_id}
                    tabIndex={0}
                    role="button"
                    aria-label={`Open evaluation for ${title.title_name}`}
                    onClick={() => navigateToTitle(title.title_id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        navigateToTitle(title.title_id);
                      }
                    }}
                    className="cursor-pointer border-b last:border-b-0 transition-colors hover:bg-muted/50 focus:bg-muted/50 focus:outline-none"
                  >
                    <td className="px-4 py-3 font-medium">{title.title_name}</td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {ASSET_TYPE_LABELS[title.asset_type] ?? title.asset_type}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatPrice(title.asking_price, title.native_currency)}
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn("inline-flex items-center gap-1 font-medium", cpvh.className)}>
                        <cpvh.icon className="h-3.5 w-3.5" aria-hidden />
                        {cpvh.label}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {formatMultiple(title.ltv_to_cost_multiple)}
                    </td>
                    <td className="px-4 py-3">
                      <DealStageBadge stage={title.deal_stage ?? "SCREENING"} />
                    </td>
                    <td className="px-4 py-3">
                      <RecommendationBadge status={title.recommendation_status} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}