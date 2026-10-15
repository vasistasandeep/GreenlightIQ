import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { KpiCards } from "@/components/dashboard/kpi-cards";
import type { DashboardKpis } from "@/lib/types";

/**
 * KpiCards component tests (R14.1).
 *
 * Verifies the four executive KPI header cards render with correctly
 * formatted figures and that `null` figures degrade to a dash placeholder
 * rather than a misleading zero.
 */

const FULL_KPIS: DashboardKpis = {
  active_pipeline_valuation_usd: 12_400_000,
  avg_ltv_to_cost: 3.2,
  portfolio_risk_exposure: 0.42,
  model_accuracy_rate: 0.87,
};

/** Locate the KPI card <div> that owns a given label. */
function cardByLabel(label: string): HTMLElement {
  const labelNode = screen.getByText(label);
  const card = labelNode.closest("[data-kpi-card]");
  expect(card).not.toBeNull();
  return card as HTMLElement;
}

describe("KpiCards (R14.1)", () => {
  it("renders all four KPI header cards", () => {
    render(<KpiCards kpis={FULL_KPIS} />);

    expect(
      screen.getByText("Active Pipeline Valuation"),
    ).toBeInTheDocument();
    expect(screen.getByText("Avg LTV-to-Cost")).toBeInTheDocument();
    expect(screen.getByText("Portfolio Risk Exposure")).toBeInTheDocument();
    expect(screen.getByText("Model Accuracy")).toBeInTheDocument();
  });

  it("formats the valuation compactly in USD", () => {
    render(<KpiCards kpis={FULL_KPIS} />);
    const card = cardByLabel("Active Pipeline Valuation");
    expect(within(card).getByText("$12.4M")).toBeInTheDocument();
  });

  it("formats the LTV multiple with a two-decimal ×", () => {
    render(<KpiCards kpis={FULL_KPIS} />);
    const card = cardByLabel("Avg LTV-to-Cost");
    expect(within(card).getByText("3.20×")).toBeInTheDocument();
  });

  it("formats risk exposure and accuracy as rounded percentages", () => {
    render(<KpiCards kpis={FULL_KPIS} />);
    expect(
      within(cardByLabel("Portfolio Risk Exposure")).getByText("42%"),
    ).toBeInTheDocument();
    expect(
      within(cardByLabel("Model Accuracy")).getByText("87%"),
    ).toBeInTheDocument();
  });

  it("renders a dash placeholder for each null figure instead of zero", () => {
    const empty: DashboardKpis = {
      active_pipeline_valuation_usd: null,
      avg_ltv_to_cost: null,
      portfolio_risk_exposure: null,
      model_accuracy_rate: null,
    };
    render(<KpiCards kpis={empty} />);

    expect(screen.getAllByText("—")).toHaveLength(4);
    expect(screen.queryByText("$0")).not.toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });

  it("has an accessible region label for the KPI group", () => {
    render(<KpiCards kpis={FULL_KPIS} />);
    expect(
      screen.getByRole("region", {
        name: "Portfolio key performance indicators",
      }),
    ).toBeInTheDocument();
  });
});
