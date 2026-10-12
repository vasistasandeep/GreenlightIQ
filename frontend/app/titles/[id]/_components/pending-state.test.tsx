import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { PendingValuationState } from "./pending-state";

/**
 * PendingValuationState component tests (R15.4).
 *
 * Rendered when a title has no completed valuation yet. We assert the status
 * role (so assistive tech announces it as a status rather than an error), the
 * pending headline/explanatory copy, and that the title id is surfaced.
 */

describe("PendingValuationState (R15.4)", () => {
  it("announces the pending valuation as a status region", () => {
    render(<PendingValuationState titleId="t-123" />);
    const status = screen.getByRole("status");
    expect(status).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Valuation pending" }),
    ).toBeInTheDocument();
  });

  it("explains that no completed valuation exists yet", () => {
    render(<PendingValuationState titleId="t-123" />);
    expect(
      screen.getByText(/does not have a completed valuation yet/i),
    ).toBeInTheDocument();
  });

  it("surfaces the title id so the user knows which title is pending", () => {
    render(<PendingValuationState titleId="t-abc-789" />);
    expect(screen.getByText(/Title t-abc-789/)).toBeInTheDocument();
  });
});
