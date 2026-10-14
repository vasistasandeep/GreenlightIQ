import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/**
 * ChurnBreakdown component tests (R10, R13.3).
 *
 * The breakdown lives inside a native collapsed `<details>`; each test opens it
 * by clicking the summary (as financial-accordion.test.tsx does) before asserting
 * on the table / notes. The borderline pill and the "nothing rendered" case for a
 * null model are asserted without opening (the pill is inside the disclosure body,
 * so those tests open it too).
 */

import { ChurnBreakdown, BORDERLINE_MESSAGE } from "./churn-breakdown";
import type { ChurnModel } from "@/lib/types";

function calculatedModel(overrides: Partial<ChurnModel> = {}): ChurnModel {
  return {
    churn_method: "CALCULATED",
    is_borderline: false,
    params_source: "MODEL_VERSION",
    model_version_id: "mv-1",
    missing_features: [],
    churn_breakdown: {
      base_platform_rate: "0.03",
      asset_cadence: "0.35",
      talent_pedigree_contribution: "0.77",
      production_scale_contribution: "0.27",
      exclusivity_lift: "0.25",
      market_telemetry_heat: "0.33",
      genre_affinity: "0.15",
    },
    assumed_features: [],
    ...overrides,
  };
}

async function openDisclosure() {
  const user = userEvent.setup();
  await user.click(screen.getByText("Why this churn number"));
}

describe("ChurnBreakdown (R10)", () => {
  it("renders the six feature rows with labels and signed point values (R10.1)", async () => {
    render(<ChurnBreakdown churnModel={calculatedModel()} />);
    await openDisclosure();

    const table = screen.getByRole("table");
    const rows: [string, string][] = [
      ["Base Platform Rate", "+0.03"],
      ["Asset Cadence", "+0.35"],
      ["Talent Pedigree Contribution", "+0.77"],
      ["Production Scale Contribution", "+0.27"],
      ["Exclusivity Lift", "+0.25"],
      ["Market Telemetry Heat", "+0.33"],
      ["Genre Affinity", "+0.15"],
    ];
    for (const [label, points] of rows) {
      const row = within(table).getByText(label).closest("tr")!;
      expect(within(row).getByText(points)).toBeInTheDocument();
    }
  });

  it("renders a Bounds Adjustment row only when bounds_adjustment is present (R1.8)", async () => {
    const { rerender } = render(
      <ChurnBreakdown churnModel={calculatedModel()} />,
    );
    await openDisclosure();
    expect(screen.queryByText("Bounds Adjustment")).not.toBeInTheDocument();

    rerender(
      <ChurnBreakdown
        churnModel={calculatedModel({
          churn_breakdown: {
            ...calculatedModel().churn_breakdown!,
            bounds_adjustment: "-0.08",
          },
        })}
      />,
    );
    const table = screen.getByRole("table");
    const row = within(table).getByText("Bounds Adjustment").closest("tr")!;
    expect(within(row).getByText("-0.08")).toBeInTheDocument();
  });

  it("shows an unavailable tag and 0.00 points for a missing feature (R10.4)", async () => {
    render(
      <ChurnBreakdown
        churnModel={calculatedModel({
          missing_features: ["telemetry_heat"],
          churn_breakdown: {
            ...calculatedModel().churn_breakdown!,
            market_telemetry_heat: "0.00",
          },
        })}
      />,
    );
    await openDisclosure();

    const table = screen.getByRole("table");
    const row = within(table).getByText("Market Telemetry Heat").closest("tr")!;
    expect(within(row).getByText("unavailable")).toBeInTheDocument();
    expect(within(row).getByText("0.00")).toBeInTheDocument();
  });

  it("renders a Supplied note and NO per-feature table when SUPPLIED (R10.3)", async () => {
    render(
      <ChurnBreakdown
        churnModel={{
          churn_method: "SUPPLIED",
          is_borderline: false,
          churn_breakdown: null,
          missing_features: [],
        }}
      />,
    );
    await openDisclosure();

    expect(
      screen.getByText(/Supplied directly \(not calculated\)/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders the amber borderline pill with the exact message when is_borderline is true (R10.5)", async () => {
    render(
      <ChurnBreakdown churnModel={calculatedModel({ is_borderline: true })} />,
    );
    await openDisclosure();
    expect(screen.getByText(BORDERLINE_MESSAGE)).toBeInTheDocument();
    expect(BORDERLINE_MESSAGE).toBe(
      "Borderline Sensitivity: within 0.05% of the 1.50% hurdle",
    );
  });

  it("does not render the borderline pill when is_borderline is false", async () => {
    render(
      <ChurnBreakdown churnModel={calculatedModel({ is_borderline: false })} />,
    );
    await openDisclosure();
    expect(screen.queryByText(BORDERLINE_MESSAGE)).not.toBeInTheDocument();
  });

  it("shows the borderline pill for a SUPPLIED result too (R10.5)", async () => {
    render(
      <ChurnBreakdown
        churnModel={{
          churn_method: "SUPPLIED",
          is_borderline: true,
          churn_breakdown: null,
          missing_features: [],
        }}
      />,
    );
    await openDisclosure();
    expect(screen.getByText(BORDERLINE_MESSAGE)).toBeInTheDocument();
  });

  it("tags a neutral-telemetry row 'neutral (no market data)' not 'unavailable' (R15.2)", async () => {
    render(
      <ChurnBreakdown
        churnModel={calculatedModel({
          assumed_features: ["telemetry_heat"],
          churn_breakdown: {
            ...calculatedModel().churn_breakdown!,
            market_telemetry_heat: "0.25",
          },
        })}
      />,
    );
    await openDisclosure();
    const table = screen.getByRole("table");
    const row = within(table).getByText("Market Telemetry Heat").closest("tr")!;
    expect(within(row).getByText(/neutral \(no market data\)/i)).toBeInTheDocument();
    expect(within(row).queryByText("unavailable")).not.toBeInTheDocument();
    expect(within(row).getByText("+0.25")).toBeInTheDocument();
  });

  it("tags an unlisted-genre row 'neutral (unlisted genre)' (R14.3)", async () => {
    render(
      <ChurnBreakdown
        churnModel={calculatedModel({
          assumed_features: ["genre"],
          churn_breakdown: {
            ...calculatedModel().churn_breakdown!,
            genre_affinity: "0.10",
          },
        })}
      />,
    );
    await openDisclosure();
    const table = screen.getByRole("table");
    const row = within(table).getByText("Genre Affinity").closest("tr")!;
    expect(within(row).getByText(/neutral \(unlisted genre\)/i)).toBeInTheDocument();
  });

  it("renders nothing when churnModel is null or undefined (R7.6)", () => {
    const { container, rerender } = render(
      <ChurnBreakdown churnModel={null} />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(<ChurnBreakdown churnModel={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});
