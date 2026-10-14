/**
 * NegotiationLeverage (R15.3, Deal Decision Support R9).
 *
 * Surfaces the Negotiation Playbook for a NEGOTIATE_HARD / PASS title: the target
 * purchase ceiling and implied discount versus the current ask, plus one
 * plain-language counter-proposal lever per breached guardrail. The server
 * supplies the levers (preferred); when absent we fall back to deriving them from
 * the explanation's correctable breaches. The ceiling/discount are omitted for a
 * GREENLIGHT.
 *
 * Presentational, server-renderable (no interactivity). Decimal values arrive as
 * JSON strings and are coerced with `toNumber` before formatting.
 */

import type {
  CounterProposalLever,
  Explanation,
  ValuationScorecard,
} from "@/lib/types";
import { formatPercent, formatUsd, guardrailLabel, toNumber } from "./format";

/** Fallback safeguard text per guardrail when the server sends no levers. */
const SAFEGUARD_BY_CHECK: Record<string, string> = {
  CPVH: "Renegotiate acquisition cost or secure additional licensed windows to pull CPVH under its ceiling.",
  LTV_TO_COST:
    "Negotiate a lower upfront fee or performance-based step-downs to lift the LTV-to-cost multiple.",
  CHURN_MITIGATION:
    "Add exclusivity or holdback clauses that protect the title's churn-mitigation value.",
  PAYBACK_HORIZON:
    "Restructure the milestone payment schedule to shorten the payback horizon.",
};

/** Derive levers from the explanation when the server did not supply them. */
function fallbackLevers(explanation: Explanation | null): CounterProposalLever[] {
  if (!explanation || !explanation.checks) {
    return [];
  }
  return explanation.checks
    .filter((c) => c.breached)
    .map((c) => ({
      name: c.name,
      correctable: c.correctable,
      message:
        SAFEGUARD_BY_CHECK[c.name] ??
        "Negotiate contractual terms to bring this check within its threshold.",
    }));
}

export interface NegotiationLeverageProps {
  scorecard: Pick<
    ValuationScorecard,
    | "explanation"
    | "recommendation_status"
    | "target_purchase_ceiling_usd"
    | "implied_discount_pct"
    | "counter_proposal_levers"
  >;
}

export function NegotiationLeverage({ scorecard }: NegotiationLeverageProps) {
  const serverLevers = scorecard.counter_proposal_levers ?? [];
  const levers =
    serverLevers.length > 0 ? serverLevers : fallbackLevers(scorecard.explanation);

  const isGreenlight = scorecard.recommendation_status === "GREENLIGHT";
  const ceiling = toNumber(scorecard.target_purchase_ceiling_usd);
  const showCeiling = !isGreenlight && ceiling !== null;

  return (
    <section
      aria-labelledby="negotiation-leverage-heading"
      className="rounded-lg border bg-background p-5 shadow-sm"
    >
      <h2 id="negotiation-leverage-heading" className="mb-3 text-lg font-semibold">
        Negotiation playbook
      </h2>

      {showCeiling ? (
        <div className="mb-4 rounded-md border border-emerald-800/40 bg-emerald-950/30 p-3">
          <p className="text-sm text-slate-300">
            Target purchase ceiling:{" "}
            <span className="font-semibold text-emerald-300">
              {formatUsd(scorecard.target_purchase_ceiling_usd)}
            </span>
          </p>
          <p className="mt-1 text-sm text-slate-400">
            Implied discount vs. current ask:{" "}
            <span className="font-medium text-slate-200">
              {formatPercent(scorecard.implied_discount_pct)}
            </span>
          </p>
        </div>
      ) : null}

      {levers.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No correctable guardrail breaches - there are no outstanding contractual
          levers to renegotiate for this title.
        </p>
      ) : (
        <ul className="space-y-3">
          {levers.map((lever) => (
            <li
              key={lever.name}
              className="rounded-md border border-amber-200 bg-amber-50 p-3"
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-medium text-amber-900">
                  {guardrailLabel(lever.name)}
                </span>
                <span className="whitespace-nowrap text-xs text-amber-800">
                  {lever.correctable === true ? "Correctable" : "Structural"}
                </span>
              </div>
              <p className="mt-1 text-sm text-amber-900/90">{lever.message}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}