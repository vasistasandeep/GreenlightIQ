import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { GreenlightMemo } from "./greenlight-memo";
import type { Explanation, ValuationScorecard } from "@/lib/types";

/**
 * GreenlightMemo tests (Deal Decision Support - Investment Committee one-pager).
 *
 * The memo composes the financial summary, guardrail checks, negotiation
 * playbook (for non-GREENLIGHT), and sign-off block into a printable brief.
 */

function explanation(): Explanation {
  return {
    checks: [
      {
        name: "CPVH",
        computed_value: "0.25",
        threshold: "0.18",
        passed: false,
        breached: true,
        shortfall_magnitude: "0.07",
        correctable: true,
      },
    ],
    dominant_factor: "CPVH",
    unclassifiable: false,
  };
}

function scorecard(overrides: Partial<ValuationScorecard> = {}): ValuationScorecard {
  return {
    title_id: "t-1",
    calculated_cpvh: "0.25",
    ltv_to_cost_multiple: "3.7",
    churn_reduction_pct: "2.0",
    payback_horizon_months: 14,
    recommendation_status: "NEGOTIATE_HARD",
    normalized_cost_usd: "5000000",
    model_version_id: "mv-1",
    explanation: explanation(),
    metadata_breakdown: null,
    target_purchase_ceiling_usd: "180000",
    implied_discount_pct: "96.4",
    counter_proposal_levers: [
      { name: "CPVH", correctable: true, message: "Renegotiate the acquisition cost." },
    ],
    ltv_attribution: null,
    churn_cohort: null,
    ...overrides,
  };
}

describe("GreenlightMemo", () => {
  it("renders the memo heading and the recommendation", () => {
    render(<GreenlightMemo titleId="t-1" scorecard={scorecard()} />);
    expect(screen.getByText("Greenlight Memo")).toBeInTheDocument();
    expect(screen.getByText(/NEGOTIATE HARD/)).toBeInTheDocument();
  });

  it("renders the guardrail checks and sign-off block", () => {
    render(<GreenlightMemo titleId="t-1" scorecard={scorecard()} />);
    expect(screen.getByText("Guardrail Checks")).toBeInTheDocument();
    expect(screen.getByText("Executive Sign-Off")).toBeInTheDocument();
    expect(screen.getByText("Chief Content Officer")).toBeInTheDocument();
    expect(screen.getByText("Chief Financial Officer")).toBeInTheDocument();
  });

  it("includes the negotiation playbook for a non-GREENLIGHT title", () => {
    render(<GreenlightMemo titleId="t-1" scorecard={scorecard()} />);
    expect(screen.getByText("Negotiation Playbook")).toBeInTheDocument();
    expect(screen.getByText(/\$180,000/)).toBeInTheDocument();
    expect(screen.getByText(/Renegotiate the acquisition cost/)).toBeInTheDocument();
  });

  it("omits the playbook for a GREENLIGHT title", () => {
    render(
      <GreenlightMemo
        titleId="t-1"
        scorecard={scorecard({
          recommendation_status: "GREENLIGHT",
          target_purchase_ceiling_usd: null,
        })}
      />,
    );
    expect(screen.queryByText("Negotiation Playbook")).not.toBeInTheDocument();
  });
});