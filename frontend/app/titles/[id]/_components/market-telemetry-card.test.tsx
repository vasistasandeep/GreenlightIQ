import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { MarketTelemetryCard } from "./market-telemetry-card";
import type { MarketTelemetry } from "@/lib/types";

/**
 * MarketTelemetryCard tests (R13.3, R13.4).
 *
 * The card fetches telemetry for the title's genre/territory, renders the three
 * indices, flags a stale source, shows an empty state when the pair was never
 * polled, and renders nothing when the title has no genre/territory.
 */

const { getTelemetry } = vi.hoisted(() => ({ getTelemetry: vi.fn() }));

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>(
    "@/lib/api-client",
  );
  return { ...actual, api: { getTelemetry } };
});

function telemetry(overrides: Partial<MarketTelemetry> = {}): MarketTelemetry {
  return {
    genre_tag: "sci-fi",
    territory: "US",
    social_sentiment_index: "0.72",
    chart_velocity_score: "6.0",
    licensing_inflation_multiplier: "1.080",
    source_available: true,
    found: true,
    ...overrides,
  };
}

describe("MarketTelemetryCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the three telemetry indices for the genre/territory", async () => {
    getTelemetry.mockResolvedValue(telemetry());
    render(<MarketTelemetryCard genre="sci-fi" territory="US" />);

    await waitFor(() => expect(screen.getByText("0.72")).toBeInTheDocument());
    expect(screen.getByText("6.0")).toBeInTheDocument();
    expect(screen.getByText("1.080x")).toBeInTheDocument();
    expect(getTelemetry).toHaveBeenCalledWith("sci-fi", "US");
  });

  it("flags a stale source when the last poll was unavailable", async () => {
    getTelemetry.mockResolvedValue(telemetry({ source_available: false }));
    render(<MarketTelemetryCard genre="sci-fi" territory="US" />);
    await waitFor(() =>
      expect(screen.getByText(/retained from the previous successful poll/i)).toBeInTheDocument(),
    );
  });

  it("shows an empty state when the pair has never been polled", async () => {
    getTelemetry.mockResolvedValue(
      telemetry({ found: false, social_sentiment_index: null, chart_velocity_score: null, licensing_inflation_multiplier: null }),
    );
    render(<MarketTelemetryCard genre="sci-fi" territory="US" />);
    await waitFor(() =>
      expect(screen.getByText(/no telemetry has been polled/i)).toBeInTheDocument(),
    );
  });

  it("renders nothing when the title has no genre/territory", () => {
    const { container } = render(
      <MarketTelemetryCard genre={null} territory={null} />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(getTelemetry).not.toHaveBeenCalled();
  });
});