"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowDown,
  ArrowUp,
  ChevronsUpDown,
  Check,
  CircleAlert,
  Minus,
  Clock,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { CpvhStatus, TitleSummary } from "@/lib/types";
import { RecommendationBadge } from "@/components/recommendation-badge";

/**
 * AssetDataGrid (R14.2, R14.4, R14.5).
 *
 * The master asset data grid for the Executive Command Dashboard. Lists each
 * title with its asset type, asking price, CPVH status, LTV multiple, and
 * recommendation badge (R14.2). Column headers are sortable — selecting one
 * reorders rows and toggling re-selects direction (R14.4). Selecting a row
 * navigates to the Title Evaluation view for that title (R14.5).
 */

/** Columns that can be sorted; the badge column is derived and not sortable. */
type SortableColumn =
  | "title_name"
  | "asset_type"
  | "asking_price"
  | "cpvh_status"
  | "ltv_to_cost_multiple";

type SortDirection = "asc" | "desc";

interface SortState {
  column: SortableColumn;
  direction: SortDirection;
}

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
      // Nulls sort last regardless of direction by using -Infinity for asc baseline;
      // handled in the comparator below.
      return row.ltv_to_cost_multiple ?? Number.NEGATIVE_INFINITY;
  }
}

function compareRows(
  a: TitleSummary,
  b: TitleSummary,
  sort: SortState,
): number {
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
    // Fall back for non-ISO currency codes.
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

export interface AssetDataGridProps {
  titles: TitleSummary[];
  className?: string;
}

export function AssetDataGrid({ titles, className }: AssetDataGridProps) {
  const router = useRouter();
  const [sort, setSort] = useState<SortState>({
    column: "title_name",
    direction: "asc",
  });

  const sortedTitles = useMemo(() => {
    return [...titles].sort((a, b) => compareRows(a, b, sort));
  }, [titles, sort]);

  function toggleSort(column: SortableColumn) {
    setSort((prev) =>
      prev.column === column
        ? { column, direction: prev.direction === "asc" ? "desc" : "asc" }
        : { column, direction: "asc" },
    );
  }

  function navigateToTitle(titleId: string) {
    router.push(`/titles/${titleId}`);
  }

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
    <div className={cn("overflow-x-auto rounded-lg border border-slate-800 bg-slate-900/60", className)}>
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">
          Master asset data grid of pipeline titles
        </caption>
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
                  className={cn(
                    "px-4 py-3 font-medium",
                    col.numeric && "text-right",
                  )}
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
          {sortedTitles.map((title) => {
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
                  <RecommendationBadge status={title.recommendation_status} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
