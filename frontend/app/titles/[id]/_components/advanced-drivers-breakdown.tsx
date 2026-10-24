"use client";

/**
 * AdvancedDriversBreakdown - the Advanced_Content_Eval_Drivers disclosures (task 16, R6.1-R6.5).
 *
 * Renders one `<details>`/`<summary>` card per resolved driver carried in a
 * scorecard's `explanation.advanced_drivers` (the additive provenance block the
 * provider threads through only when a per-driver kill-switch is on and that
 * driver resolved). Each card reuses the ChurnBreakdown / ContentEvalBreakdown
 * visual pattern: a collapsed disclosure holding a per-line contribution table.
 *
 * Signed diffs (R6.4): a line that moves the prediction relative to its neutral
 * baseline renders a signed delta (value before, value after, and the signed
 * difference) using ASCII-only text and the defensive `toNumber()` coercion. A
 * non-coercible value renders a "--" placeholder while the other lines still
 * render. The Comps card also surfaces comps confidence - the realized `k` and
 * the inter-quartile Comps_Dispersion (R6.2).
 *
 * Gated / graceful (R6.5, R7.2): when `explanation.advanced_drivers` is ABSENT
 * (flags off / pre-feature) this renders nothing, leaving the scorecard byte-
 * identical. A driver entry that is null/absent renders no card for that driver.
 *
 * Theme-neutral styling (muted borders) so it reads on both the light title
 * scorecard and the dark Asset Studio report.
 */

import type { AdvancedDriversExplanation } from "@/lib/types";
import { toNumber } from "./format";

/** ASCII placeholder for a value that could not be coerced to a finite number. */
const PLACEHOLDER = "--";

/** Format a whole-hour value with grouping, or the ASCII placeholder. */
function formatHours(raw: number | string | null | undefined): string {
  const n = toNumber(raw);
  if (n === null) {
    return PLACEHOLDER;
  }
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 1,
  }).format(n);
}

/** Format a signed whole-hour delta, e.g. "+1,200" / "0" / "-350", or placeholder. */
function formatSignedHours(raw: number | string | null | undefined): string {
  const n = toNumber(raw);
  if (n === null) {
    return PLACEHOLDER;
  }
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  return `${sign}${new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 1,
  }).format(Math.abs(n))}`;
}

/** Format a signed percentage-point churn value, e.g. "+0.35" / "0.00", or placeholder. */
function formatSignedPoints(raw: number | string | null | undefined): string {
  const n = toNumber(raw);
  if (n === null) {
    return PLACEHOLDER;
  }
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  return `${sign}${Math.abs(n).toFixed(2)}`;
}

/** Format a bounded multiplier, e.g. "1.25x", or the ASCII placeholder. */
function formatMultiplier(raw: number | string | null | undefined): string {
  const n = toNumber(raw);
  if (n === null) {
    return PLACEHOLDER;
  }
  return `${n.toFixed(2)}x`;
}

/**
 * Render a multiplier's signed effect relative to the neutral 1.00 baseline as a
 * signed percentage, e.g. "+25.0%" / "0.0%" / "-5.0%", or the placeholder. This
 * is the "value before (1.00) -> value after -> difference" diff for a
 * multiplicative modifier.
 */
function formatSignedMultiplierDelta(raw: number | string | null | undefined): string {
  const n = toNumber(raw);
  if (n === null) {
    return PLACEHOLDER;
  }
  const deltaPct = (n - 1) * 100;
  const sign = deltaPct > 0 ? "+" : deltaPct < 0 ? "-" : "";
  return `${sign}${Math.abs(deltaPct).toFixed(1)}%`;
}

/** A single disclosure card wrapping a driver's breakdown table. */
function DriverCard({
  title,
  summary,
  children,
}: {
  title: string;
  summary?: string;
  children: React.ReactNode;
}) {
  return (
    <details className="group mt-4 rounded-md border bg-muted/20">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span className="flex flex-wrap items-center gap-2">
          <span>{title}</span>
          {summary ? (
            <span className="text-xs font-normal text-muted-foreground">
              {summary}
            </span>
          ) : null}
        </span>
        <span
          aria-hidden="true"
          className="text-muted-foreground transition-transform group-open:rotate-180"
        >
          {"\u25be"}
        </span>
      </summary>
      <div className="px-3 pb-3">{children}</div>
    </details>
  );
}

/** A two-column before/after/diff row inside a driver table. */
function DiffRow({
  label,
  before,
  after,
  diff,
}: {
  label: string;
  before: string;
  after: string;
  diff: string;
}) {
  return (
    <tr className="border-b last:border-b-0">
      <th
        scope="row"
        className="py-1.5 pr-3 text-left font-normal text-foreground"
      >
        {label}
      </th>
      <td className="py-1.5 text-right tabular-nums text-muted-foreground">
        {before}
      </td>
      <td className="py-1.5 text-right tabular-nums">{after}</td>
      <td className="py-1.5 text-right font-medium tabular-nums">{diff}</td>
    </tr>
  );
}

/** The 4-column header shared by the driver diff tables. */
function DiffHead() {
  return (
    <thead>
      <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
        <th scope="col" className="py-1.5 pr-3 font-medium">
          Driver
        </th>
        <th scope="col" className="py-1.5 text-right font-medium">
          Before
        </th>
        <th scope="col" className="py-1.5 text-right font-medium">
          After
        </th>
        <th scope="col" className="py-1.5 text-right font-medium">
          Delta
        </th>
      </tr>
    </thead>
  );
}

function CompsCard({
  comps,
}: {
  comps: NonNullable<AdvancedDriversExplanation["comps"]>;
}) {
  const fallback = comps.use_intercept_fallback;
  return (
    <DriverCard
      title="Comps anchor"
      summary={`${comps.realized_k} comps`}
    >
      {fallback ? (
        <p className="text-sm text-muted-foreground">
          No eligible comps in the budget band; the model fell back to the
          default viewing-hours intercept (DETERMINISTIC_FALLBACK).
        </p>
      ) : (
        <>
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">
              Comps anchor hour and churn contributions
            </caption>
            <tbody>
              <tr className="border-b last:border-b-0">
                <th
                  scope="row"
                  className="py-1.5 pr-3 text-left font-normal text-foreground"
                >
                  H_comps (base hours)
                </th>
                <td className="py-1.5 text-right tabular-nums">
                  {formatHours(comps.h_comps)}
                </td>
              </tr>
              <tr className="border-b last:border-b-0">
                <th
                  scope="row"
                  className="py-1.5 pr-3 text-left font-normal text-foreground"
                >
                  C_comps (churn anchor)
                </th>
                <td className="py-1.5 text-right tabular-nums">
                  {formatSignedPoints(comps.c_comps)}
                </td>
              </tr>
            </tbody>
          </table>
          <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
            <div>
              <dt className="text-muted-foreground">Comps confidence (k)</dt>
              <dd className="font-medium tabular-nums">{comps.realized_k}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Dispersion (IQR)</dt>
              <dd className="font-medium tabular-nums">
                {formatHours(comps.dispersion_iqr)}
              </dd>
            </div>
          </dl>
        </>
      )}
    </DriverCard>
  );
}

function LineageCard({
  lineage,
}: {
  lineage: NonNullable<AdvancedDriversExplanation["lineage"]>;
}) {
  if (!lineage.is_active) {
    return (
      <DriverCard title="Franchise lineage" summary="not a franchise">
        <p className="text-sm text-muted-foreground">
          Not a franchise entry; no floor and a zero churn credit, leaving the
          base prediction unchanged.
        </p>
      </DriverCard>
    );
  }
  return (
    <DriverCard title="Franchise lineage" summary="franchise floor">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">
          Franchise floor hour lift and churn loyalty credit
        </caption>
        <thead>
          <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th scope="col" className="py-1.5 pr-3 font-medium">
              Driver
            </th>
            <th scope="col" className="py-1.5 text-right font-medium">
              Contribution
            </th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-b last:border-b-0">
            <th
              scope="row"
              className="py-1.5 pr-3 text-left font-normal text-foreground"
            >
              Franchise floor lift
            </th>
            <td className="py-1.5 text-right tabular-nums">
              {formatSignedHours(lineage.franchise_floor)}
            </td>
          </tr>
          <tr className="border-b last:border-b-0">
            <th
              scope="row"
              className="py-1.5 pr-3 text-left font-normal text-foreground"
            >
              Franchise loyalty credit
            </th>
            <td className="py-1.5 text-right tabular-nums">
              {formatSignedPoints(lineage.delta_c_franchise)}
            </td>
          </tr>
        </tbody>
      </table>
    </DriverCard>
  );
}

function MomentumCard({
  momentum,
}: {
  momentum: NonNullable<AdvancedDriversExplanation["momentum"]>;
}) {
  const note = momentum.stage_excluded
    ? `Stage-excluded${momentum.production_stage ? ` (${momentum.production_stage})` : ""}: multiplier forced to 1.00.`
    : momentum.reason === "STALE"
      ? "Telemetry stale: multiplier degraded to 1.00."
      : momentum.reason === "UNAVAILABLE"
        ? "Telemetry unavailable: multiplier degraded to 1.00."
        : null;
  return (
    <DriverCard
      title="Momentum telemetry"
      summary={`bounds ${momentum.bounds}`}
    >
      {note ? (
        <p className="mb-2 text-sm text-muted-foreground">{note}</p>
      ) : null}
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">
          Momentum multiplier and its effect relative to the 1.00 baseline
        </caption>
        <DiffHead />
        <tbody>
          <DiffRow
            label="Momentum multiplier"
            before={formatMultiplier(1)}
            after={formatMultiplier(momentum.value)}
            diff={formatSignedMultiplierDelta(momentum.value)}
          />
        </tbody>
      </table>
    </DriverCard>
  );
}

/** One macro modifier row's label and multiplier key. */
const MACRO_ROWS: {
  key: keyof NonNullable<AdvancedDriversExplanation["macro_modifiers"]>;
  label: string;
}[] = [
  { key: "source_ip_multiplier", label: "Source IP provenance" },
  { key: "release_window_multiplier", label: "Release window halo" },
  { key: "calendar_seasonality_multiplier", label: "Calendar seasonality" },
  { key: "vernacular_tam_multiplier", label: "Vernacular TAM" },
];

function MacroModifiersCard({
  macro,
}: {
  macro: NonNullable<AdvancedDriversExplanation["macro_modifiers"]>;
}) {
  return (
    <DriverCard
      title="Macro modifiers"
      summary={`${formatMultiplier(macro.product)} combined`}
    >
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">
          Market multipliers and their signed effect relative to the 1.00 baseline
        </caption>
        <DiffHead />
        <tbody>
          {MACRO_ROWS.map(({ key, label }) => (
            <DiffRow
              key={key}
              label={label}
              before={formatMultiplier(1)}
              after={formatMultiplier(macro[key] as number | string | null)}
              diff={formatSignedMultiplierDelta(
                macro[key] as number | string | null,
              )}
            />
          ))}
          <tr className="border-b last:border-b-0">
            <th
              scope="row"
              className="py-1.5 pr-3 text-left font-medium text-foreground"
            >
              Combined
            </th>
            <td className="py-1.5 text-right tabular-nums text-muted-foreground">
              {formatMultiplier(1)}
            </td>
            <td className="py-1.5 text-right font-medium tabular-nums">
              {formatMultiplier(macro.product)}
            </td>
            <td className="py-1.5 text-right font-medium tabular-nums">
              {formatSignedMultiplierDelta(macro.product)}
            </td>
          </tr>
        </tbody>
      </table>
    </DriverCard>
  );
}

export interface AdvancedDriversBreakdownProps {
  advancedDrivers: AdvancedDriversExplanation | null | undefined;
}

export function AdvancedDriversBreakdown({
  advancedDrivers,
}: AdvancedDriversBreakdownProps) {
  // Flags off / pre-feature -> no advanced_drivers block -> render nothing (R6.5, R7.2).
  if (advancedDrivers === null || advancedDrivers === undefined) {
    return null;
  }

  const { comps, lineage, momentum, macro_modifiers } = advancedDrivers;
  const cards = [
    comps ? <CompsCard key="comps" comps={comps} /> : null,
    lineage ? <LineageCard key="lineage" lineage={lineage} /> : null,
    momentum ? <MomentumCard key="momentum" momentum={momentum} /> : null,
    macro_modifiers ? (
      <MacroModifiersCard key="macro_modifiers" macro={macro_modifiers} />
    ) : null,
  ].filter(Boolean);

  // Every driver absent (empty block) -> render nothing extra.
  if (cards.length === 0) {
    return null;
  }

  return (
    <section
      aria-labelledby="advanced-drivers-breakdown-heading"
      className="mt-4"
    >
      <h3
        id="advanced-drivers-breakdown-heading"
        className="text-xs font-semibold uppercase tracking-wide text-muted-foreground"
      >
        Advanced content drivers
      </h3>
      {cards}
    </section>
  );
}
