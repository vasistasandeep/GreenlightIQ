"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import type { AssetType, QuickEvaluateRequest } from "@/lib/types";

const ASSET_TYPES: { value: AssetType; label: string }[] = [
  { value: "ORIGINAL_SERIES", label: "ORIGINAL_SERIES" },
  { value: "ORIGINAL_FILM", label: "ORIGINAL_FILM" },
  { value: "LICENSED_LIBRARY", label: "LICENSED_LIBRARY" },
  { value: "CO_PRODUCTION", label: "CO_PRODUCTION" },
];

const CURRENCIES = ["USD", "INR", "EUR", "GBP"];

const TERRITORIES = [
  { code: "IN", label: "India" },
  { code: "NA", label: "North America" },
  { code: "EU", label: "Europe" },
  { code: "SEA", label: "SE Asia" },
  { code: "GLOBAL", label: "Global" },
];

const PRESETS: Record<string, Partial<QuickEvaluateRequest>> = {
  "Bengaluru S1": {
    title_name: "The Bengaluru Syndicate (S1)",
    asset_type: "ORIGINAL_SERIES",
    acquisition_cost_or_budget: 1_250_000,
    native_currency: "USD",
    target_territories: ["IN", "SEA"],
    synopsis:
      "A gritty, fast-paced urban crime-noir saga delving into Bangalore's underground syndicate and the detectives who hunt it. A breakout ensemble and a festival-circuit showrunner anchor a bingeable eight-episode arc built for subscriber retention.",
    genre_tag: "Crime-Noir",
    talent_pedigree_score: 7.5,
    license_duration_months: 24,
    is_exclusive: true,
  },
  "Apex Horizon (High-Budget)": {
    title_name: "Apex Horizon",
    asset_type: "ORIGINAL_FILM",
    acquisition_cost_or_budget: 42_000_000,
    native_currency: "USD",
    target_territories: ["GLOBAL"],
    synopsis:
      "A sweeping, four-quadrant sci-fi thriller: a marooned crew races a collapsing orbital station as a rival syndicate closes in. A-list leads and a tentpole director make this a global marquee event with blockbuster franchise upside.",
    genre_tag: "Sci-Fi Thriller",
    talent_pedigree_score: 9.0,
    license_duration_months: 36,
    is_exclusive: true,
  },
  "Vintage Reruns (Library)": {
    title_name: "Vintage Reruns Vol. 7",
    asset_type: "LICENSED_LIBRARY",
    acquisition_cost_or_budget: 1_200_000,
    native_currency: "EUR",
    target_territories: ["EU", "NA"],
    synopsis:
      "A nostalgia-driven catalogue bundle of beloved mid-budget library titles - comfort-viewing filler that broadens the back-catalogue tail without headline spend.",
    genre_tag: "Comedy-Classic",
    talent_pedigree_score: 4.0,
    license_duration_months: 12,
    is_exclusive: false,
  },
};

const labelCls = "mb-1 block text-xs font-medium uppercase tracking-wide text-slate-400";
const fieldCls =
  "w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 " +
  "placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500";

export interface AssetFormProps {
  onSubmit: (payload: QuickEvaluateRequest) => void | Promise<void>;
  submitting: boolean;
}

export function AssetForm({ onSubmit, submitting }: AssetFormProps) {
  const [titleName, setTitleName] = useState("");
  const [assetType, setAssetType] = useState<AssetType>("ORIGINAL_SERIES");
  const [cost, setCost] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [territories, setTerritories] = useState<string[]>([]);
  const [synopsis, setSynopsis] = useState("");
  const [genre, setGenre] = useState("");
  const [viewingHours, setViewingHours] = useState("");
  const [pedigree, setPedigree] = useState("5.0");
  const [duration, setDuration] = useState("24");
  const [exclusive, setExclusive] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function toggleTerritory(code: string) {
    setTerritories((prev) =>
      prev.includes(code) ? prev.filter((t) => t !== code) : [...prev, code],
    );
  }

  function applyPreset(name: string) {
    const p = PRESETS[name];
    if (!p) return;
    setTitleName(p.title_name ?? "");
    setAssetType((p.asset_type as AssetType) ?? "ORIGINAL_SERIES");
    setCost(String(p.acquisition_cost_or_budget ?? ""));
    setCurrency(p.native_currency ?? "USD");
    setTerritories(p.target_territories ?? []);
    setSynopsis(p.synopsis ?? "");
    setGenre(p.genre_tag ?? "");
    setPedigree(String(p.talent_pedigree_score ?? "5.0"));
    setDuration(String(p.license_duration_months ?? "24"));
    setExclusive(Boolean(p.is_exclusive));
    setError(null);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!titleName.trim()) return setError("Title name is required.");
    if (!synopsis.trim()) return setError("A logline / synopsis is required.");
    const costN = Number(cost);
    if (!Number.isFinite(costN) || costN < 0.01 || costN > 999_999_999.99) {
      return setError("Cost must be between 0.01 and 999,999,999.99.");
    }

    const payload: QuickEvaluateRequest = {
      title_name: titleName.trim(),
      asset_type: assetType,
      acquisition_cost_or_budget: costN,
      native_currency: currency,
      target_territories: territories,
      synopsis: synopsis.trim(),
      genre_tag: genre.trim() || null,
      projected_viewing_hours: viewingHours ? Number(viewingHours) : null,
      talent_pedigree_score: pedigree ? Number(pedigree) : null,
      license_duration_months: duration ? Number(duration) : null,
      is_exclusive: exclusive,
    };
    void onSubmit(payload);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div>
        <label htmlFor="f-title" className={labelCls}>Title Name</label>
        <input id="f-title" className={fieldCls} value={titleName}
          onChange={(e) => setTitleName(e.target.value)} placeholder="The Bengaluru Syndicate (S1)" />
      </div>

      <div>
        <label htmlFor="f-asset" className={labelCls}>Asset Type</label>
        <select id="f-asset" className={fieldCls} value={assetType}
          onChange={(e) => setAssetType(e.target.value as AssetType)}>
          {ASSET_TYPES.map((a) => (
            <option key={a.value} value={a.value}>{a.label}</option>
          ))}
        </select>
      </div>

      <div>
        <label className={labelCls}>Cost &amp; Currency</label>
        <div className="flex gap-2">
          <input className={fieldCls} inputMode="decimal" value={cost}
            onChange={(e) => setCost(e.target.value)} placeholder="1,200,000" aria-label="Acquisition cost" />
          <select className={cn(fieldCls, "w-24")} value={currency}
            onChange={(e) => setCurrency(e.target.value)} aria-label="Currency">
            {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      </div>

      <div>
        <label className={labelCls}>Target Territories</label>
        <div className="flex flex-wrap gap-2">
          {TERRITORIES.map((t) => {
            const on = territories.includes(t.code);
            return (
              <button type="button" key={t.code} onClick={() => toggleTerritory(t.code)}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                  on
                    ? "border-emerald-500 bg-emerald-500/15 text-emerald-300"
                    : "border-slate-700 bg-slate-950 text-slate-400 hover:border-slate-500",
                )}>
                {t.label}
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <label htmlFor="f-synopsis" className={labelCls}>Logline / Synopsis</label>
        <textarea id="f-synopsis" className={cn(fieldCls, "min-h-20 resize-y")} value={synopsis}
          onChange={(e) => setSynopsis(e.target.value)}
          placeholder="A gritty, fast-paced urban crime-noir saga..." />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="f-genre" className={labelCls}>Genre &amp; Tags</label>
          <input id="f-genre" className={fieldCls} value={genre}
            onChange={(e) => setGenre(e.target.value)} placeholder="Crime-Noir" />
        </div>
        <div>
          <label htmlFor="f-hours" className={labelCls}>Viewing Hours (opt.)</label>
          <input id="f-hours" className={fieldCls} inputMode="decimal" value={viewingHours}
            onChange={(e) => setViewingHours(e.target.value)} placeholder="estimated" />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="f-ped" className={labelCls}>Talent Pedigree: {pedigree}</label>
          <input id="f-ped" type="range" min="0" max="10" step="0.5" value={pedigree}
            onChange={(e) => setPedigree(e.target.value)} className="w-full accent-emerald-500" />
        </div>
        <div>
          <label htmlFor="f-dur" className={labelCls}>License (months)</label>
          <input id="f-dur" className={fieldCls} inputMode="numeric" value={duration}
            onChange={(e) => setDuration(e.target.value)} placeholder="24" />
        </div>
      </div>

      <label className="flex items-center gap-2 text-sm text-slate-300">
        <input type="checkbox" checked={exclusive}
          onChange={(e) => setExclusive(e.target.checked)} className="accent-emerald-500" />
        Exclusive SVOD
      </label>

      <div>
        <span className={labelCls}>Quick Presets</span>
        <div className="flex flex-wrap gap-2">
          {Object.keys(PRESETS).map((name) => (
            <button type="button" key={name} onClick={() => applyPreset(name)}
              className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1 text-xs text-slate-300 hover:border-emerald-500 hover:text-emerald-300">
              [ Load {name} ]
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <p role="alert" className="text-sm font-medium text-rose-400">{error}</p>
      ) : null}

      <button type="submit" disabled={submitting}
        className={cn(
          "mt-1 w-full rounded-md px-4 py-2.5 text-sm font-bold transition-colors",
          submitting
            ? "cursor-not-allowed bg-slate-700 text-slate-400"
            : "bg-emerald-500 text-emerald-950 hover:bg-emerald-400",
        )}>
        {submitting ? "Deconstructing Narrative DNA & Running Guardrails..." : "[ RUN ROI VALUATION ]"}
      </button>
    </form>
  );
}