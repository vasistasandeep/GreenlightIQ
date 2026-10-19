"use client";

/**
 * ContentEvalBreakdown — the modeled driver-breakdown disclosures (task 18, R8.1).
 *
 * Renders one `<details>`/`<summary>` card per modeled driver carried in a
 * scorecard's `explanation.content_eval` (the additive passthrough task 12
 * threads through from a fitted `content_eval` version). Each card reuses the
 * ChurnBreakdown visual pattern: a collapsed disclosure holding a per-feature
 * contribution table (hours for `projected_viewing_hours`, points for the
 * additive engagement drivers) plus a conservation adjustment row.
 *
 * Honesty gate (R8.1): because every value here is modeled from proxy/illustrative
 * data, each card shows a visible PROXY / illustrative badge driven by the
 * driver's `label_type`. A modeled value is NEVER presented as a real-world
 * figure. The badge carries its meaning in text (not color-only) so it stays
 * accessible.
 *
 * When `explanation.content_eval` is ABSENT (the demo default — no fitted
 * version), this renders nothing, leaving the existing scorecard unchanged.
 *
 * Theme-neutral styling (amber proxy pill, muted borders) so it reads on both
 * the light title scorecard and the dark Asset Studio report.
 */

import type {
  ContentEvalContribution,
  ContentEvalDriver,
  ContentEvalExplanation,
} from "@/lib/types";
import { toNumber } from "./format";

/** Driver keys in fixed display order, with executive-facing titles + unit. */
const DRIVER_ORDER: {
  key: string;
  title: string;
  /** Which breakdown field carries the contribution for this driver. */
  unit: "hours" | "points";
  /** Column header + value suffix. */
  valueLabel: string;
}[] = [
  {
    key: "projected_viewing_hours",
    title: "Projected viewing hours",
    unit: "hours",
    valueLabel: "Hours",
  },
  {
    key: "watch_time_elasticity",
    title: "Watch-time elasticity",
    unit: "points",
    valueLabel: "Points",
  },
  {
    key: "ad_load_receptivity",
    title: "Ad-load receptivity",
    unit: "points",
    valueLabel: "Points",
  },
];

/** Keys whose contribution is a base/adjustment entry, shown last, unsigned. */
const ADJUSTMENT_KEYS = new Set([
  "base_platform_hours",
  "rounding_or_bounds_adjustment",
  "bounds_adjustment",
]);

/** Human label for an adjustment row key. */
const ADJUSTMENT_LABELS: Record<string, string> = {
  base_platform_hours: "Base Platform Hours",
  rounding_or_bounds_adjustment: "Rounding Adjustment",
  bounds_adjustment: "Bounds Adjustment",
};

/** A value is "proxy/illustrative" unless the label_type is explicitly OBSERVED. */
function isProxyLabel(labelType: string | null | undefined): boolean {
  return (labelType ?? "").toUpperCase() !== "OBSERVED";
}

/** Short, human-readable badge text for a driver's label_type (never color-only). */
function proxyBadgeText(labelType: string | null | undefined): string {
  const t = (labelType ?? "").toUpperCase();
  if (t === "SYNTHETIC") {
    return "SYNTHETIC · illustrative";
  }
  // PROXY, DEFAULTS, or anything non-OBSERVED is surfaced as proxy/illustrative.
  return "PROXY · illustrative";
}

/** Format a hours value, e.g. "1,234.5". */
function formatHours(raw: number | string | null | undefined): string {
  const n = toNumber(raw);
  if (n === null) {
    return "—";
  }
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(n);
}

/** Format a point value as signed text, e.g. "+0.35" / "0.00" / "-0.12". */
function formatSignedPoints(raw: number | string | null | undefined): string {
  const n = toNumber(raw);
  if (n === null) {
    return "0.00";
  }
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  return `${sign}${Math.abs(n).toFixed(2)}`;
}

/** The amber PROXY / illustrative pill (R8.1); the glyph is decorative. */
function ProxyBadge({ labelType }: { labelType: string | null | undefined }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-800 dark:text-amber-200">
      <span aria-hidden="true">⚠</span>
      <span>{proxyBadgeText(labelType)}</span>
    </span>
  );
}

/** Pick the contribution value for a driver's display unit. */
function contributionValue(
  row: ContentEvalContribution,
  unit: "hours" | "points",
): number | string | null | undefined {
  return unit === "hours" ? (row.hours ?? row.points) : (row.points ?? row.hours);
}

/** Human label for a contribution row, falling back to a humanized key. */
function rowLabel(row: ContentEvalContribution): string {
  if (row.label) {
    return row.label;
  }
  if (ADJUSTMENT_LABELS[row.key]) {
    return ADJUSTMENT_LABELS[row.key];
  }
  return row.key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function DriverCard({
  title,
  valueLabel,
  unit,
  driver,
}: {
  title: string;
  valueLabel: string;
  unit: "hours" | "points";
  driver: ContentEvalDriver;
}) {
  const breakdown = driver.breakdown ?? [];
  const proxy = isProxyLabel(driver.label_type);
  const formatCell = unit === "hours" ? formatHours : formatSignedPoints;
  // Adjustment / base rows render last, in their natural order.
  const featureRows = breakdown.filter((r) => !ADJUSTMENT_KEYS.has(r.key));
  const adjustmentRows = breakdown.filter((r) => ADJUSTMENT_KEYS.has(r.key));
  const orderedRows = [...featureRows, ...adjustmentRows];
  const resolvedValue = formatCell(driver.value);

  return (
    <details className="group mt-4 rounded-md border bg-muted/20">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span className="flex flex-wrap items-center gap-2">
          <span>{title}</span>
          {proxy ? <ProxyBadge labelType={driver.label_type} /> : null}
        </span>
        <span
          aria-hidden="true"
          className="text-muted-foreground transition-transform group-open:rotate-180"
        >
          ▾
        </span>
      </summary>

      <div className="px-3 pb-3">
        <p className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          <span>Modeled driver breakdown</span>
          <span className="font-normal normal-case tracking-normal">
            Resolved value:{" "}
            <span className="font-semibold text-foreground tabular-nums">
              {resolvedValue}
            </span>{" "}
            {valueLabel.toLowerCase()}
          </span>
        </p>

        {proxy ? (
          <p className="mb-2 text-xs text-muted-foreground">
            This is a modeled, proxy-trained estimate — not a measured
            real-world figure.
          </p>
        ) : null}

        {orderedRows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No per-feature breakdown is available for this driver.
          </p>
        ) : (
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">
              Per-feature modeled contributions for {title} (
              {unit === "hours" ? "hours" : "points"})
            </caption>
            <thead>
              <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  Driver
                </th>
                <th scope="col" className="py-1.5 text-right font-medium">
                  {valueLabel}
                </th>
              </tr>
            </thead>
            <tbody>
              {orderedRows.map((row) => (
                <tr key={row.key} className="border-b last:border-b-0">
                  <th
                    scope="row"
                    className="py-1.5 pr-3 text-left font-normal text-foreground"
                  >
                    {rowLabel(row)}
                  </th>
                  <td className="py-1.5 text-right tabular-nums">
                    {formatCell(contributionValue(row, unit))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {driver.version_label ? (
          <p className="mt-2 text-[11px] text-muted-foreground">
            Fitted version:{" "}
            <span className="font-medium text-foreground">
              {driver.version_label}
            </span>
          </p>
        ) : null}
      </div>
    </details>
  );
}

export interface ContentEvalBreakdownProps {
  contentEval: ContentEvalExplanation | null | undefined;
}

export function ContentEvalBreakdown({ contentEval }: ContentEvalBreakdownProps) {
  // No fitted version -> no content_eval block -> render nothing (demo default).
  if (contentEval === null || contentEval === undefined) {
    return null;
  }

  const cards = DRIVER_ORDER.filter(({ key }) => contentEval[key] != null).map(
    ({ key, title, unit, valueLabel }) => (
      <DriverCard
        key={key}
        title={title}
        valueLabel={valueLabel}
        unit={unit}
        driver={contentEval[key]}
      />
    ),
  );

  if (cards.length === 0) {
    return null;
  }

  return (
    <section aria-labelledby="content-eval-breakdown-heading" className="mt-4">
      <h3
        id="content-eval-breakdown-heading"
        className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
      >
        Modeled engagement drivers
      </h3>
      {cards}
    </section>
  );
}
