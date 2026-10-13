import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import BacktestStudioPage from "@/app/backtest/page";
import { ApiError } from "@/lib/api-client";
import type { DashboardSummary } from "@/lib/types";

/**
 * BacktestStudioPage tests (R2.1, R2.3, R2.5, R3, R4.1, R4.2).
 *
 * The page loads auditable titles from GET /dashboard/summary on mount, passes
 * only titles with a stored prediction to the ground-truth selector, maps audit
 * rejections to readable messages, and preserves the success path.
 */

// Minimal recharts stub so the VarianceChart renders in jsdom without measuring.
vi.mock("recharts", () => {
  const Passthrough = ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  );
  return {
    ResponsiveContainer: Passthrough,
    BarChart: ({ children }: { children?: React.ReactNode }) => (
      <div data-testid="bar-chart">{children}</div>
    ),
    Bar: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
    Cell: () => <div />,
    CartesianGrid: () => null,
    XAxis: () => null,
    YAxis: () => null,
    Tooltip: () => null,
    Legend: () => <div />,
  };
});

// next/navigation is used by the shared TopNav inside AppShell.
vi.mock("next/navigation", () => ({
  usePathname: () => "/backtest",
}));

const {
  getDashboardSummary,
  backtestAudit,
  getFinalization,
  applyCalibration,
} = vi.hoisted(() => ({
  getDashboardSummary: vi.fn(),
  backtestAudit: vi.fn(),
  getFinalization: vi.fn(),
  applyCalibration: vi.fn(),
}));

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>(
    "@/lib/api-client",
  );
  return {
    ...actual,
    api: {
      getDashboardSummary,
      backtestAudit,
      getFinalization,
      applyCalibration,
    },
  };
});

function summaryWith(): DashboardSummary {
  return {
    kpis: {
      active_pipeline_valuation_usd: null,
      avg_ltv_to_cost: null,
      portfolio_risk_exposure: null,
      model_accuracy_rate: null,
    },
    titles: [
      {
        title_id: "t-pred",
        title_name: "Maharani",
        asset_type: "ORIGINAL_SERIES",
        asking_price: 100,
        native_currency: "USD",
        cpvh_status: "PASS",
        ltv_to_cost_multiple: 3.1,
        recommendation_status: "GREENLIGHT",
      },
      {
        title_id: "t-nopred",
        title_name: "Pending Title",
        asset_type: "ORIGINAL_FILM",
        asking_price: 50,
        native_currency: "USD",
        cpvh_status: "PENDING",
        ltv_to_cost_multiple: null,
        recommendation_status: null,
      },
    ],
  };
}

describe("BacktestStudioPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads the summary and offers only auditable titles (R2.1, R2.3)", async () => {
    getDashboardSummary.mockResolvedValue(summaryWith());

    render(<BacktestStudioPage />);

    await waitFor(() => expect(getDashboardSummary).toHaveBeenCalledTimes(1));
    expect(
      await screen.findByRole("option", { name: /Maharani/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: /Pending Title/ }),
    ).not.toBeInTheDocument();
  });

  it("shows a load-failure message and keeps submit disabled (R2.5)", async () => {
    getDashboardSummary.mockRejectedValue(new Error("network"));

    render(<BacktestStudioPage />);

    expect(
      await screen.findByText(/could not load auditable titles/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run audit/i })).toBeDisabled();
  });

  it("renders a mapped, readable message when an audit is rejected (R3)", async () => {
    getDashboardSummary.mockResolvedValue(summaryWith());
    backtestAudit.mockRejectedValue(
      new ApiError(404, "ground truth missing", {
        error_code: "GROUND_TRUTH_MISSING",
        message: "ground truth missing",
      }),
    );

    const user = userEvent.setup();
    render(<BacktestStudioPage />);

    await screen.findByRole("option", { name: /Maharani/ });
    await user.selectOptions(screen.getByLabelText("Historical title"), "t-pred");
    await user.type(screen.getByLabelText("Actual CPVH"), "0.12");
    await user.click(screen.getByRole("button", { name: /Run audit/i }));

    expect(
      await screen.findByText(
        /has no stored prediction to audit against/i,
      ),
    ).toBeInTheDocument();
  });

  it("renders the variance scorecard and enables calibration on success (R4.1, R4.2)", async () => {
    getDashboardSummary.mockResolvedValue(summaryWith());
    backtestAudit.mockResolvedValue({
      title_id: "t-pred",
      metrics: [{ metric: "cpvh", predicted: 0.1, actual: 0.12, excluded: false }],
      mape: 12.5,
      no_eligible_metrics: false,
    });
    getFinalization.mockResolvedValue({
      decision_id: "t-pred",
      can_finalize: false,
      required_roles: [],
      outstanding_roles: [],
      approved_roles: [],
    });

    const user = userEvent.setup();
    render(<BacktestStudioPage />);

    await screen.findByRole("option", { name: /Maharani/ });
    await user.selectOptions(screen.getByLabelText("Historical title"), "t-pred");
    await user.type(screen.getByLabelText("Actual CPVH"), "0.12");
    await user.click(screen.getByRole("button", { name: /Run audit/i }));

    expect(await screen.findByText(/Overall MAPE/i)).toBeInTheDocument();
    await waitFor(() => expect(getFinalization).toHaveBeenCalledWith("t-pred"));
  });
});