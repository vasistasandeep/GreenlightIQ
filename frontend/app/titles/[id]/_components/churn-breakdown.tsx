"use client";

/**
 * ChurnBreakdown — the "Churn Drivers Breakdown" disclosure (R10).
 *
 * Renders the per-feature contributions of a CALCULATED churn-reduction
 * percentage inside a native `<details>`/`<summary>` disclosure (keyboard
 * operable, matching the FinancialAccordion pattern). For a SUPPLIED result it
 * shows a short note instead of the table (R10.3). The amber borderline pill
 * (R10.5) renders the fixed message with a decorative warning glyph; the text
 * carries the meaning (R10.6).
 *
 * Theme-neutral styling (amber pill, muted borders) so it reads on both the
 * light title scorecard and the dark Asset Studio report.
 */

import type { ChurnModel } from "@/lib/types";

/** The fixed borderline message wording (R5.4, R10.5). */
export const BORDERLINE_MESSAGE =
  "Borderline Sensitivity: within 0.05% of the 1.50% hurdle";

/**
 * The six feature rows in fixed display order, mapping each breakdown key to
 * its executive-facing label (R10.1).
 */
const FEATURE_ROWS: { key: string; label: string }[] = [
  { key: "base_platform_rate", label: "Base Platform Rate" },
  { key: "asset_cadence", label: "Asset Cadence" },
  { key: "talent_pedigree_contribution", label: "Talent Pedigree Contribution" },
  { key: "production_scale_contribution", label: "Production Scale Contribution" },
  { key: "exclusivity_lift", label: "Exclusivity Lift" },
  { key: "market_telemetry_heat", label: "Market Telemetry Heat" },
  { key: "genre_affinity", label: "Genre Affinity" },
  { key: "content_format", label: "Content Format" },
];

/**
 * Breakdown keys that an `assumed_features` entry can refer to. An assumed
 * feature used a neutral default (no real reading) rather than being missing:
 * a missing market-telemetry reading, or an unknown/absent genre (R14.3, R15.2).
 */
const ASSUMED_FEATURE_ALIASES: Record<string, string[]> = {
  market_telemetry_heat: ["telemetry_heat"],
  genre_affinity: ["genre"],
  content_format: ["content_format"],
};

/**
 * Breakdown keys that a `missing_features` entry can refer to. A feature may be
 * reported under more than one alias, so each breakdown key lists the aliases
 * that mark it unavailable (R10.4).
 */
const MISSING_FEATURE_ALIASES: Record<string, string[]> = {
  talent_pedigree_contribution: ["pedigree", "talent_pedigree_score"],
  production_scale_contribution: ["production_scale"],
  market_telemetry_heat: ["telemetry_heat"],
  asset_cadence: ["asset_type"],
};

/** Format a point value as signed text, e.g. "+0.35" / "0.00" / "-0.12". */
function formatSignedPoints(raw: string | undefined): string {
  const n = Number(raw);
  if (!Number.isFinite(n)) {
    return "0.00";
  }
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  return `${sign}${Math.abs(n).toFixed(2)}`;
}

/** The amber borderline pill (R10.5); the warning glyph is decorative (R10.6). */
function BorderlinePill() {
  return (
    <p className="mt-3 flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm font-medium text-amber-800 dark:text-amber-200">
      <span aria-hidden="true" className="leading-5">
        ⚠
      </span>
      <span>{BORDERLINE_MESSAGE}</span>
    </p>
  );
}

export interface ChurnBreakdownProps {
  churnModel: ChurnModel | null | undefined;
}

export function ChurnBreakdown({ churnModel }: ChurnBreakdownProps) {
  // A pre-feature scorecard renders nothing extra (R7.6).
  if (churnModel === null || churnModel === undefined) {
    return null;
  }

  const isSupplied =
    churnModel.churn_method === "SUPPLIED" || churnModel.churn_breakdown == null;
  const breakdown = churnModel.churn_breakdown ?? {};
  const missing = new Set(churnModel.missing_features ?? []);
  const assumed = new Set(churnModel.assumed_features ?? []);

  function isMissing(key: string): boolean {
    const aliases = MISSING_FEATURE_ALIASES[key] ?? [];
    return aliases.some((alias) => missing.has(alias));
  }

  function isAssumed(key: string): boolean {
    const aliases = ASSUMED_FEATURE_ALIASES[key] ?? [];
    return aliases.some((alias) => assumed.has(alias));
  }

  const showBoundsRow =
    !isSupplied &&
    churnModel.churn_breakdown != null &&
    "bounds_adjustment" in churnModel.churn_breakdown;

  return (
    <details className="group mt-4 rounded-md border bg-muted/20">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span>Why this churn number</span>
        <span
          aria-hidden="true"
          className="text-muted-foreground transition-transform group-open:rotate-180"
        >
          ▾
        </span>
      </summary>

      <div className="px-3 pb-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Churn Drivers Breakdown
        </p>

        {isSupplied ? (
          <p className="text-sm text-muted-foreground">
            Supplied directly (not calculated)
          </p>
        ) : (
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">
              Per-feature churn-reduction contributions in percentage points
            </caption>
            <thead>
              <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th scope="col" className="py-1.5 pr-3 font-medium">
                  Driver
                </th>
                <th scope="col" className="py-1.5 text-right font-medium">
                  Points
                </th>
              </tr>
            </thead>
            <tbody>
              {FEATURE_ROWS.map(({ key, label }) => {
                const missingRow = isMissing(key);
                // "Assumed" means a neutral default was used (no real reading),
                // distinct from "unavailable" (missing -> contributes 0).
                const assumedRow = !missingRow && isAssumed(key);
                const value = missingRow ? "0.00" : breakdown[key];
                return (
                  <tr key={key} className="border-b last:border-b-0">
                    <th
                      scope="row"
                      className="py-1.5 pr-3 text-left font-normal text-foreground"
                    >
                      {label}
                      {missingRow ? (
                        <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                          unavailable
                        </span>
                      ) : null}
                      {assumedRow ? (
                        <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                          {key === "genre_affinity"
                            ? "neutral (unlisted genre)"
                            : key === "content_format"
                              ? "neutral (unlisted format)"
                              : "neutral (no market data)"}
                        </span>
                      ) : null}
                    </th>
                    <td className="py-1.5 text-right tabular-nums">
                      {formatSignedPoints(value)}
                    </td>
                  </tr>
                );
              })}
              {showBoundsRow ? (
                <tr className="border-b last:border-b-0">
                  <th
                    scope="row"
                    className="py-1.5 pr-3 text-left font-normal text-foreground"
                  >
                    Bounds Adjustment
                  </th>
                  <td className="py-1.5 text-right tabular-nums">
                    {formatSignedPoints(breakdown.bounds_adjustment)}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        )}

        {churnModel.is_borderline ? <BorderlinePill /> : null}
      </div>
    </details>
  );
}
