import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { AuditLineage } from "./audit-lineage";

const { getTitleDecision, getLineage } = vi.hoisted(() => ({
  getTitleDecision: vi.fn(),
  getLineage: vi.fn(),
}));

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, api: { getTitleDecision, getLineage } };
});

describe("AuditLineage (R25.4)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getTitleDecision.mockResolvedValue({ title_id: "t-1", decision_id: "d-1" });
    getLineage.mockResolvedValue({
      subject_id: "d-1",
      entries: [
        {
          audit_id: "a-1",
          subject_id: "d-1",
          actor_id: "u-1",
          action: "valuation",
          before_value: null,
          after_value: null,
          model_version_id: "mv-1",
          created_at: "2026-10-10T14:22:00Z",
        },
        {
          audit_id: "a-2",
          subject_id: "d-1",
          actor_id: "u-2",
          action: "override",
          before_value: { recommendation_status: "PASS" },
          after_value: { recommendation_status: "GREENLIGHT" },
          model_version_id: null,
          created_at: "2026-10-11T09:15:00Z",
        },
      ],
    });
  });

  it("lazily loads lineage on first expand and renders entries chronologically", async () => {
    render(<AuditLineage titleId="t-1" />);
    expect(getLineage).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Audit history/i }));

    expect(await screen.findByText(/Guardrail valuation executed/i)).toBeInTheDocument();
    expect(screen.getByText(/Recommendation overridden/i)).toBeInTheDocument();
    // The override entry summarizes the before -> after status change.
    expect(screen.getByText(/PASS to GREENLIGHT/)).toBeInTheDocument();
    await waitFor(() => expect(getTitleDecision).toHaveBeenCalledWith("t-1"));
  });

  it("shows an empty state when there is no history", async () => {
    getLineage.mockResolvedValue({ subject_id: "d-1", entries: [] });
    render(<AuditLineage titleId="t-1" />);
    fireEvent.click(screen.getByRole("button", { name: /Audit history/i }));
    expect(await screen.findByText(/No recorded history/i)).toBeInTheDocument();
  });
});