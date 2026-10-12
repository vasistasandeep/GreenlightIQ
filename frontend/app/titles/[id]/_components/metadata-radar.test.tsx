import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

/**
 * MetadataRadar component tests (R15.1).
 *
 * Recharts renders through a `ResponsiveContainer` that measures its parent via
 * ResizeObserver, which jsdom does not implement — the chart would collapse to
 * zero size and skip rendering. We mock `recharts` with trivial pass-through
 * elements so the chart subtree mounts deterministically; the component's own
 * data projection (`buildRadarData`) and the accessible summary list are what we
 * actually assert on.
 */

vi.mock("recharts", () => {
  const Passthrough = ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  );
  const Leaf = () => null;
  return {
    ResponsiveContainer: Passthrough,
    RadarChart: Passthrough,
    Radar: Leaf,
    PolarGrid: Leaf,
    PolarAngleAxis: Leaf,
    PolarRadiusAxis: Leaf,
    Tooltip: Leaf,
  };
});

import { MetadataRadar, buildRadarData } from "./metadata-radar";
import type { MetadataBreakdown } from "@/lib/types";

const FULL_BREAKDOWN: MetadataBreakdown = {
  affective_primary: "tension",
  affective_secondary: "hope",
  talent_pedigree_score: 7.5,
  production_scale_metric: 6,
  narrative_dna_dimensions: 1536,
  extraction_status: "COMPLETED",
};

describe("buildRadarData (R15.1)", () => {
  it("projects all four metadata dimensions onto the 0-10 axis", () => {
    const data = buildRadarData(FULL_BREAKDOWN);
    expect(data.map((d) => d.dimension)).toEqual([
      "Narrative DNA",
      "Affective Tone",
      "Talent Pedigree",
      "Production Scale",
    ]);
  });

  it("scales a complete 1536-dim embedding to the full Narrative DNA score", () => {
    const data = buildRadarData(FULL_BREAKDOWN);
    const narrative = data.find((d) => d.dimension === "Narrative DNA")!;
    expect(narrative.score).toBe(10);
    expect(narrative.derived).toBe(true);
  });

  it("scores Affective Tone from the count of extracted triggers", () => {
    const both = buildRadarData(FULL_BREAKDOWN);
    expect(both.find((d) => d.dimension === "Affective Tone")!.score).toBe(10);

    const one = buildRadarData({
      ...FULL_BREAKDOWN,
      affective_secondary: null,
    });
    expect(one.find((d) => d.dimension === "Affective Tone")!.score).toBe(5);

    const none = buildRadarData({
      ...FULL_BREAKDOWN,
      affective_primary: null,
      affective_secondary: null,
    });
    expect(none.find((d) => d.dimension === "Affective Tone")!.score).toBe(0);
  });

  it("passes talent-pedigree and production-scale scores through, coercing strings", () => {
    const data = buildRadarData({
      ...FULL_BREAKDOWN,
      talent_pedigree_score: "8.25",
      production_scale_metric: 3,
    });
    expect(data.find((d) => d.dimension === "Talent Pedigree")!.score).toBe(8.25);
    expect(data.find((d) => d.dimension === "Production Scale")!.score).toBe(3);
  });

  it("marks dimensions non-derived and scores them 0 when the breakdown is null", () => {
    const data = buildRadarData(null);
    expect(data).toHaveLength(4);
    expect(data.every((d) => d.derived === false)).toBe(true);
    expect(data.every((d) => d.score === 0)).toBe(true);
  });
});

describe("MetadataRadar (R15.1)", () => {
  it("renders the radar section heading and 0-10 scale note", () => {
    render(<MetadataRadar breakdown={FULL_BREAKDOWN} />);
    expect(
      screen.getByRole("heading", { name: "Metadata profile" }),
    ).toBeInTheDocument();
    expect(screen.getByText("0–10 scale")).toBeInTheDocument();
  });

  it("renders the four labelled dimensions with their derived scores", () => {
    render(<MetadataRadar breakdown={FULL_BREAKDOWN} />);
    const list = screen.getByRole("heading", {
      name: "Metadata profile",
    }).closest("section")!;

    for (const dimension of [
      "Narrative DNA",
      "Affective Tone",
      "Talent Pedigree",
      "Production Scale",
    ]) {
      expect(within(list).getByText(dimension)).toBeInTheDocument();
    }
    // Talent pedigree 7.5 formatted to one decimal.
    expect(within(list).getByText("7.5")).toBeInTheDocument();
    // Production scale 6 formatted to one decimal.
    expect(within(list).getByText("6.0")).toBeInTheDocument();
  });

  it("exposes the chart with an accessible image role and label", () => {
    render(<MetadataRadar breakdown={FULL_BREAKDOWN} />);
    expect(
      screen.getByRole("img", { name: "Metadata profile radar chart" }),
    ).toBeInTheDocument();
  });

  it("renders an empty-state message and no chart when no dimension is derivable", () => {
    render(<MetadataRadar breakdown={null} />);
    expect(
      screen.getByText(/No metadata profile is available for this title yet/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
