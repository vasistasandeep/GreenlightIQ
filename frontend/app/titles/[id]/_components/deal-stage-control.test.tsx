import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DealStageControl } from "./deal-stage-control";
import { ApiError } from "@/lib/api-client";
import type { DealStageInfo } from "@/lib/types";

/**
 * DealStageControl tests (deal-stage lifecycle).
 *
 * The control fetches the current stage + allowed moves, advances on a button
 * click (showing only server-sanctioned next stages), surfaces a rejected move,
 * and degrades to a view-only state on a 403.
 */

const { getDealStage, setDealStage } = vi.hoisted(() => ({
  getDealStage: vi.fn(),
  setDealStage: vi.fn(),
}));

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>(
    "@/lib/api-client",
  );
  return { ...actual, api: { getDealStage, setDealStage } };
});

function info(overrides: Partial<DealStageInfo> = {}): DealStageInfo {
  return {
    title_id: "t-1",
    deal_stage: "EVALUATED",
    allowed_next_stages: ["IN_NEGOTIATION", "PASSED"],
    ...overrides,
  };
}

describe("DealStageControl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the current stage and its allowed next-stage buttons", async () => {
    getDealStage.mockResolvedValue(info());
    render(<DealStageControl titleId="t-1" />);

    await waitFor(() => expect(screen.getByText("Evaluated")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "In Negotiation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Passed" })).toBeInTheDocument();
  });

  it("advances the stage when a next-stage button is clicked", async () => {
    const user = userEvent.setup();
    getDealStage.mockResolvedValue(info());
    setDealStage.mockResolvedValue(
      info({ deal_stage: "IN_NEGOTIATION", allowed_next_stages: ["APPROVED", "PASSED"] }),
    );
    render(<DealStageControl titleId="t-1" />);

    await waitFor(() => screen.getByRole("button", { name: "In Negotiation" }));
    await user.click(screen.getByRole("button", { name: "In Negotiation" }));

    expect(setDealStage).toHaveBeenCalledWith("t-1", "IN_NEGOTIATION");
    await waitFor(() => expect(screen.getByText("In Negotiation")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Approved" })).toBeInTheDocument();
  });

  it("shows a terminal message when there are no allowed next stages", async () => {
    getDealStage.mockResolvedValue(
      info({ deal_stage: "CLOSED_WON", allowed_next_stages: [] }),
    );
    render(<DealStageControl titleId="t-1" />);

    await waitFor(() =>
      expect(screen.getByText(/reached a final stage/i)).toBeInTheDocument(),
    );
  });

  it("falls back to view-only on a 403 and surfaces a permission message", async () => {
    const user = userEvent.setup();
    getDealStage.mockResolvedValue(info());
    setDealStage.mockRejectedValue(new ApiError(403, "forbidden"));
    render(<DealStageControl titleId="t-1" />);

    await waitFor(() => screen.getByRole("button", { name: "In Negotiation" }));
    await user.click(screen.getByRole("button", { name: "In Negotiation" }));

    await waitFor(() =>
      expect(screen.getByText(/do not have permission/i)).toBeInTheDocument(),
    );
    // The action buttons are withdrawn once we learn the user lacks permission.
    expect(
      screen.queryByRole("button", { name: "In Negotiation" }),
    ).not.toBeInTheDocument();
  });

  it("surfaces a rejected (illegal) transition message", async () => {
    const user = userEvent.setup();
    getDealStage.mockResolvedValue(info());
    setDealStage.mockRejectedValue(
      new ApiError(422, "Cannot move a deal from EVALUATED to CLOSED_WON."),
    );
    render(<DealStageControl titleId="t-1" />);

    await waitFor(() => screen.getByRole("button", { name: "In Negotiation" }));
    await user.click(screen.getByRole("button", { name: "Passed" }));

    await waitFor(() =>
      expect(screen.getByText(/Cannot move a deal/i)).toBeInTheDocument(),
    );
  });
});