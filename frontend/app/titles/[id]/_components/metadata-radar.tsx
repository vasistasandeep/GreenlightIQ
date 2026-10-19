"use client";

/**
 * MetadataRadar (R15.1).
 *
 * Renders a Recharts `RadarChart` of the four metadata dimensions — Narrative DNA,
 * Affective Tone, Talent Pedigree, Production Scale — on a shared 0-10 axis.
 *
 * The backend exposes talent-pedigree and production-scale as 0-10 scores directly
 * (`metadata_vectors` CHECK 0.00-10.00). Narrative DNA and Affective Tone are
 * qualitative/high-dimensional; we project them onto the same 0-10 axis so the
 * executive sees a single comparable profile:
 *   - Narrative DNA: scaled from the extracted embedding's presence/completeness.
 *   - Affective Tone: scaled from how many affective triggers were extracted.
 * When a dimension cannot be derived it renders at 0 with a muted note.
 */

import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

import type { MetadataBreakdown } from "@/lib/types";
import { toNumber } from "./format";

const AXIS_MAX = 10;

/** The full 1536-dim embedding scores a complete Narrative DNA profile. */
const NARRATIVE_DNA_FULL_DIMS = 1536;

export interface MetadataRadarDatum {
  dimension: string;
  score: number;
  /** `true` when the score could not be derived from the breakdown. */
  derived: boolean;
}

/** Project the metadata breakdown onto the four 0-10 radar axes (R15.1). */
export function buildRadarData(
  breakdown: MetadataBreakdown | null,
): MetadataRadarDatum[] {
  const talent = toNumber(breakdown?.talent_pedigree_score ?? null);
  const production = toNumber(breakdown?.production_scale_metric ?? null);

  // Narrative DNA: completeness of the extracted embedding, scaled to 0-10.
  const dims = breakdown?.narrative_dna_dimensions ?? null;
  const narrativeScore =
    dims && dims > 0
      ? Math.min(AXIS_MAX, (dims / NARRATIVE_DNA_FULL_DIMS) * AXIS_MAX)
      : null;

  // Affective Tone: presence of primary/secondary triggers (0, 5, or 10).
  const affectiveCount =
    (breakdown?.affective_primary ? 1 : 0) +
    (breakdown?.affective_secondary ? 1 : 0);
  const affectiveScore =
    breakdown == null ? null : (affectiveCount / 2) * AXIS_MAX;

  return [
    {
      dimension: "Narrative DNA",
      score: narrativeScore ?? 0,
      derived: narrativeScore !== null,
    },
    {
      dimension: "Affective Tone",
      score: affectiveScore ?? 0,
      derived: affectiveScore !== null,
    },
    {
      dimension: "Talent Pedigree",
      score: talent ?? 0,
      derived: talent !== null,
    },
    {
      dimension: "Production Scale",
      score: production ?? 0,
      derived: production !== null,
    },
  ];
}

export interface MetadataRadarProps {
  breakdown: MetadataBreakdown | null;
}

export function MetadataRadar({ breakdown }: MetadataRadarProps) {
  const data = buildRadarData(breakdown);
  const anyDerived = data.some((d) => d.derived);

  return (
    <section
      aria-labelledby="metadata-radar-heading"
      className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 shadow-sm shadow-black/20"
    >
      <div className="mb-3 flex items-baseline justify-between">
        <h2 id="metadata-radar-heading" className="text-lg font-semibold">
          Metadata profile
        </h2>
        <span className="text-xs text-muted-foreground">0–10 scale</span>
      </div>

      {!anyDerived ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          No metadata profile is available for this title yet.
        </p>
      ) : (
        <>
          <div className="h-72 w-full" role="img" aria-label="Metadata profile radar chart">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={data} outerRadius="65%">
                <PolarGrid />
                <PolarAngleAxis dataKey="dimension" tick={{ fontSize: 12 }} />
                <PolarRadiusAxis domain={[0, AXIS_MAX]} tick={{ fontSize: 10 }} />
                <Radar
                  name="Score"
                  dataKey="score"
                  stroke="hsl(222.2 47.4% 11.2%)"
                  fill="hsl(222.2 47.4% 11.2%)"
                  fillOpacity={0.3}
                />
                <Tooltip
                  formatter={(value: number | string) =>
                    [`${Number(value).toFixed(1)} / ${AXIS_MAX}`, "Score"] as [
                      string,
                      string,
                    ]
                  }
                />
              </RadarChart>
            </ResponsiveContainer>
          </div>

          <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            {data.map((d) => (
              <div key={d.dimension} className="flex items-center justify-between">
                <dt className="text-muted-foreground">{d.dimension}</dt>
                <dd className="font-medium tabular-nums">
                  {d.derived ? d.score.toFixed(1) : "—"}
                </dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </section>
  );
}
