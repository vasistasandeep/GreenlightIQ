import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { NegotiationLeverage } from "./negotiation-leverage";
import type { Explanation, GuardrailCheck } from "@/lib/types";

/**
 * NegotiationLeverage component tests (R15.3).
 *
 * The panel derives renegotiable levers from the explanation's breached-but-
 * correctable guardrail checks and recommends a contractual safeguard for each.
 * We assert that only correctable breaches become levers, that passed and
 * non-correctable checks are excluded, and that the shortfall + safeguard copy
 * is surfaced per lever.
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

describe("NegotiationLeverage (R15.3)", () => {
  it("renders the panel heading", () => {
    render(<NegotiationLeverage explanation={explanationWith([])} />);
    expect(
      screen.getByRole("heading", { name: "Negotiation leverage" }),
    ).toBeInTheDocument();
  });

  it("lists a lever with its safeguard and shortfall for a correctable breach", () => {
    render(
      <NegotiationLeverage
        explanation={explanationWith([
          check({ name: "CPVH", shortfall_magnitude: 0.04, correctable: true }),
        ])}
      />,
    );
    const item = screen.getByRole("listitem");
    expect(within(item).getByText("CPVH ceiling")).toBeInTheDocument();
    expect(within(item).getByText(/Shortfall 0.04/)).toBeInTheDocument();
    expect(
      within(item).getByText(/Renegotiate acquisition cost/i),
    ).toBeInTheDocument();
  });

  it("surfaces a lever for each distinct correctable guardrail", () => {
    render(
      <NegotiationLeverage
        explanation={explanationWith([
          check({ name: "CPVH", correctable: true }),
          check({ name: "LTV_TO_COST", correctable: true }),
          check({ name: "PAYBACK_HORIZON", correctable: true }),
        ])}
      />,
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("LTV-to-cost multiple")).toBeInTheDocument();
    expect(screen.getByText("Payback horizon")).toBeInTheDocument();
  });

  it("excludes passed checks and non-correctable breaches from the levers", () => {
    render(
      <NegotiationLeverage
        explanation={explanationWith([
          check({ name: "CPVH", passed: true, breached: false, correctable: null }),
          check({ name: "LTV_TO_COST", correctable: false }),
          check({ name: "CHURN_MITIGATION", correctable: null }),
        ])}
      />,
    );
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
    expect(
      screen.getByText(/No correctable guardrail breaches/i),
    ).toBeInTheDocument();
  });

  it("shows the empty-state message when there is no explanation", () => {
    render(<NegotiationLeverage explanation={null} />);
    expect(
      screen.getByText(/No correctable guardrail breaches/i),
    ).toBeInTheDocument();
  });

  it("omits the shortfall line when a lever has no shortfall magnitude", () => {
    render(
      <NegotiationLeverage
        explanation={explanationWith([
          check({ name: "CPVH", shortfall_magnitude: null, correctable: true }),
        ])}
      />,
    );
    const item = screen.getByRole("listitem");
    expect(within(item).queryByText(/Shortfall/)).not.toBeInTheDocument();
  });
});
