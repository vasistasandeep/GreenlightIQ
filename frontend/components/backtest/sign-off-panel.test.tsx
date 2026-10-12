import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { SignOffPanel } from "@/components/backtest/sign-off-panel";
import type { FinalizationStatus } from "@/lib/types";

/**
 * SignOffPanel tests (R20.5).
 *
 * A high-budget GREENLIGHT decision cannot be finalized until every required
 * executive sign-off is recorded. The panel must surface the required roles and
 * which approvals remain outstanding, flip its gate indicator once all sign-offs
 * are in, and report the clear-to-finalize case when no gate applies.
 */

const AWAITING: FinalizationStatus = {
  decision_id: "d-1",
  can_finalize: false,
  required_roles: ["CHIEF_CONTENT_OFFICER", "CFO"],
  outstanding_roles: ["CFO"],
  approved_roles: ["CHIEF_CONTENT_OFFICER"],
};

const READY: FinalizationStatus = {
  decision_id: "d-2",
  can_finalize: true,
  required_roles: ["CHIEF_CONTENT_OFFICER", "CFO"],
  outstanding_roles: [],
  approved_roles: ["CHIEF_CONTENT_OFFICER", "CFO"],
};

/** Find the required-role list item that owns a given role label. */
function roleRow(label: string): HTMLElement {
  const node = screen.getByText(label);
  const li = node.closest("li");
  expect(li).not.toBeNull();
  return li as HTMLElement;
}

describe("SignOffPanel (R20.5)", () => {
  it("prompts to load a decision before any status is provided", () => {
    render(<SignOffPanel />);
    expect(
      screen.getByText(/Load a decision to view its sign-off requirements/i),
    ).toBeInTheDocument();
  });

  it("renders a loading state", () => {
    render(<SignOffPanel loading />);
    expect(screen.getByText(/Loading sign-off status/i)).toBeInTheDocument();
  });

  it("surfaces an error state", () => {
    render(<SignOffPanel error="Could not load finalization gate" />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      /Could not load finalization gate/i,
    );
  });

  describe("awaiting approvals", () => {
    it("lists the required roles with readable labels", () => {
      render(<SignOffPanel status={AWAITING} />);
      expect(screen.getByText("Chief Content Officer")).toBeInTheDocument();
      expect(screen.getByText("Chief Financial Officer")).toBeInTheDocument();
    });

    it("marks the gate as awaiting approvals and cannot finalize", () => {
      render(<SignOffPanel status={AWAITING} />);
      expect(screen.getByText(/Awaiting approvals/i)).toBeInTheDocument();
      expect(screen.queryByText(/Ready to finalize/i)).not.toBeInTheDocument();
    });

    it("shows the outstanding role as outstanding and the signed role as approved", () => {
      render(<SignOffPanel status={AWAITING} />);

      expect(
        within(roleRow("Chief Content Officer")).getByText(/Approved/i),
      ).toBeInTheDocument();
      expect(
        within(roleRow("Chief Financial Officer")).getByText(/Outstanding/i),
      ).toBeInTheDocument();
    });
  });

  describe("ready to finalize", () => {
    it("flips the gate indicator once every sign-off is recorded", () => {
      render(<SignOffPanel status={READY} />);
      expect(screen.getByText(/Ready to finalize/i)).toBeInTheDocument();
      expect(
        screen.queryByText(/Awaiting approvals/i),
      ).not.toBeInTheDocument();
    });

    it("marks every required role as approved", () => {
      render(<SignOffPanel status={READY} />);
      expect(
        within(roleRow("Chief Content Officer")).getByText(/Approved/i),
      ).toBeInTheDocument();
      expect(
        within(roleRow("Chief Financial Officer")).getByText(/Approved/i),
      ).toBeInTheDocument();
      expect(screen.queryByText(/Outstanding/i)).not.toBeInTheDocument();
    });
  });

  it("reports a clear-to-finalize decision when no sign-off is required", () => {
    render(
      <SignOffPanel
        status={{
          decision_id: "d-3",
          can_finalize: true,
          required_roles: [],
          outstanding_roles: [],
          approved_roles: [],
        }}
      />,
    );

    expect(
      screen.getByText(/No sign-off required/i),
    ).toBeInTheDocument();
  });
});
