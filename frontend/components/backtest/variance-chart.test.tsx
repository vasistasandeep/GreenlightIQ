import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { VarianceChart } from "@/components/backtest/variance-chart";
import type { AuditMetric } from "@/lib/types";

/**
 * VarianceChart tests (R16.2).
 *
 * R16.2 requires side-by-side Predicted vs Actual comparison for CPVH and the
 * LTV multiple after a ground-truth submission.
 *
 * Recharts renders through a ResponsiveContainer that measures its parent with
 * ResizeObserver; in jsdom the container reports a zero size and the SVG never
 * draws, so there is nothing to assert against. We replace the Recharts
 * primitives with lightweight DOM stand-ins that expose the data the chart was
 * handed (metric labels + the Predicted/Actual series) as inspectable nodes.
 * This keeps the assertions on *what the component charts* rather than on
 * Recharts' internal SVG geometry.
 */

vi.mock("recharts", () => {
  const Passthrough = ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  );

  return {
    ResponsiveContainer: Passthrough,
    BarChart: ({
      data,
      children,
    }: {
      data: Array<{ label: string; predicted: number; actual: number; excluded: boolean }>;
      children?: React.ReactNode;
    }) => (
      <div data-testid="bar-chart">
        <ul>
          {data.map((d) => (
            <li key={d.label} data-testid="chart-row">
              <span data-testid="row-label">{d.label}</span>
              <span data-testid="row-predicted">{d.predicted}</span>
              <span data-testid="row-actual">{d.actual}</span>
              <span data-testid="row-excluded">{String(d.excluded)}</span>
            </li>
          ))}
        </ul>
        {children}
      </div>
    ),
    Bar: ({ name, children }: { name?: string; children?: React.ReactNode }) => (
      <div data-testid="bar" data-series={name}>
        {children}
      </div>
    ),
    Cell: () => <div data-testid="cell" />,
    CartesianGrid: () => null,
    XAxis: () => null,
    YAxis: () => null,
    Tooltip: () => null,
    Legend: () => <div data-testid="legend" />,
  };
});

const METRICS: AuditMetric[] = [
  { metric: "cpvh", predicted: 0.1, actual: 0.12, excluded: false },
  { metric: "ltv_to_cost_multiple", predicted: 3.2, actual: 2.9, excluded: false },
];

describe("VarianceChart (R16.2)", () => {
  it("renders an empty-state message when there are no metrics", () => {
    render(<VarianceChart metrics={[]} />);
    expect(
      screen.getByText(/No metrics to compare for this title/i),
    ).toBeInTheDocument();
  });

  it("plots one row per audited metric with readable labels", () => {
    render(<VarianceChart metrics={METRICS} />);

    const labels = screen
      .getAllByTestId("row-label")
      .map((n) => n.textContent);
    expect(labels).toEqual(["CPVH", "LTV-to-Cost"]);
  });

  it("charts both the Predicted and Actual series side by side", () => {
    render(<VarianceChart metrics={METRICS} />);

    const series = screen
      .getAllByTestId("bar")
      .map((n) => n.getAttribute("data-series"));
    expect(series).toEqual(["Predicted", "Actual"]);
  });

  it("passes the predicted and actual values for each metric", () => {
    render(<VarianceChart metrics={METRICS} />);

    const predicted = screen
      .getAllByTestId("row-predicted")
      .map((n) => n.textContent);
    const actual = screen
      .getAllByTestId("row-actual")
      .map((n) => n.textContent);

    expect(predicted).toEqual(["0.1", "3.2"]);
    expect(actual).toEqual(["0.12", "2.9"]);
  });

  it("annotates excluded (zero-actual) metrics and notes the exclusion", () => {
    render(
      <VarianceChart
        metrics={[
          { metric: "cpvh", predicted: 0.1, actual: 0.12, excluded: false },
          {
            metric: "ltv_to_cost_multiple",
            predicted: 3.2,
            actual: 0,
            excluded: true,
          },
        ]}
      />,
    );

    const excluded = screen
      .getAllByTestId("row-excluded")
      .map((n) => n.textContent);
    expect(excluded).toEqual(["false", "true"]);
    expect(
      screen.getByText(/excluded from the MAPE calculation/i),
    ).toBeInTheDocument();
  });

  it("omits the exclusion note when no metrics are excluded", () => {
    render(<VarianceChart metrics={METRICS} />);
    expect(
      screen.queryByText(/excluded from the MAPE calculation/i),
    ).not.toBeInTheDocument();
  });

  it("exposes an accessible label describing the chart", () => {
    render(<VarianceChart metrics={METRICS} />);
    expect(
      screen.getByRole("img", {
        name: /Predicted versus actual variance by metric/i,
      }),
    ).toBeInTheDocument();
  });
});
