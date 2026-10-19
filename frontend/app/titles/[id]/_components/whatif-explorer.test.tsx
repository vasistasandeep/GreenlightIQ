import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const replace = vi.hoisted(() => vi.fn());
const params = vi.hoisted(() => ({ value: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => params.value,
}));

const { whatIf } = vi.hoisted(() => ({ whatIf: vi.fn() }));
vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, api: { whatIf } };
});

import { WhatIfExplorer } from "./whatif-explorer";

function resp(scenarioRec: string, ltv: number, breached: boolean) {
  return {
    title_id: "t1",
    recommendation_status: scenarioRec,
    calculated_cpvh: "0.04",
    ltv_to_cost_multiple: String(ltv),
    churn_reduction_pct: "2.00",
    payback_horizon_months: 8,
    normalized_cost_usd: "1000000",
    model_version_id: "m1",
    explanation: { checks: [{ name: "LTV_TO_COST", computed_value: String(ltv), threshold: "3.2", passed: !breached, breached, shortfall_magnitude: null, correctable: breached }], dominant_factor: null, unclassifiable: false },
    metadata_breakdown: null,
    ltv_attribution: { subscription_value: "100", advertising_value: "50", total_modeled_value: "150", normalized_cost_usd: "1000000", multiple: String(ltv) },
    baseline: { recommendation_status: "NEGOTIATE_HARD", calculated_cpvh: "0.04", ltv_to_cost_multiple: "2.90", churn_reduction_pct: "2.00", payback_horizon_months: 8, ltv_subscription_value: "100", ltv_advertising_value: "50", inputs: { cost_usd: "1000000", projected_viewing_hours: "250000", churn_reduction_pct: "2.00", ltv: "150", churn_reduction_value: "2", cpm: "28", ad_impressions: "100000", watch_time_elasticity: "0.6" }, explanation: { checks: [{ name: "LTV_TO_COST", computed_value: "2.90", threshold: "3.2", passed: false, breached: true, shortfall_magnitude: "0.09", correctable: true }] } },
    negotiation_ceiling_usd: "600000",
  };
}

describe("WhatIfExplorer", () => {
  beforeEach(() => {
    whatIf.mockReset();
    replace.mockReset();
    params.value = new URLSearchParams();
  });

  it("renders the sandbox banner and computes an initial scenario", async () => {
    whatIf.mockResolvedValue(resp("NEGOTIATE_HARD", 2.9, true));
    render(<WhatIfExplorer titleId="t1" />);
    expect(screen.getByText(/Exploration sandbox/i)).toBeInTheDocument();
    await waitFor(() => expect(whatIf).toHaveBeenCalled());
  });

  it("shows a verdict-movement callout when the scenario flips the verdict", async () => {
    whatIf.mockResolvedValue(resp("GREENLIGHT", 3.5, false));
    render(<WhatIfExplorer titleId="t1" />);
    // Set a cost override so a request fires.
    fireEvent.change(screen.getByLabelText("Acquisition cost (USD)"), { target: { value: "600000" } });
    await waitFor(() =>
      expect(screen.getByText(/changed from NEGOTIATE HARD/i)).toBeInTheDocument(),
    );
  });

  it("disables Target deal when baseline is already GREENLIGHT", async () => {
    whatIf.mockResolvedValue({ ...resp("GREENLIGHT", 3.5, false), baseline: { ...resp("GREENLIGHT", 3.5, false).baseline, recommendation_status: "GREENLIGHT" } });
    render(<WhatIfExplorer titleId="t1" />);
    await waitFor(() => expect(whatIf).toHaveBeenCalled());
    const btn = screen.getByRole("button", { name: /Target deal/i });
    await waitFor(() => expect(btn).toBeDisabled());
  });

  it("reset all clears overrides", async () => {
    whatIf.mockResolvedValue(resp("NEGOTIATE_HARD", 2.9, true));
    render(<WhatIfExplorer titleId="t1" />);
    const input = screen.getByLabelText("CPM (USD / 1k)") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "32" } });
    expect(input.value).toBe("32");
    fireEvent.click(screen.getByRole("button", { name: "Reset all" }));
    await waitFor(() => expect((screen.getByLabelText("CPM (USD / 1k)") as HTMLInputElement).value).toBe(""));
  });

  it("Bull preset fills driver fields with concrete values (not blank)", async () => {
    whatIf.mockResolvedValue(resp("NEGOTIATE_HARD", 2.9, true));
    render(<WhatIfExplorer titleId="t1" />);
    await waitFor(() => expect(whatIf).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: /Bull case/i }));
    await waitFor(() => {
      const cpm = screen.getByLabelText("CPM (USD / 1k)") as HTMLInputElement;
      // Baseline CPM 28 * 1.25 = 35 -> the field now shows a concrete number.
      expect(cpm.value).toBe("35");
    });
  });
});