"use client";

/**
 * FinancialAccordion (R15.2).
 *
 * A disclosure accordion for the title's financial breakdown with three sections:
 *   1. CPVH ceiling checks — the computed CPVH against its ceiling threshold,
 *      sourced from the `CPVH` guardrail check in the explanation.
 *   2. Churn mitigation impact curve — the projected churn-reduction effect.
 *   3. Payback timeline — the {@link PaybackTimeline} bar chart.
 *
 * Built on native `<details>`/`<summary>` for accessible, keyboard-operable
 * disclosure without pulling in a Radix accordion the project does not yet vend.
 */

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Explanation, ValuationScorecard } from "@/lib/types";
import { PaybackTimeline } from "./payback-timeline";
import {
  formatMultiple,
  formatNumber,
  formatPercent,
  formatUsd,
  toNumber,
} from "./format";

function findCheck(explanation: Explanation | null, name: string) {
  return explanation?.checks?.find((c) => c.name === name) ?? null;
}

interface AccordionSectionProps {
  title: string;
  summary: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

function AccordionSection({
  title,
  summary,
  defaultOpen,
  children,
}: AccordionSectionProps) {
  return (
    <details open={defaultOpen} className="group border-b last:border-b-0">
      <summary className="flex cursor-pointer list-none items-center justify-between py-3 font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span>{title}</span>
        <span className="text-xs font-normal text-muted-foreground group-open:hidden">
          {summary}
        </span>
        <span
          aria-hidden="true"
          className="ml-3 text-muted-foreground transition-transform group-open:rotate-180"
        >
          ▾
        </span>
      </summary>
      <div className="pb-4">{children}</div>
    </details>
  );
}

/** Project a simple churn-mitigation impact curve from the reduction percentage. */
function buildChurnCurve(reductionPct: number | null) {
  if (reductionPct === null) {
    return [];
  }
  // Fraction vs percent: values <= 1 are fractions.
  const target = Math.abs(reductionPct) <= 1 ? reductionPct * 100 : reductionPct;
  // Ease the mitigation effect in over 6 months toward the steady-state target.
  return Array.from({ length: 7 }, (_, month) => ({
    month,
    reduction: Number((target * (1 - Math.exp(-month / 2))).toFixed(2)),
  }));
}

export interface FinancialAccordionProps {
  scorecard: ValuationScorecard;
}

export function FinancialAccordion({ scorecard }: FinancialAccordionProps) {
  const cpvhCheck = findCheck(scorecard.explanation, "CPVH");
  const ltvCheck = findCheck(scorecard.explanation, "LTV_TO_COST");
  const churnPct = toNumber(scorecard.churn_reduction_pct);
  const churnCurve = buildChurnCurve(churnPct);

  return (
    <section
      aria-labelledby="financial-accordion-heading"
      className="rounded-lg border bg-background p-5 shadow-sm"
    >
      <h2 id="financial-accordion-heading" className="mb-2 text-lg font-semibold">
        Financial breakdown
      </h2>

      <div className="divide-y">
        <AccordionSection
          title="CPVH ceiling checks"
          summary={cpvhCheck?.passed ? "Within ceiling" : "Review"}
          defaultOpen
        >
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-muted-foreground">Computed CPVH</dt>
              <dd className="font-medium tabular-nums">
                {formatNumber(scorecard.calculated_cpvh)}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Ceiling threshold</dt>
              <dd className="font-medium tabular-nums">
                {formatNumber(cpvhCheck?.threshold ?? null)}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Status</dt>
              <dd
                className={
                  cpvhCheck == null
                    ? "font-medium text-muted-foreground"
                    : cpvhCheck.passed
                      ? "font-medium text-emerald-700"
                      : "font-medium text-red-700"
                }
              >
                {cpvhCheck == null
                  ? "—"
                  : cpvhCheck.passed
                    ? "Passed"
                    : "Breached"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">LTV-to-cost multiple</dt>
              <dd className="font-medium tabular-nums">
                {formatMultiple(scorecard.ltv_to_cost_multiple)}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">LTV threshold</dt>
              <dd className="font-medium tabular-nums">
                {formatNumber(ltvCheck?.threshold ?? null)}
              </dd>
            </div>
          </dl>

          {scorecard.ltv_attribution ? (
            <div className="mt-4 rounded-md border bg-muted/30 p-3">
              <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                LTV-to-cost attribution
              </p>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-muted-foreground">SVOD subscription value</dt>
                  <dd className="font-medium tabular-nums">
                    {formatUsd(scorecard.ltv_attribution.subscription_value)}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">AVOD ad-yield value</dt>
                  <dd className="font-medium tabular-nums">
                    {formatUsd(scorecard.ltv_attribution.advertising_value)}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Total modeled value</dt>
                  <dd className="font-medium tabular-nums">
                    {formatUsd(scorecard.ltv_attribution.total_modeled_value)}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Normalized cost</dt>
                  <dd className="font-medium tabular-nums">
                    {formatUsd(scorecard.ltv_attribution.normalized_cost_usd)}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Multiple</dt>
                  <dd className="font-medium tabular-nums">
                    {formatMultiple(scorecard.ltv_attribution.multiple)}
                  </dd>
                </div>
              </dl>
            </div>
          ) : null}
        </AccordionSection>

        <AccordionSection
          title="Churn mitigation impact"
          summary={churnPct !== null ? formatPercent(scorecard.churn_reduction_pct) : "—"}
        >
          {churnCurve.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No churn-reduction projection is available for this title.
            </p>
          ) : (
            <div
              className="h-48 w-full"
              role="img"
              aria-label="Churn mitigation impact curve"
            >
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={churnCurve} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis
                    dataKey="month"
                    tick={{ fontSize: 11 }}
                    label={{ value: "Month", position: "insideBottom", offset: -2, fontSize: 11 }}
                  />
                  <YAxis
                    tick={{ fontSize: 11 }}
                    width={44}
                    tickFormatter={(v: number) => `${v}%`}
                  />
                  <Tooltip
                    formatter={(value: number | string) =>
                      [`${Number(value).toFixed(2)}%`, "Churn reduction"] as [
                        string,
                        string,
                      ]
                    }
                    labelFormatter={(label) => `Month ${label}`}
                  />
                  <Area
                    type="monotone"
                    dataKey="reduction"
                    stroke="hsl(222.2 47.4% 11.2%)"
                    fill="hsl(222.2 47.4% 11.2%)"
                    fillOpacity={0.2}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
          {scorecard.churn_cohort &&
          toNumber(scorecard.churn_cohort.retained_subscribers) !== null ? (
            <p className="mt-3 text-sm text-muted-foreground">
              Approx.{" "}
              <span className="font-semibold text-foreground tabular-nums">
                {new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(
                  Math.round(toNumber(scorecard.churn_cohort.retained_subscribers)!),
                )}
              </span>{" "}
              retained subscribers
              {scorecard.churn_cohort.derived ? (
                <span className="text-xs"> (modeled estimate)</span>
              ) : null}
            </p>
          ) : null}
        </AccordionSection>

        <AccordionSection
          title="Payback timeline"
          summary={
            scorecard.payback_horizon_months !== null
              ? `${scorecard.payback_horizon_months} mo`
              : "—"
          }
        >
          <PaybackTimeline
            paybackHorizonMonths={scorecard.payback_horizon_months}
            normalizedCostUsd={scorecard.normalized_cost_usd}
          />
        </AccordionSection>
      </div>
    </section>
  );
}
