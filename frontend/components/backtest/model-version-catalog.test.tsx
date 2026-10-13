import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { ModelVersionCatalog } from "./model-version-catalog";
import type { ModelVersion } from "@/lib/types";

const { listModelVersions, activateModelVersion } = vi.hoisted(() => ({
  listModelVersions: vi.fn(),
  activateModelVersion: vi.fn(),
}));

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, api: { listModelVersions, activateModelVersion } };
});

function version(overrides: Partial<ModelVersion>): ModelVersion {
  return {
    model_version_id: "mv-1",
    talent_pedigree_weight: "0.60",
    narrative_trope_weight: "0.40",
    guardrail_params: {},
    supersedes_id: null,
    is_active: false,
    created_at: "2026-10-10T00:00:00Z",
    ...overrides,
  };
}

describe("ModelVersionCatalog (R26.3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listModelVersions.mockResolvedValue([
      version({ model_version_id: "mv-2", is_active: true, talent_pedigree_weight: "0.65" }),
      version({ model_version_id: "mv-1", is_active: false }),
    ]);
    activateModelVersion.mockResolvedValue(version({ model_version_id: "mv-1", is_active: true }));
  });

  it("lists versions with the active one flagged and prior ones rollback-able", async () => {
    render(<ModelVersionCatalog />);
    expect(await screen.findByText("Active")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Roll back to this/i }),
    ).toBeInTheDocument();
  });

  it("rolls back to a prior version and reloads the catalog", async () => {
    render(<ModelVersionCatalog />);
    const btn = await screen.findByRole("button", { name: /Roll back to this/i });
    fireEvent.click(btn);
    await waitFor(() => expect(activateModelVersion).toHaveBeenCalledWith("mv-1"));
    // Catalog reloaded (list called on mount + after rollback).
    await waitFor(() => expect(listModelVersions).toHaveBeenCalledTimes(2));
  });
});