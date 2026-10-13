import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  RecommendationBadge,
  recommendationLabel,
} from "@/components/recommendation-badge";
import type { RecommendationStatus } from "@/lib/types";

/**
 * RecommendationBadge mapping tests (R14.3).
 *
 * R14.3 requires the badge to render as GREENLIGHT, NEGOTIATE HARD, or PASS
 * according to the title's recommendation status. The underscore in the
 * `NEGOTIATE_HARD` enum must be dropped in the display label.
 */

describe("recommendationLabel (R14.3)", () => {
  it.each<[RecommendationStatus, string]>([
    ["GREENLIGHT", "GREENLIGHT"],
    ["NEGOTIATE_HARD", "NEGOTIATE HARD"],
    ["PASS", "PASS"],
  ])("maps %s to the executive label %s", (status, label) => {
    expect(recommendationLabel(status)).toBe(label);
  });

  it("falls back to PENDING for null or undefined", () => {
    expect(recommendationLabel(null)).toBe("PENDING");
    expect(recommendationLabel(undefined)).toBe("PENDING");
  });
});

describe("RecommendationBadge (R14.3)", () => {
  it.each<[RecommendationStatus, string]>([
    ["GREENLIGHT", "GREENLIGHT"],
    ["NEGOTIATE_HARD", "NEGOTIATE HARD"],
    ["PASS", "PASS"],
  ])("renders %s as the %s badge", (status, label) => {
    render(<RecommendationBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("renders a PENDING badge when the status is null", () => {
    render(<RecommendationBadge status={null} />);
    expect(screen.getByText("PENDING")).toBeInTheDocument();
  });

  it("spells out NEGOTIATE HARD without an underscore", () => {
    render(<RecommendationBadge status="NEGOTIATE_HARD" />);
    expect(screen.getByText("NEGOTIATE HARD")).toBeInTheDocument();
    expect(screen.queryByText("NEGOTIATE_HARD")).not.toBeInTheDocument();
  });

  it("renders a status icon so meaning is not color-only (a11y)", () => {
    const { container } = render(
      <RecommendationBadge status="GREENLIGHT" data-testid="badge" />,
    );
    // A decorative SVG icon accompanies the label on every status.
    const icon = container.querySelector("svg");
    expect(icon).not.toBeNull();
    expect(icon).toHaveAttribute("aria-hidden");
  });

  it("forwards extra props and merges className onto the badge", () => {
    render(
      <RecommendationBadge
        status="GREENLIGHT"
        className="custom-class"
        data-testid="badge"
      />,
    );
    const badge = screen.getByTestId("badge");
    expect(badge).toHaveClass("custom-class");
    expect(badge).toHaveTextContent("GREENLIGHT");
  });
});
