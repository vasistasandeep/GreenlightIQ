import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// Mock the route so the Context_Chip shows the portfolio scope by default.
const pathname = vi.hoisted(() => ({ value: "/dashboard" }));
vi.mock("next/navigation", () => ({
  usePathname: () => pathname.value,
}));

const { chat } = vi.hoisted(() => ({ chat: vi.fn() }));
vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>(
    "@/lib/api-client",
  );
  return { ...actual, api: { chat }, ApiError: actual.ApiError };
});

import { ChatWidget } from "./chat-widget";

describe("ChatWidget", () => {
  beforeEach(() => {
    chat.mockReset();
    pathname.value = "/dashboard";
  });

  function open() {
    render(<ChatWidget />);
    fireEvent.click(screen.getByLabelText("Open CineROI Copilot"));
  }

  it("sends a message and renders the grounded answer with a source chip", async () => {
    chat.mockResolvedValue({
      answer: "The Ledger is NEGOTIATE HARD because its LTV is below the floor.",
      sources: ["title:abc", "doc:how-to-batch-slate"],
    });
    open();

    fireEvent.change(screen.getByLabelText("Ask the assistant"), {
      target: { value: "why did The Ledger fail?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(screen.getByText(/NEGOTIATE HARD because its LTV/)).toBeInTheDocument(),
    );
    expect(chat).toHaveBeenCalledTimes(1);
    // A how-to source renders as a readable citation chip.
    expect(screen.getByText(/Help: batch slate/i)).toBeInTheDocument();
  });

  it("shows a readable error and stays usable when the request fails", async () => {
    chat.mockRejectedValue(new Error("network down"));
    open();

    fireEvent.change(screen.getByLabelText("Ask the assistant"), {
      target: { value: "hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    // Input remains usable for the next question.
    expect(screen.getByLabelText("Ask the assistant")).not.toBeDisabled();
  });

  it("reflects the title scope in the Context chip on a title page", () => {
    pathname.value = "/titles/7b1c3771-aaaa";
    open();
    expect(screen.getByText(/This title - read-only/)).toBeInTheDocument();
  });

  it("shows the portfolio scope on non-title routes", () => {
    open();
    expect(screen.getByText(/Portfolio overview - read-only/)).toBeInTheDocument();
  });

  it("renders follow-up chips and sends one when clicked", async () => {
    chat
      .mockResolvedValueOnce({
        answer: "The Ledger is NEGOTIATE HARD.",
        sources: ["title:abc"],
        follow_ups: ["How is The Ledger's churn calculated?"],
      })
      .mockResolvedValueOnce({
        answer: "Churn is built additively from several drivers.",
        sources: ["doc:concept-churn"],
        follow_ups: [],
      });
    open();

    fireEvent.change(screen.getByLabelText("Ask the assistant"), {
      target: { value: "tell me about The Ledger" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    const chip = await screen.findByRole("button", {
      name: /How is The Ledger's churn calculated\?/,
    });
    expect(chip).toBeInTheDocument();

    fireEvent.click(chip);
    await waitFor(() => expect(chat).toHaveBeenCalledTimes(2));
    expect(chat.mock.calls[1][0].message).toMatch(/How is The Ledger's churn/);
  });
});