"use client";

import { CheckCircle2, XCircle } from "lucide-react";

import { cn } from "@/lib/utils";
import type { GuardrailCheck, QuickEvaluateResponse } from "@/lib/types";
import { AdvancedDriversBreakdown } from "@/app/titles/[id]/_components/advanced-drivers-breakdown";
import { ChurnBreakdown } from "@/app/titles/[id]/_components/churn-breakdown";
import { ContentEvalBreakdown } from "@/app/titles/[id]/_components/content-eval-breakdown";
import { StudioPayback } from "./studio-payback";
import { StudioRadar } from "./studio-radar";
import {
  decimals,
  guardrailLabel,
  multiple,
  num,
  pct,
  subscribers,
  usd,
} from "./helpers";

const BANNER: Record<string, { label: string; cls: string }> = {
  GREENLIGHT: {
    label: "GREENLIGHT",
    cls: "bg-gradient-to-r from-emerald-500 to-emerald-400 text-emerald-950 shadow-lg shadow-emerald-500/20",
  },
  NEGOTIATE_HARD: {
    label: "NEGOTIATE HARD",
    cls: "bg-gradient-to-r from-amber-500 to-amber-400 text-amber-950 shadow-lg shadow-amber-500/20",
  },
  PASS: {
    label: "PASS",
    cls: "bg-gradient-to-r from-rose-500 to-rose-400 text-rose-950 shadow-lg shadow-rose-500/20",
  },
};

function Panel({
  title,
  children,
  className,
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "rounded-xl border border-slate-800 bg-slate-900/60 p-5",
        className,
      )}
    >
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
        {title}
      </h3>
      {children}
    </section>
  );
}

function CheckRow({ check }: { check: GuardrailCheck }) {
  const passed = check.passed;
  const detail = (() => {
    switch (check.name) {
      case "CPVH":
        return num(check.computed_value) !== null
          ? `$${decimals(check.computed_value)}/hr vs $${decimals(check.threshold)} ceiling`
          : "Not computable (0 viewing hours)";
      case "LTV_TO_COST":
        return `${multiple(check.computed_value)} (Hurdle: ${multiple(check.threshold)})`;
      case "CHURN_MITIGATION":
        return `${pct(check.computed_value)} (Threshold: ${pct(check.threshold)})`;
      case "PAYBACK_HORIZON":
        return `${num(check.computed_value) ?? "â€”"} Months (Target: 9-12)`;
      default:
        return "";
    }
  })();

  return (
    <div className="flex items-center justify-between gap-3 border-b border-slate-800 py-2.5 last:border-b-0">
      <div className="flex items-center gap-2.5">
        {passed ? (
          <CheckCircle2 className="h-5 w-5 text-emerald-400" aria-hidden />
        ) : (
          <XCircle className="h-5 w-5 text-rose-400" aria-hidden />
        )}
        <span className="font-medium text-slate-100">
          {guardrailLabel(check.name)}
        </span>
      </div>
      <span className="text-right text-sm text-slate-400">
        <span
          className={cn(
            "mr-2 font-semibold",
            passed ? "text-emerald-400" : "text-rose-400",
          )}
        >
          {passed ? "PASS" : "BREACH"}
        </span>
        {detail}
      </span>
    </div>
  );
}

export function ValuationReport({ result }: { result: QuickEvaluateResponse }) {
  const banner = BANNER[result.recommendation_status] ?? {
    label: result.recommendation_status,
    cls: "bg-slate-600 text-slate-50",
  };

  return (
    <div className="flex flex-col gap-5">
      {/* Recommendation banner */}
      <div
        className={cn(
          "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl px-6 py-4 text-xl font-bold",
          banner.cls,
        )}
      >
        <span>[ {banner.label} ]</span>
        {result.recommendation_status !== "GREENLIGHT" &&
        num(result.target_purchase_ceiling_usd) !== null ? (
          <span className="text-base font-semibold">
            &bull; Target Purchase Ceiling: {usd(result.target_purchase_ceiling_usd)}
            {num(result.implied_discount_pct) !== null ? (
              <> &bull; Discount: {pct(result.implied_discount_pct)}</>
            ) : null}
          </span>
        ) : null}
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Four quantitative checks */}
        <Panel title="Four Quantitative Checks">
          <div className="flex flex-col">
            {(result.explanation?.checks ?? []).map((c) => (
              <CheckRow key={c.name} check={c} />
            ))}
          </div>
        </Panel>

        {/* Explainability + governance */}
        <div className="flex flex-col gap-5">
          <Panel title="Explainability">
            <p className="text-sm text-slate-300">
              <span className="text-slate-500">Dominant Factor: </span>
              {result.explanation.dominant_factor
                ? guardrailLabel(result.explanation.dominant_factor)
                : "All checks passed - no breach drives the outcome."}
            </p>
            {result.explanation.unclassifiable ? (
              <p className="mt-2 text-sm text-rose-400">
                A breach could not be classified; treat with caution.
              </p>
            ) : null}
            <div className="text-slate-300">
              <ChurnBreakdown churnModel={result.explanation?.churn_model} />
              <ContentEvalBreakdown
                contentEval={result.explanation?.content_eval}
              />
              <AdvancedDriversBreakdown
                advancedDrivers={result.explanation?.advanced_drivers}
              />
            </div>
          </Panel>

          <Panel title="Governance">
            {result.governance.required ? (
              <ul className="space-y-1.5 text-sm">
                {result.governance.required_roles.map((r) => (
                  <li key={r} className="flex items-center justify-between">
                    <span className="text-slate-300">{r.replace(/_/g, " ")}</span>
                    <span className="font-semibold text-amber-400">PENDING</span>
                  </li>
                ))}
                <li className="pt-1 text-xs text-slate-500">
                  {result.governance.note}
                </li>
              </ul>
            ) : (
              <p className="text-sm text-emerald-400">
                {result.governance.note}
              </p>
            )}
          </Panel>
        </div>

        {/* Metadata radar */}
        <Panel title="Metadata Vector Profile">
          <StudioRadar profile={result.metadata_profile} />
          <p className="mt-1 text-center text-[11px] text-slate-500">
            Derived profile (demo embedding) - 0 to 10 scale
          </p>
        </Panel>

        {/* Cumulative payback projection */}
        <Panel title="Cumulative Payback Projection">
          <StudioPayback
            normalizedCostUsd={result.normalized_cost_usd}
            paybackMonths={result.payback_horizon_months}
          />
          {result.payback_horizon_months ? (
            <p className="mt-1 text-center text-[11px] text-slate-500">
              Break-Even: Month {result.payback_horizon_months}
            </p>
          ) : null}
        </Panel>

        {/* LTV-to-Cost attribution */}
        {result.ltv_attribution ? (
          <Panel title="LTV-to-Cost Attribution">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
              <dt className="text-slate-400">SVOD subscription value</dt>
              <dd className="text-right font-semibold text-slate-200">
                {usd(result.ltv_attribution.subscription_value)}
              </dd>
              <dt className="text-slate-400">AVOD ad-yield value</dt>
              <dd className="text-right font-semibold text-slate-200">
                {usd(result.ltv_attribution.advertising_value)}
              </dd>
              <dt className="text-slate-400">Total modeled value</dt>
              <dd className="text-right font-semibold text-slate-200">
                {usd(result.ltv_attribution.total_modeled_value)}
              </dd>
              <dt className="text-slate-400">Normalized cost</dt>
              <dd className="text-right font-semibold text-slate-200">
                {usd(result.ltv_attribution.normalized_cost_usd)}
              </dd>
              <dt className="text-slate-400">Multiple</dt>
              <dd className="text-right font-semibold text-emerald-300">
                {multiple(result.ltv_attribution.multiple)}
              </dd>
            </dl>
          </Panel>
        ) : null}

        {/* Negotiation playbook: counter-proposal levers + retained subscribers */}
        {result.recommendation_status !== "GREENLIGHT" &&
        (result.counter_proposal_levers?.length ||
          num(result.churn_cohort?.retained_subscribers) !== null) ? (
          <Panel title="Negotiation Playbook">
            {result.churn_cohort &&
            num(result.churn_cohort.retained_subscribers) !== null ? (
              <p className="mb-3 text-sm text-slate-300">
                Approx.{" "}
                <span className="font-semibold text-slate-100">
                  {subscribers(result.churn_cohort.retained_subscribers)}
                </span>{" "}
                retained subscribers
                {result.churn_cohort.derived ? (
                  <span className="text-[11px] text-slate-500"> (modeled estimate)</span>
                ) : null}
              </p>
            ) : null}
            {result.counter_proposal_levers?.length ? (
              <ul className="space-y-2">
                {result.counter_proposal_levers.map((lv) => (
                  <li
                    key={lv.name}
                    className="rounded-md border border-amber-500/30 bg-amber-500/10 p-2.5 text-sm"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-amber-200">
                        {guardrailLabel(lv.name)}
                      </span>
                      <span className="text-[11px] uppercase text-amber-400/80">
                        {lv.correctable === true ? "Correctable" : "Structural"}
                      </span>
                    </div>
                    <p className="mt-1 text-slate-300">{lv.message}</p>
                  </li>
                ))}
              </ul>
            ) : null}
          </Panel>
        ) : null}
      </div>
    </div>
  );
}