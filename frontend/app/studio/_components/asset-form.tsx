"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";
import { parseShorthandAmount } from "./helpers";
import { api, ApiError } from "@/lib/api-client";
import type {
  AssetType,
  BuzzLevel,
  ProductionStage,
  QuickEvaluateRequest,
  ReleaseWindow,
  SourceIpProvenance,
} from "@/lib/types";

const ASSET_TYPES: { value: AssetType; label: string }[] = [
  { value: "ORIGINAL_SERIES", label: "ORIGINAL_SERIES" },
  { value: "ORIGINAL_FILM", label: "ORIGINAL_FILM" },
  { value: "LICENSED_LIBRARY", label: "LICENSED_LIBRARY" },
  { value: "CO_PRODUCTION", label: "CO_PRODUCTION" },
];

const CURRENCIES = ["USD", "INR", "EUR", "GBP"];

// Canonical genres with a churn-model weight (see the Churn_Mitigation_Model).
// The field is an editable dropdown: a custom typed value still works and falls
// back to the model's neutral genre weight.
const GENRES = [
  "Crime",
  "Crime-Biopic",
  "Drama",
  "Thriller",
  "Reality",
  "Mystery",
  "Sci-Fi",
  "Fantasy",
  "Biopic",
  "Romance",
  "Action",
  "Adventure",
  "Historical",
  "War",
  "Horror",
  "Sports",
  "Family",
  "Animation",
  "Anthology",
  "Comedy",
  "Documentary",
  "Kids",
  "Musical",
  "Western",
];

const VIEWING_UNITS: { value: "hours" | "minutes" | "seconds"; label: string }[] = [
  { value: "hours", label: "hrs" },
  { value: "minutes", label: "min" },
  { value: "seconds", label: "sec" },
];

// OTT content formats with a churn-affinity lift (live/appointment formats are
// stickiest). The field is an editable dropdown; a custom value falls back to a
// neutral lift. Distinct from Asset Type and Genre.
const CONTENT_FORMATS = [
  "Live Sports",
  "Live Event",
  "Reality / Competition",
  "Scripted Series",
  "Limited Series",
  "Original Film",
  "Licensed Film",
  "Documentary",
  "Kids / Animation",
  "Library / Catalog",
];

const TERRITORIES = [
  { code: "IN", label: "India" },
  { code: "NA", label: "North America" },
  { code: "EU", label: "Europe" },
  { code: "SEA", label: "SE Asia" },
  { code: "GLOBAL", label: "Global" },
];

// --------------------------------------------------------------------------- //
// Advanced_Content_Eval_Drivers controls (driver-input-capture). All optional:
// a submission that sets none behaves exactly as today (R8.5).
// --------------------------------------------------------------------------- //

// Production_Stage members (R2.1). Momentum is stage-excluded for the first two.
const PRODUCTION_STAGES: { value: ProductionStage; label: string }[] = [
  { value: "CONCEPT_SCRIPT", label: "CONCEPT_SCRIPT" },
  { value: "IN_PRODUCTION", label: "IN_PRODUCTION" },
  { value: "FESTIVAL_PREVIEW", label: "FESTIVAL_PREVIEW" },
  { value: "ACQUISITION_READY", label: "ACQUISITION_READY" },
];

// Stages for which momentum is forced to a flat 1.00 (STAGE_EXCLUDED) by the
// backend, so a buzz level has no effect and the control is disabled (R2 #4).
const BUZZ_EXCLUDED_STAGES: ProductionStage[] = ["CONCEPT_SCRIPT", "IN_PRODUCTION"];

// Buzz_Level control values (R2.2). No raw v_trailer/e_ratio/s_velocity inputs.
const BUZZ_LEVELS: BuzzLevel[] = ["LOW", "MEDIUM", "HIGH"];

// Source_IP_Provenance_Set — the only selectable source-IP values (R1.3).
const SOURCE_IP_PROVENANCES: SourceIpProvenance[] = [
  "ORIGINAL_SCREENPLAY",
  "BESTSELLER_BOOK",
  "TRUE_CRIME_IP",
  "WEBTOON_MANGA",
  "PUBLIC_DOMAIN",
];

// Release_Window_Set — the only selectable release-window values (R1.4).
const RELEASE_WINDOWS: ReleaseWindow[] = [
  "DIRECT_TO_STREAMING",
  "DAY_AND_DATE",
  "THEATRICAL_30D",
  "THEATRICAL_60D_PLUS",
];

// Each preset fills the whole form, including the optional Advanced drivers.
// Presets that carry a buzz_level use a late production_stage (FESTIVAL_PREVIEW
// / ACQUISITION_READY) so momentum is active rather than STAGE_EXCLUDED.
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
    content_format: "Scripted Series",
    projected_viewing_hours: 4_200_000,
    viewing_hours_unit: "hours",
    talent_pedigree_score: 7.5,
    license_duration_months: 24,
    is_exclusive: true,
    // Advanced drivers — a fresh original, so no lineage; macro + momentum set.
    production_stage: "ACQUISITION_READY",
    buzz_level: "MEDIUM",
    source_ip_provenance: "ORIGINAL_SCREENPLAY",
    release_window: "DIRECT_TO_STREAMING",
    release_month: 8,
    vernacular_track_count: 3,
  },
  "Bengaluru S2 (Sequel)": {
    title_name: "The Bengaluru Syndicate (S2)",
    asset_type: "ORIGINAL_SERIES",
    acquisition_cost_or_budget: 2_100_000,
    native_currency: "USD",
    target_territories: ["IN", "SEA", "NA"],
    synopsis:
      "The syndicate saga returns: with the kingpin behind bars, a power vacuum ignites a bloodier turf war while the detectives chase the money. A proven returning ensemble raises the stakes for a highly anticipated second season.",
    genre_tag: "Crime-Noir",
    content_format: "Scripted Series",
    projected_viewing_hours: 5_600_000,
    viewing_hours_unit: "hours",
    talent_pedigree_score: 8.0,
    license_duration_months: 24,
    is_exclusive: true,
    // Advanced drivers — full franchise lineage + strong momentum + macro.
    is_franchise: true,
    franchise_order: 2,
    parent_title_viewing_hours: 4_200_000,
    parent_completion_rate: 0.82,
    production_stage: "ACQUISITION_READY",
    buzz_level: "HIGH",
    source_ip_provenance: "ORIGINAL_SCREENPLAY",
    release_window: "DIRECT_TO_STREAMING",
    release_month: 10,
    vernacular_track_count: 4,
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
    content_format: "Original Film",
    projected_viewing_hours: 9_000_000,
    viewing_hours_unit: "hours",
    talent_pedigree_score: 9.0,
    license_duration_months: 36,
    is_exclusive: true,
    // Advanced drivers — bestseller-adapted tentpole, day-and-date, peak buzz.
    production_stage: "ACQUISITION_READY",
    buzz_level: "HIGH",
    source_ip_provenance: "BESTSELLER_BOOK",
    release_window: "DAY_AND_DATE",
    release_month: 7,
    vernacular_track_count: 6,
  },
  "Mythic Realms (Festival IP)": {
    title_name: "Mythic Realms",
    asset_type: "CO_PRODUCTION",
    acquisition_cost_or_budget: 8_500_000,
    native_currency: "EUR",
    target_territories: ["EU", "NA", "IN"],
    synopsis:
      "An epic fantasy co-production adapted from a bestselling webtoon: warring realms, a reluctant heir, and a festival-buzzed visual spectacle positioned for a staggered theatrical-to-streaming rollout.",
    genre_tag: "Fantasy",
    content_format: "Limited Series",
    projected_viewing_hours: 6_000_000,
    viewing_hours_unit: "hours",
    talent_pedigree_score: 8.5,
    license_duration_months: 30,
    is_exclusive: true,
    // Advanced drivers — festival-preview stage with medium buzz; webtoon IP.
    production_stage: "FESTIVAL_PREVIEW",
    buzz_level: "MEDIUM",
    source_ip_provenance: "WEBTOON_MANGA",
    release_window: "THEATRICAL_60D_PLUS",
    release_month: 11,
    vernacular_track_count: 5,
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
    content_format: "Library / Catalog",
    projected_viewing_hours: 2_000_000,
    viewing_hours_unit: "hours",
    talent_pedigree_score: 4.0,
    license_duration_months: 12,
    is_exclusive: false,
    // Advanced drivers — public-domain back catalogue; no buzz (library title).
    production_stage: "ACQUISITION_READY",
    source_ip_provenance: "PUBLIC_DOMAIN",
    release_window: "DIRECT_TO_STREAMING",
    release_month: 2,
    vernacular_track_count: 2,
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
  const [viewingUnit, setViewingUnit] = useState<"hours" | "minutes" | "seconds">("hours");
  const [contentFormat, setContentFormat] = useState("");
  const [pedigree, setPedigree] = useState("5.0");
  const [duration, setDuration] = useState("24");
  const [exclusive, setExclusive] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [parsing, setParsing] = useState(false);
  const [parseNote, setParseNote] = useState<string | null>(null);

  // --- Advanced drivers (optional). Empty string / false = "not supplied". --- //
  const [isFranchise, setIsFranchise] = useState(false);
  const [franchiseOrder, setFranchiseOrder] = useState("");
  const [parentHours, setParentHours] = useState("");
  const [parentCompletion, setParentCompletion] = useState("");
  const [productionStage, setProductionStage] = useState<ProductionStage | "">("");
  const [buzzLevel, setBuzzLevel] = useState<BuzzLevel | "">("");
  const [sourceIp, setSourceIp] = useState<SourceIpProvenance | "">("");
  const [releaseWindow, setReleaseWindow] = useState<ReleaseWindow | "">("");
  const [releaseMonth, setReleaseMonth] = useState("");
  const [vernacularTracks, setVernacularTracks] = useState("");

  // Buzz is inert (STAGE_EXCLUDED, flat 1.00) in early stages, so disable it and
  // mirror the backend behavior for the user (R2 clarification #4).
  const buzzDisabled =
    productionStage !== "" && BUZZ_EXCLUDED_STAGES.includes(productionStage);

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
    setContentFormat(p.content_format ?? "");
    setViewingHours(
      p.projected_viewing_hours != null ? String(p.projected_viewing_hours) : "",
    );
    setViewingUnit(p.viewing_hours_unit ?? "hours");
    // Advanced drivers: apply whatever the preset carries, resetting any field
    // the preset omits back to its neutral "not supplied" state so switching
    // presets never leaves a stale driver value behind.
    setIsFranchise(Boolean(p.is_franchise));
    setFranchiseOrder(p.franchise_order != null ? String(p.franchise_order) : "");
    setParentHours(
      p.parent_title_viewing_hours != null ? String(p.parent_title_viewing_hours) : "",
    );
    setParentCompletion(
      p.parent_completion_rate != null ? String(p.parent_completion_rate) : "",
    );
    setProductionStage((p.production_stage as ProductionStage) ?? "");
    setBuzzLevel((p.buzz_level as BuzzLevel) ?? "");
    setSourceIp((p.source_ip_provenance as SourceIpProvenance) ?? "");
    setReleaseWindow((p.release_window as ReleaseWindow) ?? "");
    setReleaseMonth(p.release_month != null ? String(p.release_month) : "");
    setVernacularTracks(
      p.vernacular_track_count != null ? String(p.vernacular_track_count) : "",
    );
    setError(null);
  }

  async function handlePitchFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setParsing(true);
    setParseNote(null);
    setError(null);
    try {
      const p = await api.parsePitch(file);
      if (p.title_name) setTitleName(p.title_name);
      if (p.synopsis) setSynopsis(p.synopsis);
      if (p.genre_tag) setGenre(p.genre_tag);
      if (typeof p.acquisition_cost_or_budget === "number") {
        setCost(String(p.acquisition_cost_or_budget));
      }
      if (p.native_currency) setCurrency(p.native_currency);
      if (typeof p.is_exclusive === "boolean") setExclusive(p.is_exclusive);

      // Advanced-driver facts the parser recognized (R4.1-R4.4). Each is
      // rendered as a user-editable control the user reviews before submitting
      // (R4.6); an unrecognized fact is absent and leaves its control empty (R4.5).
      const driverFacts: string[] = [];
      if (typeof p.is_franchise === "boolean" && p.is_franchise) {
        setIsFranchise(true);
        driverFacts.push("franchise");
        if (typeof p.franchise_order === "number") {
          setFranchiseOrder(String(p.franchise_order));
        }
      }
      if (p.production_stage) {
        setProductionStage(p.production_stage as ProductionStage);
        driverFacts.push("production stage");
      }
      if (p.source_ip_provenance) {
        setSourceIp(p.source_ip_provenance as SourceIpProvenance);
        driverFacts.push("source IP");
      }
      if (p.release_window) {
        setReleaseWindow(p.release_window as ReleaseWindow);
        driverFacts.push("release window");
      }

      const filled = [
        p.title_name && "title",
        p.synopsis && "synopsis",
        p.genre_tag && "genre",
        typeof p.acquisition_cost_or_budget === "number" && "budget",
      ].filter(Boolean) as string[];
      const allFilled = [...filled, ...driverFacts];
      setParseNote(
        allFilled.length > 0
          ? `Pre-filled ${allFilled.join(", ")} from the pitch. Review and edit before running.`
          : "Could not recognize fields in that PDF. Enter them manually.",
      );
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.envelope?.message ?? err.message
          : "Could not read that PDF.",
      );
    } finally {
      setParsing(false);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!titleName.trim()) return setError("Title name is required.");
    if (!synopsis.trim()) return setError("A logline / synopsis is required.");
    const costN = parseShorthandAmount(cost) ?? NaN;
    if (!Number.isFinite(costN) || costN < 0.01 || costN > 999_999_999.99) {
      return setError("Cost must be between 0.01 and 999,999,999.99 (e.g. 12 Cr, 1.5M, 500k).");
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
      viewing_hours_unit: viewingUnit,
      content_format: contentFormat.trim() || null,
      talent_pedigree_score: pedigree ? Number(pedigree) : null,
      license_duration_months: duration ? Number(duration) : null,
      is_exclusive: exclusive,
    };

    // Advanced drivers: include each fact only when set; omit otherwise so an
    // unsupplied fact stays absent from the snapshot (R1.5, R2.5). Lineage
    // parent fields are sent only for a franchise entry (R1.6).
    if (isFranchise) {
      payload.is_franchise = true;
      if (franchiseOrder.trim() !== "") payload.franchise_order = Number(franchiseOrder);
      if (parentHours.trim() !== "") payload.parent_title_viewing_hours = Number(parentHours);
      if (parentCompletion.trim() !== "") {
        payload.parent_completion_rate = Number(parentCompletion);
      }
    }
    if (productionStage !== "") payload.production_stage = productionStage;
    // A buzz level is sent only while the control is active (not stage-excluded).
    if (buzzLevel !== "" && !buzzDisabled) payload.buzz_level = buzzLevel;
    if (sourceIp !== "") payload.source_ip_provenance = sourceIp;
    if (releaseWindow !== "") payload.release_window = releaseWindow;
    if (releaseMonth.trim() !== "") payload.release_month = Number(releaseMonth);
    if (vernacularTracks.trim() !== "") {
      payload.vernacular_track_count = Number(vernacularTracks);
    }

    void onSubmit(payload);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <label className="flex cursor-pointer flex-col items-center gap-1 rounded-lg border border-dashed border-slate-700 bg-slate-900/40 px-4 py-5 text-center text-sm text-slate-400 hover:border-emerald-600/60">
        <span className="font-medium text-slate-300">
          {parsing ? "Reading pitch PDF..." : "Drop a script / pitch PDF to auto-fill"}
        </span>
        <span className="text-xs">We parse title, synopsis, genre, and budget for you to review.</span>
        <input
          type="file"
          accept=".pdf,application/pdf"
          className="hidden"
          disabled={parsing}
          onChange={handlePitchFile}
        />
      </label>
      {parseNote ? (
        <p className="text-xs text-emerald-400">{parseNote}</p>
      ) : null}
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
        {parseShorthandAmount(cost) !== null ? (
          <p className="mt-1 text-xs text-slate-500">
            {new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(
              parseShorthandAmount(cost)!,
            )}{" "}
            {currency}
          </p>
        ) : cost.trim() !== "" ? (
          <p className="mt-1 text-xs text-amber-500">
            Enter a number or shorthand like 12 Cr, 1.5M, 500k.
          </p>
        ) : null}
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
          <input id="f-genre" className={fieldCls} value={genre} list="genre-options"
            onChange={(e) => setGenre(e.target.value)} placeholder="Crime" />
          <datalist id="genre-options">
            {GENRES.map((g) => <option key={g} value={g} />)}
          </datalist>
        </div>
        <div>
          <label htmlFor="f-hours" className={labelCls}>Viewing (opt.)</label>
          <div className="flex gap-2">
            <input id="f-hours" className={fieldCls} inputMode="decimal" value={viewingHours}
              onChange={(e) => setViewingHours(e.target.value)} placeholder="estimated"
              aria-label="Projected viewing figure" />
            <select className={cn(fieldCls, "w-20")} value={viewingUnit}
              onChange={(e) => setViewingUnit(e.target.value as "hours" | "minutes" | "seconds")}
              aria-label="Viewing unit">
              {VIEWING_UNITS.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
            </select>
          </div>
        </div>
      </div>

      <div>
        <label htmlFor="f-format" className={labelCls}>Content Format (opt.)</label>
        <input id="f-format" className={fieldCls} value={contentFormat} list="format-options"
          onChange={(e) => setContentFormat(e.target.value)} placeholder="e.g. Live Sports" />
        <datalist id="format-options">
          {CONTENT_FORMATS.map((f) => <option key={f} value={f} />)}
        </datalist>
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

      <fieldset className="flex flex-col gap-4 rounded-lg border border-slate-800 bg-slate-900/30 p-4">
        <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-slate-300">
          Advanced drivers (optional)
        </legend>

        {/* Lineage — franchise toggle reveals the parent fields (R1.6). */}
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={isFranchise}
            onChange={(e) => setIsFranchise(e.target.checked)} className="accent-emerald-500" />
          Franchise entry (sequel / later season)
        </label>

        {isFranchise ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label htmlFor="f-forder" className={labelCls}>Franchise Order</label>
              <input id="f-forder" className={fieldCls} inputMode="numeric" min={1}
                type="number" value={franchiseOrder}
                onChange={(e) => setFranchiseOrder(e.target.value)} placeholder="2" />
            </div>
            <div>
              <label htmlFor="f-phours" className={labelCls}>Parent Viewing Hours</label>
              <input id="f-phours" className={fieldCls} inputMode="decimal" type="number"
                min={0} value={parentHours}
                onChange={(e) => setParentHours(e.target.value)} placeholder="6000" />
            </div>
            <div>
              <label htmlFor="f-pcomp" className={labelCls}>Parent Completion (0-1)</label>
              <input id="f-pcomp" className={fieldCls} inputMode="decimal" type="number"
                min={0} max={1} step={0.01} value={parentCompletion}
                onChange={(e) => setParentCompletion(e.target.value)} placeholder="0.80" />
            </div>
          </div>
        ) : null}

        {/* Momentum — production stage + friendly buzz level (no raw signals, R2.2). */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="f-stage" className={labelCls}>Production Stage</label>
            <select id="f-stage" className={fieldCls} value={productionStage}
              onChange={(e) => setProductionStage(e.target.value as ProductionStage | "")}>
              <option value="">(not set)</option>
              {PRODUCTION_STAGES.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="f-buzz" className={labelCls}>Buzz Level</label>
            <select id="f-buzz" className={fieldCls} value={buzzLevel} disabled={buzzDisabled}
              aria-describedby={buzzDisabled ? "f-buzz-help" : undefined}
              onChange={(e) => setBuzzLevel(e.target.value as BuzzLevel | "")}>
              <option value="">(not set)</option>
              {BUZZ_LEVELS.map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
          </div>
        </div>
        {buzzDisabled ? (
          <p id="f-buzz-help" className="text-xs text-amber-500">
            Inactive in early stage (STAGE_EXCLUDED) — buzz does not affect an
            unproduced title&apos;s verdict.
          </p>
        ) : null}

        {/* Macro — provenance, window, month, vernacular tracks. */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="f-sip" className={labelCls}>Source IP Provenance</label>
            <select id="f-sip" className={fieldCls} value={sourceIp}
              onChange={(e) => setSourceIp(e.target.value as SourceIpProvenance | "")}>
              <option value="">(not set)</option>
              {SOURCE_IP_PROVENANCES.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="f-rwin" className={labelCls}>Release Window</label>
            <select id="f-rwin" className={fieldCls} value={releaseWindow}
              onChange={(e) => setReleaseWindow(e.target.value as ReleaseWindow | "")}>
              <option value="">(not set)</option>
              {RELEASE_WINDOWS.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="f-rmonth" className={labelCls}>Release Month (1-12)</label>
            <input id="f-rmonth" className={fieldCls} inputMode="numeric" type="number"
              min={1} max={12} value={releaseMonth}
              onChange={(e) => setReleaseMonth(e.target.value)} placeholder="optional" />
          </div>
          <div>
            <label htmlFor="f-vtracks" className={labelCls}>Vernacular Tracks</label>
            <input id="f-vtracks" className={fieldCls} inputMode="numeric" type="number"
              min={1} value={vernacularTracks}
              onChange={(e) => setVernacularTracks(e.target.value)} placeholder="1" />
          </div>
        </div>
      </fieldset>

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