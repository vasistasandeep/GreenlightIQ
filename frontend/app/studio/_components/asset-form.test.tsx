import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import type { ParsedPitch } from "@/lib/types";

// Mock the typed API client so the pitch-prefill path returns a canned parse.
const { parsePitch } = vi.hoisted(() => ({ parsePitch: vi.fn() }));
vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>(
    "@/lib/api-client",
  );
  return { ...actual, api: { parsePitch }, ApiError: actual.ApiError };
});

import { AssetForm } from "./asset-form";

const emptyParse: ParsedPitch = {
  title_name: null,
  synopsis: null,
  genre_tag: null,
  acquisition_cost_or_budget: null,
  native_currency: null,
  is_exclusive: null,
  source_text_preview: null,
};

describe("AssetForm — Advanced drivers section", () => {
  beforeEach(() => {
    parsePitch.mockReset();
  });

  function renderForm() {
    const onSubmit = vi.fn();
    render(<AssetForm onSubmit={onSubmit} submitting={false} />);
    return { onSubmit };
  }

  const buzz = () => screen.getByLabelText("Buzz Level") as HTMLSelectElement;
  const stage = () => screen.getByLabelText("Production Stage") as HTMLSelectElement;

  it("disables and annotates Buzz_Level for CONCEPT_SCRIPT (STAGE_EXCLUDED)", () => {
    renderForm();
    fireEvent.change(stage(), { target: { value: "CONCEPT_SCRIPT" } });
    expect(buzz()).toBeDisabled();
    expect(screen.getByText(/Inactive in early stage \(STAGE_EXCLUDED\)/i)).toBeInTheDocument();
  });

  it("disables Buzz_Level for IN_PRODUCTION", () => {
    renderForm();
    fireEvent.change(stage(), { target: { value: "IN_PRODUCTION" } });
    expect(buzz()).toBeDisabled();
  });

  it("enables Buzz_Level for FESTIVAL_PREVIEW and ACQUISITION_READY", () => {
    renderForm();
    fireEvent.change(stage(), { target: { value: "FESTIVAL_PREVIEW" } });
    expect(buzz()).not.toBeDisabled();
    expect(
      screen.queryByText(/Inactive in early stage/i),
    ).not.toBeInTheDocument();

    fireEvent.change(stage(), { target: { value: "ACQUISITION_READY" } });
    expect(buzz()).not.toBeDisabled();
  });

  it("reveals lineage parent fields only when is_franchise is on (R1.6)", () => {
    renderForm();
    expect(screen.queryByLabelText("Franchise Order")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Parent Viewing Hours")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Parent Completion (0-1)")).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/Franchise entry/i));

    expect(screen.getByLabelText("Franchise Order")).toBeInTheDocument();
    expect(screen.getByLabelText("Parent Viewing Hours")).toBeInTheDocument();
    expect(screen.getByLabelText("Parent Completion (0-1)")).toBeInTheDocument();

    // Toggling back off hides them again.
    fireEvent.click(screen.getByLabelText(/Franchise entry/i));
    expect(screen.queryByLabelText("Franchise Order")).not.toBeInTheDocument();
  });

  it("pitch prefill populates the Advanced-drivers controls (R4.6)", async () => {
    parsePitch.mockResolvedValue({
      ...emptyParse,
      title_name: "Apex Horizon II",
      is_franchise: true,
      franchise_order: 2,
      production_stage: "ACQUISITION_READY",
      source_ip_provenance: "BESTSELLER_BOOK",
      release_window: "THEATRICAL_30D",
    } satisfies ParsedPitch);

    const { container } = render(
      <AssetForm onSubmit={vi.fn()} submitting={false} />,
    );
    const fileInput = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const file = new File(["%PDF-1.4"], "pitch.pdf", { type: "application/pdf" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => expect(parsePitch).toHaveBeenCalledTimes(1));

    // Franchise toggle flipped on, revealing and populating franchise_order.
    await waitFor(() =>
      expect(screen.getByLabelText("Franchise Order")).toHaveValue(2),
    );
    expect(stage()).toHaveValue("ACQUISITION_READY");
    expect(screen.getByLabelText("Source IP Provenance")).toHaveValue("BESTSELLER_BOOK");
    expect(screen.getByLabelText("Release Window")).toHaveValue("THEATRICAL_30D");
    // The parse note mentions the recognized driver facts.
    expect(
      screen.getByText(/Pre-filled .*franchise.*from the pitch/i),
    ).toBeInTheDocument();
  });

  it("leaves driver controls empty when the pitch recognizes no driver facts (R4.5)", async () => {
    parsePitch.mockResolvedValue({
      ...emptyParse,
      title_name: "Standalone Drama",
    } satisfies ParsedPitch);

    const { container } = render(
      <AssetForm onSubmit={vi.fn()} submitting={false} />,
    );
    const fileInput = container.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    const file = new File(["%PDF-1.4"], "pitch.pdf", { type: "application/pdf" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => expect(parsePitch).toHaveBeenCalledTimes(1));
    // No franchise => parent fields stay hidden; selects stay unset.
    expect(screen.queryByLabelText("Franchise Order")).not.toBeInTheDocument();
    expect(stage()).toHaveValue("");
    expect(screen.getByLabelText("Source IP Provenance")).toHaveValue("");
    expect(screen.getByLabelText("Release Window")).toHaveValue("");
  });
});
