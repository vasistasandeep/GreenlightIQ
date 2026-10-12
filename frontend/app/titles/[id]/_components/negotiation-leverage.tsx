/**
 * NegotiationLeverage (R15.3).
 *
 * Surfaces the contractual safeguards and negotiation levers a buyer can press on.
 * The valuation scorecard exposes the recommendation explanation, whose breached-
 * but-correctable guardrail checks are exactly the renegotiable levers (acquisition
 * cost / terms that can bring the deal inside its guardrails). Each lever lists the
 * check, how far it is from the threshold, and the recommended contractual safeguard.
 *
 * This is a presentational, server-renderable component (no interactivity).
 */

import type { Explanation, GuardrailCheck } from "@/lib/types";
import { formatNumber, guardrailLabel, toNumber } from "./format";

/** The contractual safeguard recommended for each correctable guardrail lever. */
const SAFEGUARD_BY_CHECK: Record<string, string> = {
  CPVH: "Renegotiate acquisition cost or secure additional licensed windows to pull CPVH under its ceiling.",
  LTV_TO_COST:
    "Negotiate a lower upfront fee or performance-based step-downs to lift the LTV-to-cost multiple.",
  CHURN_MITIGATION:
    "Add exclusivity or holdback clauses that protect the title's churn-mitigation value.",
  PAYBACK_HORIZON:
    "Restructure the milestone payment schedule to shorten the payback horizon.",
};

interface Lever {
  check: GuardrailCheck;
  safeguard: string;
}

function buildLevers(explanation: Explanation | null): Lever[] {
  if (!explanation) {
    return [];
  }
  return explanation.checks
    .filter((c) => c.breached && c.correctable === true)
    .map((check) => ({
      check,
      safeguard:
        SAFEGUARD_BY_CHECK[check.name] ??
        "Negotiate contractual terms to bring this check within its threshold.",
    }));
}

export interface NegotiationLeverageProps {
  explanation: Explanation | null;
}

export function NegotiationLeverage({ explanation }: NegotiationLeverageProps) {
  const levers = buildLevers(explanation);

  return (
    <section
      aria-labelledby="negotiation-leverage-heading"
      className="rounded-lg border bg-background p-5 shadow-sm"
    >
      <h2 id="negotiation-leverage-heading" className="mb-3 text-lg font-semibold">
        Negotiation leverage
      </h2>

      {levers.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No correctable guardrail breaches — there are no outstanding contractual
          levers to renegotiate for this title.
        </p>
      ) : (
        <ul className="space-y-3">
          {levers.map((lever) => {
            const shortfall = toNumber(lever.check.shortfall_magnitude);
            return (
              <li
                key={lever.check.name}
                className="rounded-md border border-amber-200 bg-amber-50 p-3"
              >
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-medium text-amber-900">
                    {guardrailLabel(lever.check.name)}
                  </span>
                  {shortfall !== null ? (
                    <span className="whitespace-nowrap text-xs text-amber-800">
                      Shortfall {formatNumber(shortfall)}
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 text-sm text-amber-900/90">{lever.safeguard}</p>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
