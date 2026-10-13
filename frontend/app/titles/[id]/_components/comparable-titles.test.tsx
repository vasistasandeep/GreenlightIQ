import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { ComparableTitlesPanel } from "./comparable-titles";
import type { ComparableTitles } from "@/lib/types";

/**
 * ComparableTitlesPanel tests (Top 3 Historical Comps, R2.6).
 *
 * The panel fetches comps on mount, renders each neighbour as a ranked link
 * carrying a recommendation badge and a similarity percentage, and shows a
 * graceful empty state when the title has no embedding or no neighbours.
 */

const { getComps } = vi.hoisted(() => ({ getComps: vi.fn() }));

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>(
    "@/lib/api-client",
  );
  return { ...actual, api: { getComps } };
});

function payload(overrides: Partial<ComparableTitles> = {}): ComparableTitles {
  return {
    title_id: "t-1",
    found: true,
    comps: [
      {
        title_id: "n-1",
        title_name: "Neighbour One",
        genre_tag: "DRAMA",
        recommendation_status: "GREENLIGHT",
        cosine_similarity: 0.9123,
      },
      {
        title_id: "n-2",
        title_name: "Neighbour Two",
        genre_tag: "THRILLER",
        recommendation_status: null,
        cosine_similarity: 0.8011,
      },
    ],
    ...overrides,
  };
}

describe("ComparableTitlesPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders ranked comps with name, similarity %, and a link to each title", async () => {
    getComps.mockResolvedValue(payload());
    render(<ComparableTitlesPanel titleId="t-1" />);

    await waitFor(() => expect(screen.getByText("Neighbour One")).toBeInTheDocument());
    expect(screen.getByText("Neighbour Two")).toBeInTheDocument();
    // Cosine 0.9123 -> 91.2% affinity.
    expect(screen.getByText("91.2%")).toBeInTheDocument();

    const link = screen.getByText("Neighbour One").closest("a");
    expect(link).toHaveAttribute("href", "/titles/n-1");
  });

  it("shows a pending badge for a neighbour with no computed valuation", async () => {
    getComps.mockResolvedValue(payload());
    render(<ComparableTitlesPanel titleId="t-1" />);
    await waitFor(() => expect(screen.getByText("Neighbour Two")).toBeInTheDocument());
    // RecommendationBadge renders PENDING for a null status.
    expect(screen.getByText("PENDING")).toBeInTheDocument();
  });

  it("renders an empty state when the title has no embedding", async () => {
    getComps.mockResolvedValue(payload({ found: false, comps: [] }));
    render(<ComparableTitlesPanel titleId="t-1" />);
    await waitFor(() =>
      expect(screen.getByText(/no Narrative_DNA embedding yet/i)).toBeInTheDocument(),
    );
  });

  it("renders an error state when the request fails", async () => {
    getComps.mockRejectedValue(new Error("boom"));
    render(<ComparableTitlesPanel titleId="t-1" />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        /could not load comparable titles/i,
      ),
    );
  });
});