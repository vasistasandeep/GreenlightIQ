import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { NegotiationLeverage } from "./negotiation-leverage";
import type {
  CounterProposalLever,
  Explanation,
  GuardrailCheck,
  RecommendationStatus,
  ValuationScorecard,
} from "@/lib/types";

/**
 * NegotiationLeverage component tests (R15.3, Deal Decision Support R9).
 *
 * The panel renders the Negotiation Playbook: the target purchase ceiling and
 * implied discount for a NEGOTIATE_HARD/PASS title (omitted for GREENLIGHT), plus
 * one counter-proposal lever per breached guardrail (server-supplied, falling
 * back to explanation-derived). Decimal values arrive as strings and must coerce.
 */

function check(overrides: Partial<GuardrailCheck>): GuardrailCheck {
  return {
    name: "CPVH",
    computed_value: 0.09,
    threshold: 0.05,
    passed: false,
    breached: true,
    shortfall_magnitude: 0.04,
    correctable: true,
    ...overrides,
  };
}

function explanationWith(checks: GuardrailCheck[]): Explanation {
  return { checks, dominant_factor: null, unclassifiable: false };
}

function scorecard(
  overrides: Partial<ValuationScorecard> & {
    recommendation_status?: RecommendationStatus | null;
  } = {},
): ValuationScorecard {
  return {
    title_id: "t-1",
    calculated_cpvh: null,
    ltv_to_cost_multiple: null,
    churn_reduction_pct: null,
    payback_horizon_months: null,
    recommendation_status: "NEGOTIATE_HARD",
    normalized_cost_usd: null,
    model_version_id: null,
    explanation: explanationWith([]),
    metadata_breakdown: null,
    target_purchase_ceiling_usd: null,
    implied_discount_pct: null,
    counter_proposal_levers: [],
    ltv_attribution: null,
    churn_cohort: null,
    ...overrides,
  };
}

const CPVH_LEVER: CounterProposalLever = {
  name: "CPVH",
  correctable: true,
  message: "Renegotiate the acquisition cost down to the target purchase ceiling.",
};

describe("NegotiationLeverage (R15.3)", () => {
  it("renders the panel heading", () => {
    render(<NegotiationLeverage scorecard={scorecard()} />);
    expect(
      screen.getByRole("heading", { name: "Negotiation playbook" }),
    ).toBeInTheDocument();
  });

  it("shows the target ceiling and implied discount for a NEGOTIATE_HARD title (R9.1)", () => {
    render(
      <NegotiationLeverage
        scorecard={scorecard({
          recommendation_status: "NEGOTIATE_HARD",
          // Decimal-as-string from the wire; must coerce (R9.6).
          target_purchase_ceiling_usd: "890000",
          implied_discount_pct: "25.8",
        })}
      />,
    );
    expect(screen.getByText(/Target purchase ceiling/i)).toBeInTheDocument();
    expect(screen.getByText(/\$890,000/)).toBeInTheDocument();
    expect(screen.getByText(/25.8%/)).toBeInTheDocument();
  });

  it("omits the ceiling and discount for a GREENLIGHT (R9.5)", () => {
    render(
      <NegotiationLeverage
        scorecard={scorecard({
          recommendation_status: "GREENLIGHT",
          target_purchase_ceiling_usd: "890000",
          implied_discount_pct: "25.8",
        })}
      />,
    );
    expect(screen.queryByText(/Target purchase ceiling/i)).not.toBeInTheDocument();
  });

  it("renders server-supplied counter-proposal levers labeled by guardrail (R9.3)", () => {
    render(
      <NegotiationLeverage
        scorecard={scorecard({ counter_proposal_levers: [CPVH_LEVER] })}
      />,
    );
    const item = screen.getByRole("listitem");
    expect(within(item).getByText("CPVH ceiling")).toBeInTheDocument();
    expect(within(item).getByText(/Renegotiate the acquisition cost/i)).toBeInTheDocument();
    expect(within(item).getByText(/Correctable/i)).toBeInTheDocument();
  });

  it("falls back to explanation-derived levers when the server sends none", () => {
    render(
      <NegotiationLeverage
        scorecard={scorecard({
          counter_proposal_levers: [],
          explanation: explanationWith([
            check({ name: "LTV_TO_COST", correctable: true }),
          ]),
        })}
      />,
    );
    expect(screen.getByText("LTV-to-cost multiple")).toBeInTheDocument();
  });

  it("shows the empty-state when there are no levers", () => {
    render(<NegotiationLeverage scorecard={scorecard()} />);
    expect(
      screen.getByText(/No correctable guardrail breaches/i),
    ).toBeInTheDocument();
  });
});