import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/**
 * AdvancedDriversBreakdown component tests (task 16, R6.1-R6.5).
 *
 * Mirrors the churn-breakdown.test.tsx / content-eval-breakdown.test.tsx style:
 * each driver card is a native collapsed `<details>`, so tests click the summary
 * to open it before asserting on the table. Covers the line items, the signed
 * diffs, the non-coercible placeholder path, the comps-confidence display, and
 * the backward-compatible (absent block) render.
 */

import { AdvancedDriversBreakdown } from "./advanced-drivers-breakdown";
import type { AdvancedDriversExplanation } from "@/lib/types";

/** A fully-populated advanced_drivers block with every driver resolved. */
function fullDrivers(
  overrides: Partial<AdvancedDriversExplanation> = {},
): AdvancedDriversExplanation {
  return {
    comps: {
      source_tier: "DETERMINISTIC_FALLBACK",
      realized_k: 5,
      use_intercept_fallback: false,
      comp_title_ids: ["a", "b", "c", "d", "e"],
      h_comps: "12500.0",
      c_comps: "1.80",
      dispersion_iqr: "3200.0",
      base_hours_override: "12500.0",
      base_churn_override: "1.80",
    },
    lineage: {
      source_tier: "DETERMINISTIC_FALLBACK",
      is_active: true,
      franchise_floor: "900.0",
      delta_c_franchise: "0.30",
      assumed_features: [],
    },
    momentum: {
      source_tier: "DETERMINISTIC_FALLBACK",
      value: "1.25",
      bounds: "[1.00,1.50]",
      production_stage: "ACQUISITION_READY",
      stage_excluded: false,
      reason: null,
    },
    macro_modifiers: {
      source_tier: "DETERMINISTIC_FALLBACK",
      source_ip_multiplier: "1.20",
      release_window_multiplier: "1.25",
      calendar_seasonality_multiplier: "0.90",
      vernacular_tam_multiplier: "1.00",
      product: "1.35",
      assumed_features: [],
    },
    ...overrides,
  };
}

/** Open the named driver card and return its <details> for scoped queries. */
async function open(title: string): Promise<HTMLElement> {
  const user = userEvent.setup();
  const summary = screen.getByText(title);
  await user.click(summary);
  return summary.closest("details") as HTMLElement;
}

describe("AdvancedDriversBreakdown (task 16)", () => {
  it("renders a card per resolved driver when advanced_drivers is present (R6.1)", () => {
    render(<AdvancedDriversBreakdown advancedDrivers={fullDrivers()} />);
    expect(screen.getByText("Comps anchor")).toBeInTheDocument();
    expect(screen.getByText("Franchise lineage")).toBeInTheDocument();
    expect(screen.getByText("Momentum telemetry")).toBeInTheDocument();
    expect(screen.getByText("Macro modifiers")).toBeInTheDocument();
  });

  it("renders the comps anchor H_comps / C_comps line items (R6.2, R6.3)", async () => {
    render(<AdvancedDriversBreakdown advancedDrivers={fullDrivers()} />);
    const card = await open("Comps anchor");
    expect(within(card).getByText("12,500")).toBeInTheDocument();
    expect(within(card).getByText("+1.80")).toBeInTheDocument();
  });

  it("shows comps confidence (realized_k and Comps_Dispersion IQR) (R6.2)", async () => {
    render(<AdvancedDriversBreakdown advancedDrivers={fullDrivers()} />);
    const card = await open("Comps anchor");
    const k = within(card).getByText("Comps confidence (k)").closest("div")!;
    expect(within(k).getByText("5")).toBeInTheDocument();
    const iqr = within(card).getByText("Dispersion (IQR)").closest("div")!;
    expect(within(iqr).getByText("3,200")).toBeInTheDocument();
  });

  it("renders the intercept-fallback note when no eligible comps exist (R1.5)", async () => {
    render(
      <AdvancedDriversBreakdown
        advancedDrivers={fullDrivers({
          comps: {
            source_tier: "DETERMINISTIC_FALLBACK",
            realized_k: 0,
            use_intercept_fallback: true,
            comp_title_ids: [],
          },
        })}
      />,
    );
    const card = await open("Comps anchor");
    expect(
      within(card).getByText(/fell back to the default viewing-hours intercept/i),
    ).toBeInTheDocument();
  });

  it("renders franchise floor lift and loyalty credit as signed values (R6.4)", async () => {
    render(<AdvancedDriversBreakdown advancedDrivers={fullDrivers()} />);
    const card = await open("Franchise lineage");
    const floor = within(card).getByText("Franchise floor lift").closest("tr")!;
    expect(within(floor).getByText("+900")).toBeInTheDocument();
    const credit = within(card)
      .getByText("Franchise loyalty credit")
      .closest("tr")!;
    expect(within(credit).getByText("+0.30")).toBeInTheDocument();
  });

  it("renders a not-a-franchise note when lineage is inactive (R2.5)", async () => {
    render(
      <AdvancedDriversBreakdown
        advancedDrivers={fullDrivers({
          lineage: {
            source_tier: "DETERMINISTIC_FALLBACK",
            is_active: false,
            franchise_floor: "0.0",
            delta_c_franchise: "0.00",
          },
        })}
      />,
    );
    const card = await open("Franchise lineage");
    expect(
      within(card).getByText(/Not a franchise entry/i),
    ).toBeInTheDocument();
  });

  it("renders the momentum multiplier as a signed diff vs the 1.00 baseline (R6.4)", async () => {
    render(<AdvancedDriversBreakdown advancedDrivers={fullDrivers()} />);
    const card = await open("Momentum telemetry");
    const row = within(card).getByText("Momentum multiplier").closest("tr")!;
    // before = 1.00x, after = 1.25x, delta = +25.0%
    expect(within(row).getByText("1.00x")).toBeInTheDocument();
    expect(within(row).getByText("1.25x")).toBeInTheDocument();
    expect(within(row).getByText("+25.0%")).toBeInTheDocument();
  });

  it("renders a stage-excluded note for an unproduced title (R3.3)", async () => {
    render(
      <AdvancedDriversBreakdown
        advancedDrivers={fullDrivers({
          momentum: {
            source_tier: "DETERMINISTIC_FALLBACK",
            value: "1.00",
            bounds: "[1.00,1.50]",
            production_stage: "CONCEPT_SCRIPT",
            stage_excluded: true,
            reason: null,
          },
        })}
      />,
    );
    const card = await open("Momentum telemetry");
    expect(within(card).getByText(/Stage-excluded/i)).toBeInTheDocument();
    expect(within(card).getByText(/CONCEPT_SCRIPT/)).toBeInTheDocument();
  });

  it("renders each macro modifier and the combined product as signed diffs (R6.4)", async () => {
    render(<AdvancedDriversBreakdown advancedDrivers={fullDrivers()} />);
    const card = await open("Macro modifiers");
    const ip = within(card).getByText("Source IP provenance").closest("tr")!;
    expect(within(ip).getByText("+20.0%")).toBeInTheDocument();
    const season = within(card)
      .getByText("Calendar seasonality")
      .closest("tr")!;
    // 0.90 -> a -10.0% signed delta (premium guarantee is per-driver math, not UI).
    expect(within(season).getByText("-10.0%")).toBeInTheDocument();
    const combined = within(card).getByText("Combined").closest("tr")!;
    expect(within(combined).getByText("+35.0%")).toBeInTheDocument();
  });

  it("renders a placeholder for a non-coercible value while other lines render", async () => {
    render(
      <AdvancedDriversBreakdown
        advancedDrivers={fullDrivers({
          lineage: {
            source_tier: "DETERMINISTIC_FALLBACK",
            is_active: true,
            franchise_floor: "not-a-number",
            delta_c_franchise: "0.30",
          },
        })}
      />,
    );
    const card = await open("Franchise lineage");
    const floor = within(card).getByText("Franchise floor lift").closest("tr")!;
    expect(within(floor).getByText("--")).toBeInTheDocument();
    // The sibling line still renders its real value.
    const credit = within(card)
      .getByText("Franchise loyalty credit")
      .closest("tr")!;
    expect(within(credit).getByText("+0.30")).toBeInTheDocument();
  });

  it("renders only the drivers that resolved (partial block)", () => {
    render(
      <AdvancedDriversBreakdown
        advancedDrivers={{ comps: fullDrivers().comps }}
      />,
    );
    expect(screen.getByText("Comps anchor")).toBeInTheDocument();
    expect(screen.queryByText("Momentum telemetry")).not.toBeInTheDocument();
    expect(screen.queryByText("Macro modifiers")).not.toBeInTheDocument();
  });

  it("renders nothing when advanced_drivers is null or undefined (flags off / pre-feature)", () => {
    const { container, rerender } = render(
      <AdvancedDriversBreakdown advancedDrivers={null} />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(<AdvancedDriversBreakdown advancedDrivers={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when every driver entry is absent (empty block)", () => {
    const { container } = render(
      <AdvancedDriversBreakdown advancedDrivers={{}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
