"use client";

import {
  PolarAngleAxis,
  PolarGrid,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from "recharts";

import type { MetadataProfile } from "@/lib/types";
import { num } from "./helpers";

/** Metadata Vector Profile radar (0-10). Derived axes for the instant view. */
export function StudioRadar({ profile }: { profile: MetadataProfile }) {
  const data = [
    { axis: "Narrative DNA", value: num(profile.narrative_dna) ?? 0 },
    { axis: "Affective Tone", value: num(profile.affective_tone) ?? 0 },
    { axis: "Talent Pedigree", value: num(profile.talent_pedigree) ?? 0 },
    { axis: "Production Scale", value: num(profile.production_scale) ?? 0 },
    { axis: "Cultural Portability", value: num(profile.cultural_portability) ?? 0 },
  ];
  return (
    <div className="h-64 w-full" role="img" aria-label="Metadata vector profile radar">
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={data} outerRadius="70%">
          <PolarGrid stroke="#1e293b" />
          <PolarAngleAxis
            dataKey="axis"
            tick={{ fill: "#94a3b8", fontSize: 11 }}
          />
          <Radar
            dataKey="value"
            stroke="#10b981"
            fill="#10b981"
            fillOpacity={0.35}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}