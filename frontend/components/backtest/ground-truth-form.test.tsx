import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { GroundTruthForm } from "@/components/backtest/ground-truth-form";
import type { BacktestAuditRequest } from "@/lib/types";

/**
 * GroundTruthForm submission + validation tests (R16.1).
 *
 * R16.1 requires the studio's left pane to collect historical ground-truth
 * input. The form must shape a well-formed {@link BacktestAuditRequest} on
 * submit, only including metrics the analyst actually filled in, and must
 * block submission with a descriptive message when required input is missing
 * or non-numeric (mirroring the server-side R11.2 contract it feeds).
 */

/** Capture the request the form hands to its parent on a valid submit. */
function lastRequest(onSubmit: ReturnType<typeof vi.fn>): BacktestAuditRequest {
  return onSubmit.mock.calls.at(-1)?.[0] as BacktestAuditRequest;
}

describe("GroundTruthForm (R16.1)", () => {
  let onSubmit: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onSubmit = vi.fn();
  });

  it("renders the title-id control and the audited-metric fields", () => {
    render(<GroundTruthForm onSubmit={onSubmit} />);

    expect(screen.getByLabelText("Historical title ID")).toBeInTheDocument();
    expect(screen.getByLabelText("Actual CPVH")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Actual LTV-to-Cost multiple"),
    ).toBeInTheDocument();
  });

  it("submits a shaped request with the entered actuals", async () => {
    const user = userEvent.setup();
    render(<GroundTruthForm onSubmit={onSubmit} />);

    await user.type(
      screen.getByLabelText("Historical title ID"),
      "title-123",
    );
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
        { metric_name: "ltv_to_cost_multiple", actual_value: 3.4 },
      ],
    });
  });

  it("omits blank metric fields rather than sending them as zero", async () => {
    const user = userEvent.setup();
    render(<GroundTruthForm onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Historical title ID"), "t-1");
    await user.type(screen.getByLabelText("Actual CPVH"), "0.09");
    // Leave the LTV field blank.
    await user.click(screen.getByRole("button", { name: /Run audit/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const request = lastRequest(onSubmit);
    expect(request.metrics).toEqual([
      { metric_name: "cpvh", actual_value: 0.09 },
    ]);
  });

  it("trims surrounding whitespace from the title identifier", async () => {
    const user = userEvent.setup();
    render(<GroundTruthForm onSubmit={onSubmit} />);

    await user.type(screen.getByLabelText("Historical title ID"), "  t-7  ");
    await user.type(screen.getByLabelText("Actual CPVH"), "0.1");
    await user.click(screen.getByRole("button", { name: /Run audit/i }));

    expect(lastRequest(onSubmit).title_id).toBe("t-7");
  });

  describe("validation", () => {
    it("blocks submission and reports a missing title identifier", async () => {
      const user = userEvent.setup();
      render(<GroundTruthForm onSubmit={onSubmit} />);

      await user.type(screen.getByLabelText("Actual CPVH"), "0.1");
      await user.click(screen.getByRole("button", { name: /Run audit/i }));

      expect(onSubmit).not.toHaveBeenCalled();
      expect(screen.getByRole("alert")).toHaveTextContent(
        /title identifier is required/i,
      );
    });

    it("blocks submission when no actual values are entered", async () => {
      const user = userEvent.setup();
      render(<GroundTruthForm onSubmit={onSubmit} />);

      await user.type(screen.getByLabelText("Historical title ID"), "t-1");
      await user.click(screen.getByRole("button", { name: /Run audit/i }));

      expect(onSubmit).not.toHaveBeenCalled();
      expect(screen.getByRole("alert")).toHaveTextContent(
        /at least one observed actual value/i,
      );
    });

    it("disables the controls while an audit is in flight", () => {
      render(<GroundTruthForm onSubmit={onSubmit} submitting />);

      expect(screen.getByLabelText("Historical title ID")).toBeDisabled();
      expect(screen.getByLabelText("Actual CPVH")).toBeDisabled();
      expect(
        screen.getByRole("button", { name: /Running audit/i }),
      ).toBeDisabled();
    });
  });
});
