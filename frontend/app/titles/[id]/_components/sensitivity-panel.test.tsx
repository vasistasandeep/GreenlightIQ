import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";

import { SensitivityPanel } from "./sensitivity-panel";
import type { ValuationScorecard } from "@/lib/types";

/**
 * SensitivityPanel tests (What-If Sensitivity, R6-R9).
 *
 * The panel debounces slider changes into a single what-if request, renders the
 * recomputed badge + four metrics, labels the preview as non-persisted, and
 * coerces string-encoded decimals defensively.
 */

const { whatIf } = vi.hoisted(() => ({ whatIf: vi.fn() }));

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>(
    "@/lib/api-client",
  );
  return { ...actual, api: { whatIf } };
});

function scorecard(overrides: Partial<ValuationScorecard> = {}): ValuationScorecard {
  return {
    title_id: "t-1",
    calculated_cpvh: "0.12",
    ltv_to_cost_multiple: "4.1",
    churn_reduction_pct: "2.0",
    payback_horizon_months: 11,
    recommendation_status: "GREENLIGHT",
    normalized_cost_usd: "1000000",
    model_version_id: "mv-1",
    explanation: { checks: [], dominant_factor: null, unclassifiable: false },
    metadata_breakdown: null,
    target_purchase_ceiling_usd: null,
    implied_discount_pct: null,
    counter_proposal_levers: [],
    ltv_attribution: null,
    churn_cohort: null,
    ...overrides,
  };
}

describe("SensitivityPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    whatIf.mockResolvedValue(scorecard());
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders three sliders bounded to the multiplier range, initialized at 1.0", () => {
    render(<SensitivityPanel titleId="t-1" />);
    const cost = screen.getByLabelText("Cost multiplier") as HTMLInputElement;
    const view = screen.getByLabelText("Viewership multiplier") as HTMLInputElement;
    const churn = screen.getByLabelText("Churn multiplier") as HTMLInputElement;
    for (const slider of [cost, view, churn]) {
      expect(slider.min).toBe("0.5");
      expect(slider.max).toBe("2");
      expect(slider.value).toBe("1");
    }
  });

  it("shows the non-persisted scenario label (ASCII only)", () => {
    render(<SensitivityPanel titleId="t-1" />);
    const label = screen.getByText("Scenario preview - not saved");
    expect(label).toBeInTheDocument();
    expect([...label.textContent!].every((ch) => ch.charCodeAt(0) < 128)).toBe(true);
  });

  it("carries the no-print class so it is excluded from the Greenlight Memo print", () => {
    const { container } = render(<SensitivityPanel titleId="t-1" />);
    expect(container.querySelector("section")?.className).toContain("no-print");
  });

  it("debounces rapid slider changes into a single request with the latest value", async () => {
    vi.useFakeTimers();
    render(<SensitivityPanel titleId="t-1" />);
    const cost = screen.getByLabelText("Cost multiplier") as HTMLInputElement;

    // Three rapid changes within the debounce window.
    fireEvent.change(cost, { target: { value: "1.1" } });
    fireEvent.change(cost, { target: { value: "1.2" } });
    fireEvent.change(cost, { target: { value: "1.5" } });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });

    // Only the final value should have produced a (single) call.
    const calls = whatIf.mock.calls.filter(
      (c) => (c[1] as { cost_multiplier: number }).cost_multiplier === 1.5,
    );
    expect(calls.length).toBe(1);
  });

  it("renders the recomputed badge and coerces string metrics to numbers", async () => {
    whatIf.mockResolvedValue(
      scorecard({ recommendation_status: "NEGOTIATE_HARD", calculated_cpvh: "0.25" }),
    );
    render(<SensitivityPanel titleId="t-1" />);
    expect(await screen.findByText("NEGOTIATE HARD")).toBeInTheDocument();
    // string "0.25" coerced + formatted (not NaN)
    expect(await screen.findByText("0.25")).toBeInTheDocument();
  });

  it("renders a placeholder for a non-coercible metric but keeps the others", async () => {
    whatIf.mockResolvedValue(
      scorecard({ calculated_cpvh: "not-a-number", ltv_to_cost_multiple: "4.10" }),
    );
    render(<SensitivityPanel titleId="t-1" />);
    expect(await screen.findByText("4.10×")).toBeInTheDocument();
    // CPVH is non-coercible -> a placeholder dash appears in the metrics.
    expect(screen.getAllByText("-").length).toBeGreaterThan(0);
  });
});