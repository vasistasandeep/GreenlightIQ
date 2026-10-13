import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { OverridePanel } from "./override-panel";

const { getTitleDecision, overrideDecision } = vi.hoisted(() => ({
  getTitleDecision: vi.fn(),
  overrideDecision: vi.fn(),
}));

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, api: { getTitleDecision, overrideDecision } };
});

describe("OverridePanel (R20.2)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getTitleDecision.mockResolvedValue({ title_id: "t-1", decision_id: "d-1" });
    overrideDecision.mockResolvedValue({
      decision_id: "d-1",
      previous_status: "PASS",
      recommendation_status: "GREENLIGHT",
    });
  });

  it("opens the form and blocks submit without a justification", async () => {
    render(<OverridePanel titleId="t-1" currentStatus="PASS" />);
    fireEvent.click(screen.getByRole("button", { name: /Override recommendation/i }));
    fireEvent.click(screen.getByRole("button", { name: /Record override/i }));
    expect(await screen.findByText(/business justification is required/i)).toBeInTheDocument();
    expect(overrideDecision).not.toHaveBeenCalled();
  });

  it("resolves the decision id and posts the override with justification", async () => {
    const onOverridden = vi.fn();
    render(<OverridePanel titleId="t-1" currentStatus="PASS" onOverridden={onOverridden} />);
    fireEvent.click(screen.getByRole("button", { name: /Override recommendation/i }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "GREENLIGHT" } });
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Director brings prestige and awards potential." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Record override/i }));

    await waitFor(() => expect(overrideDecision).toHaveBeenCalledWith("d-1", {
      recommendation_status: "GREENLIGHT",
      justification: "Director brings prestige and awards potential.",
    }));
    expect(onOverridden).toHaveBeenCalledWith("GREENLIGHT");
    expect(await screen.findByText(/Override recorded/i)).toBeInTheDocument();
  });
});