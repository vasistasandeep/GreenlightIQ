import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/**
 * FinancialAccordion + PaybackTimeline component tests (R15.2).
 *
 * Recharts is mocked (see metadata-radar.test.tsx for the rationale): the
 * ResponsiveContainer-based charts cannot measure themselves under jsdom, so we
 * substitute pass-through elements and assert on the component's own projections
 * (`buildPaybackSeries`, the churn curve) and the accessible accordion markup.
 */

vi.mock("recharts", () => {
  const Passthrough = ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  );
  const Leaf = () => null;
  return {
    ResponsiveContainer: Passthrough,
    BarChart: Passthrough,
    AreaChart: Passthrough,
    Bar: Leaf,
    Area: Leaf,
    CartesianGrid: Leaf,
    XAxis: Leaf,
    YAxis: Leaf,
    Tooltip: Leaf,
  };
});

import { FinancialAccordion } from "./financial-accordion";
import { PaybackTimeline, buildPaybackSeries } from "./payback-timeline";
import type { ValuationScorecard } from "@/lib/types";

function makeScorecard(
  overrides: Partial<ValuationScorecard> = {},
): ValuationScorecard {
  return {
    title_id: "t-1",
    calculated_cpvh: 0.042,
    ltv_to_cost_multiple: 3.1,
    churn_reduction_pct: 0.12,
    payback_horizon_months: 12,
    recommendation_status: "GREENLIGHT",
    normalized_cost_usd: 1_200_000,
    model_version_id: "mv-1",
    metadata_breakdown: null,
    explanation: {
      checks: [
        {
          name: "CPVH",
          computed_value: 0.042,
          threshold: 0.05,
          passed: true,
          breached: false,
          shortfall_magnitude: null,
          correctable: null,
        },
        {
          name: "LTV_TO_COST",
          computed_value: 3.1,
          threshold: 2.5,
          passed: true,
          breached: false,
          shortfall_magnitude: null,
          correctable: null,
        },
      ],
      dominant_factor: null,
      unclassifiable: false,
    },
    ...overrides,
  };
}

describe("buildPaybackSeries (R15.2)", () => {
  it("projects a linear cumulative-recovery curve across the horizon", () => {
    const series = buildPaybackSeries(4, 1000);
    expect(series).toEqual([
      { month: 1, recovered: 250 },
      { month: 2, recovered: 500 },
      { month: 3, recovered: 750 },
      { month: 4, recovered: 1000 },
    ]);
  });

  it("never recovers more than the normalized cost in the final month", () => {
    const series = buildPaybackSeries(3, 900);
    expect(series.at(-1)!.recovered).toBe(900);
  });

  it("caps the number of bars at 36 for very long horizons", () => {
    const series = buildPaybackSeries(60, 6000);
    expect(series).toHaveLength(36);
  });

  it("returns an empty series when the horizon or cost is unavailable", () => {
    expect(buildPaybackSeries(null, 1000)).toEqual([]);
    expect(buildPaybackSeries(0, 1000)).toEqual([]);
    expect(buildPaybackSeries(12, null)).toEqual([]);
  });
});

describe("PaybackTimeline (R15.2)", () => {
  it("renders the cost-recovery chart with an accessible label", () => {
    render(
      <PaybackTimeline paybackHorizonMonths={12} normalizedCostUsd={1_200_000} />,
    );
    expect(
      screen.getByRole("img", { name: "Cumulative cost-recovery timeline" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Projected linear recovery of/i),
    ).toHaveTextContent("across 12 months");
  });

  it("notes truncation when the horizon exceeds the bar cap", () => {
    render(
      <PaybackTimeline paybackHorizonMonths={48} normalizedCostUsd={4_800_000} />,
    );
    expect(screen.getByText(/Showing the first 36 months/)).toBeInTheDocument();
  });

  it("shows a fallback message when the horizon is not yet computed", () => {
    render(
      <PaybackTimeline paybackHorizonMonths={null} normalizedCostUsd={1_000_000} />,
    );
    expect(
      screen.getByText(/A payback timeline is not available/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

describe("FinancialAccordion (R15.2)", () => {
  it("renders the financial breakdown heading and all three sections", () => {
    render(<FinancialAccordion scorecard={makeScorecard()} />);
    expect(
      screen.getByRole("heading", { name: "Financial breakdown" }),
    ).toBeInTheDocument();
    expect(screen.getByText("CPVH ceiling checks")).toBeInTheDocument();
    expect(screen.getByText("Churn mitigation impact")).toBeInTheDocument();
    expect(screen.getByText("Payback timeline")).toBeInTheDocument();
  });

  it("surfaces the computed CPVH, ceiling threshold, and a passed status", () => {
    render(<FinancialAccordion scorecard={makeScorecard()} />);
    const cpvhSection = screen
      .getByText("CPVH ceiling checks")
      .closest("details")!;
    expect(within(cpvhSection).getByText("0.04")).toBeInTheDocument(); // computed CPVH
    expect(within(cpvhSection).getByText("0.05")).toBeInTheDocument(); // ceiling threshold
    expect(within(cpvhSection).getByText("Passed")).toBeInTheDocument();
    expect(within(cpvhSection).getByText("3.10×")).toBeInTheDocument(); // LTV multiple
  });

  it("marks the CPVH status as Breached when the check fails", () => {
    const scorecard = makeScorecard({
      explanation: {
        checks: [
          {
            name: "CPVH",
            computed_value: 0.09,
            threshold: 0.05,
            passed: false,
            breached: true,
            shortfall_magnitude: 0.04,
            correctable: true,
          },
        ],
        dominant_factor: "CPVH",
        unclassifiable: false,
      },
    });
    render(<FinancialAccordion scorecard={scorecard} />);
    const cpvhSection = screen
      .getByText("CPVH ceiling checks")
      .closest("details")!;
    expect(within(cpvhSection).getByText("Breached")).toBeInTheDocument();
  });

  it("renders the churn mitigation curve when a reduction percentage exists", async () => {
    const user = userEvent.setup();
    render(<FinancialAccordion scorecard={makeScorecard()} />);
    // Open the churn section (summary toggles the native <details>).
    await user.click(screen.getByText("Churn mitigation impact"));
    expect(
      screen.getByRole("img", { name: "Churn mitigation impact curve" }),
    ).toBeInTheDocument();
  });

  it("shows a churn fallback message when no reduction percentage is available", async () => {
    const user = userEvent.setup();
    render(
      <FinancialAccordion
        scorecard={makeScorecard({ churn_reduction_pct: null })}
      />,
    );
    await user.click(screen.getByText("Churn mitigation impact"));
    expect(
      screen.getByText(/No churn-reduction projection is available/i),
    ).toBeInTheDocument();
  });

  it("embeds the payback timeline chart for a computed horizon", () => {
    render(<FinancialAccordion scorecard={makeScorecard()} />);
    expect(
      screen.getByRole("img", { name: "Cumulative cost-recovery timeline" }),
    ).toBeInTheDocument();
  });
});
