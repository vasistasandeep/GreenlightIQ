import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { ExplanationPanel } from "./explanation-panel";
import type { Explanation, GuardrailCheck } from "@/lib/types";

/**
 * ExplanationPanel component tests (R30.4).
 *
 * The panel is the explainability surface: every guardrail check with its
 * pass/breach status (R30.1), computed value vs threshold and the shortfall for
 * breaches (R30.2), and the dominant contributing factor (R30.3). An
 * unclassifiable breach is flagged (R8.4). We assert the table rows, the
 * dominant-factor marker, the shortfall cells, and the unclassifiable warning.
 */

function check(overrides: Partial<GuardrailCheck>): GuardrailCheck {
  return {
    name: "CPVH",
    computed_value: 0.042,
    threshold: 0.05,
    passed: true,
    breached: false,
    shortfall_magnitude: null,
    correctable: null,
    ...overrides,
  };
}

/** Locate the explanation table row whose row-header starts with `label`. */
function rowFor(label: string): HTMLElement {
  const rowHeader = screen.getByRole("rowheader", {
    name: new RegExp(label),
  });
  return rowHeader.closest("tr") as HTMLElement;
}

describe("ExplanationPanel (R30.4)", () => {
  it("renders the panel heading", () => {
    render(
      <ExplanationPanel
        explanation={{ checks: [check({})], dominant_factor: null, unclassifiable: false }}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "Why this recommendation" }),
    ).toBeInTheDocument();
  });

  it("renders one row per guardrail check with pass/breach status (R30.1)", () => {
    const explanation: Explanation = {
      checks: [
        check({ name: "CPVH", passed: true, breached: false }),
        check({
          name: "LTV_TO_COST",
          computed_value: 1.2,
          threshold: 2.5,
          passed: false,
          breached: true,
          shortfall_magnitude: 1.3,
          correctable: true,
        }),
      ],
      dominant_factor: "LTV_TO_COST",
      unclassifiable: false,
    };
    render(<ExplanationPanel explanation={explanation} />);

    const cpvhRow = rowFor("CPVH ceiling");
    expect(within(cpvhRow).getByText("Passed")).toBeInTheDocument();

    const ltvRow = rowFor("LTV-to-cost multiple");
    expect(within(ltvRow).getByText("Breached")).toBeInTheDocument();
  });

  it("shows the computed value, threshold, and shortfall for a breach (R30.2)", () => {
    const explanation: Explanation = {
      checks: [
        check({
          name: "LTV_TO_COST",
          computed_value: 1.2,
          threshold: 2.5,
          passed: false,
          breached: true,
          shortfall_magnitude: 1.3,
          correctable: true,
        }),
      ],
      dominant_factor: "LTV_TO_COST",
      unclassifiable: false,
    };
    render(<ExplanationPanel explanation={explanation} />);
    const row = rowFor("LTV-to-cost multiple");
    expect(within(row).getByText("1.20")).toBeInTheDocument(); // computed
    expect(within(row).getByText("2.50")).toBeInTheDocument(); // threshold
    expect(within(row).getByText("1.30")).toBeInTheDocument(); // shortfall
  });

  it("renders an em dash in the shortfall cell for a passed check", () => {
    render(
      <ExplanationPanel
        explanation={{
          checks: [check({ name: "CPVH", passed: true, breached: false })],
          dominant_factor: null,
          unclassifiable: false,
        }}
      />,
    );
    const row = rowFor("CPVH ceiling");
    const cells = within(row).getAllByRole("cell");
    expect(cells.at(-1)).toHaveTextContent("—");
  });

  it("names the dominant factor and marks its row (R30.3)", () => {
    const explanation: Explanation = {
      checks: [
        check({ name: "CPVH", passed: true, breached: false }),
        check({
          name: "PAYBACK_HORIZON",
          passed: false,
          breached: true,
          shortfall_magnitude: 5,
          correctable: true,
        }),
      ],
      dominant_factor: "PAYBACK_HORIZON",
      unclassifiable: false,
    };
    render(<ExplanationPanel explanation={explanation} />);
    expect(screen.getByText("Dominant factor:")).toBeInTheDocument();
    const dominantRow = rowFor("Payback horizon");
    expect(within(dominantRow).getByText("Dominant")).toBeInTheDocument();
  });

  it("reports that all checks passed when there is no dominant factor", () => {
    render(
      <ExplanationPanel
        explanation={{
          checks: [check({ name: "CPVH", passed: true, breached: false })],
          dominant_factor: null,
          unclassifiable: false,
        }}
      />,
    );
    expect(
      screen.getByText(/None — all checks passed/),
    ).toBeInTheDocument();
  });

  it("flags an unclassifiable breach with a caution message (R8.4)", () => {
    render(
      <ExplanationPanel
        explanation={{
          checks: [
            check({ name: "CPVH", passed: false, breached: true, correctable: null }),
          ],
          dominant_factor: "CPVH",
          unclassifiable: true,
        }}
      />,
    );
    expect(
      screen.getByText(/A breach could not be classified/i),
    ).toBeInTheDocument();
  });

  it("shows the empty-state message when there is no explanation", () => {
    render(<ExplanationPanel explanation={null} />);
    expect(
      screen.getByText(/No recommendation explanation is available/i),
    ).toBeInTheDocument();
  });

  it("shows the empty-state message when the explanation has no checks", () => {
    render(
      <ExplanationPanel
        explanation={{ checks: [], dominant_factor: null, unclassifiable: false }}
      />,
    );
    expect(
      screen.getByText(/No recommendation explanation is available/i),
    ).toBeInTheDocument();
  });
});
