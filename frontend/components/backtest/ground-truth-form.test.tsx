import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { GroundTruthForm } from "@/components/backtest/ground-truth-form";
import type { BacktestAuditRequest } from "@/lib/types";
import type { AuditableTitleOption } from "@/lib/backtest/select-auditable-titles";

/**
 * GroundTruthForm submission + validation tests (R16.1).
 *
 * R16.1 requires the studio's left pane to collect historical ground-truth
 * input. The form must shape a well-formed {@link BacktestAuditRequest} on
 * submit, only including metrics the analyst actually filled in, and must
 * block submission with a descriptive message when required input is missing
 * or non-numeric (mirroring the server-side R11.2 contract it feeds).
 *
 * The historical title is chosen from a selector of auditable titles supplied by
 * the page (R1.1-R1.4, R2.4), not typed free-hand.
 */

const TITLES: AuditableTitleOption[] = [
  { title_id: "title-123", title_name: "Maharani", ltv_to_cost_multiple: 3.1 },
  { title_id: "title-456", title_name: "The Long Road", ltv_to_cost_multiple: 2.4 },
];

/** Capture the request the form hands to its parent on a valid submit. */
function lastRequest(onSubmit: ReturnType<typeof vi.fn>): BacktestAuditRequest {
  return onSubmit.mock.calls.at(-1)?.[0] as BacktestAuditRequest;
}

describe("GroundTruthForm (R16.1)", () => {
  let onSubmit: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onSubmit = vi.fn();
  });

  it("renders a title selector listing each auditable title name (R1.1, R1.2)", () => {
    render(
      <GroundTruthForm titles={TITLES} titlesStatus="loaded" onSubmit={onSubmit} />,
    );

    const selector = screen.getByLabelText("Historical title");
    expect(selector).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /Maharani/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: /The Long Road/ }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Actual CPVH")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Actual LTV-to-Cost multiple"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Actual churn reduction (%)"),
    ).toBeInTheDocument();
  });

  it("submits a shaped request with the selected title id and entered actuals (R1.3, R1.5)", async () => {
    const user = userEvent.setup();
    render(
      <GroundTruthForm titles={TITLES} titlesStatus="loaded" onSubmit={onSubmit} />,
    );

    await user.selectOptions(screen.getByLabelText("Historical title"), "title-123");
    await user.type(screen.getByLabelText("Actual CPVH"), "0.12");
    await user.type(
      screen.getByLabelText("Actual LTV-to-Cost multiple"),
      "3.4",
    );
    await user.click(screen.getByRole("button", { name: /Run audit/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(lastRequest(onSubmit)).toEqual({
      title_id: "title-123",
      metrics: [
        { metric_name: "cpvh", actual_value: 0.12 },
        { metric_name: "ltv_to_cost", actual_value: 3.4 },
      ],
    });
  });

  it("omits blank metric fields rather than sending them as zero (R4.3)", async () => {
    const user = userEvent.setup();
    render(
      <GroundTruthForm titles={TITLES} titlesStatus="loaded" onSubmit={onSubmit} />,
    );

    await user.selectOptions(screen.getByLabelText("Historical title"), "title-456");
    await user.type(screen.getByLabelText("Actual CPVH"), "0.09");
    // Leave the LTV field blank.
    await user.click(screen.getByRole("button", { name: /Run audit/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const request = lastRequest(onSubmit);
    expect(request.title_id).toBe("title-456");
    expect(request.metrics).toEqual([
      { metric_name: "cpvh", actual_value: 0.09 },
    ]);
  });

  it("includes the churn_reduction metric when the churn field is filled (R11.3)", async () => {
    const user = userEvent.setup();
    render(
      <GroundTruthForm titles={TITLES} titlesStatus="loaded" onSubmit={onSubmit} />,
    );

    await user.selectOptions(screen.getByLabelText("Historical title"), "title-123");
    await user.type(
      screen.getByLabelText("Actual churn reduction (%)"),
      "1.8",
    );
    await user.click(screen.getByRole("button", { name: /Run audit/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(lastRequest(onSubmit).metrics).toContainEqual({
      metric_name: "churn_reduction",
      actual_value: 1.8,
    });
  });

  it("omits the churn_reduction metric when the churn field is left blank (R11.3)", async () => {
    const user = userEvent.setup();
    render(
      <GroundTruthForm titles={TITLES} titlesStatus="loaded" onSubmit={onSubmit} />,
    );

    await user.selectOptions(screen.getByLabelText("Historical title"), "title-123");
    await user.type(screen.getByLabelText("Actual CPVH"), "0.12");
    // Leave churn (and LTV) blank.
    await user.click(screen.getByRole("button", { name: /Run audit/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const metricNames = lastRequest(onSubmit).metrics.map((m) => m.metric_name);
    expect(metricNames).not.toContain("churn_reduction");
  });

  describe("title selection gating (R1.4, R2.4)", () => {
    it("keeps submit disabled until a title is selected", async () => {
      const user = userEvent.setup();
      render(
        <GroundTruthForm titles={TITLES} titlesStatus="loaded" onSubmit={onSubmit} />,
      );

      const submit = screen.getByRole("button", { name: /Run audit/i });
      expect(submit).toBeDisabled();

      await user.selectOptions(
        screen.getByLabelText("Historical title"),
        "title-123",
      );
      expect(submit).toBeEnabled();
    });

    it("shows the empty-state message and disables controls when no titles are auditable", () => {
      render(
        <GroundTruthForm titles={[]} titlesStatus="empty" onSubmit={onSubmit} />,
      );

      expect(
        screen.getByText(
          /no titles with a stored prediction are available to audit/i,
        ),
      ).toBeInTheDocument();
      expect(screen.getByLabelText("Historical title")).toBeDisabled();
      expect(screen.getByRole("button", { name: /Run audit/i })).toBeDisabled();
    });

    it("disables the selector while titles are loading", () => {
      render(
        <GroundTruthForm titles={[]} titlesStatus="loading" onSubmit={onSubmit} />,
      );

      expect(screen.getByLabelText("Historical title")).toBeDisabled();
      expect(screen.getByRole("button", { name: /Run audit/i })).toBeDisabled();
    });
  });

  describe("validation", () => {
    it("blocks submission when no actual values are entered", async () => {
      const user = userEvent.setup();
      render(
        <GroundTruthForm
          titles={TITLES}
          titlesStatus="loaded"
          onSubmit={onSubmit}
        />,
      );

      await user.selectOptions(
        screen.getByLabelText("Historical title"),
        "title-123",
      );
      await user.click(screen.getByRole("button", { name: /Run audit/i }));

      expect(onSubmit).not.toHaveBeenCalled();
      expect(screen.getByRole("alert")).toHaveTextContent(
        /at least one observed actual value/i,
      );
    });

    it("disables the controls while an audit is in flight", () => {
      render(
        <GroundTruthForm
          titles={TITLES}
          titlesStatus="loaded"
          onSubmit={onSubmit}
          submitting
        />,
      );

      expect(screen.getByLabelText("Historical title")).toBeDisabled();
      expect(screen.getByLabelText("Actual CPVH")).toBeDisabled();
      expect(
        screen.getByRole("button", { name: /Running audit/i }),
      ).toBeDisabled();
    });
  });
});