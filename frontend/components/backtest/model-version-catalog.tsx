"use client";

/**
 * ModelVersionCatalog (R26.3).
 *
 * The immutable model-version history on the Backtesting & Calibration Studio:
 * the active version plus every prior one with its coupled feature weights and
 * timestamp. An authorized data scientist can roll back to a prior version
 * (POST /models/versions/{id}/activate); calibration never mutates weights in
 * place, so rollback simply re-activates a retained version.
 */

import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api-client";
import type { ModelVersion } from "@/lib/types";

function num(value: number | string): string {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n.toFixed(2) : String(value);
}

function shortId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}...` : id;
}

function formatDate(iso: string | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(0, 10);
}

export function ModelVersionCatalog() {
  const [versions, setVersions] = useState<ModelVersion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      setVersions(await api.listModelVersions());
    } catch {
      setError("Could not load the model-version catalog.");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function rollback(id: string) {
    setBusyId(id);
    setError(null);
    try {
      await api.activateModelVersion(id);
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError("Your role is not permitted to roll back model versions.");
      } else {
        setError("Could not roll back to that version. Please try again.");
      }
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section
      aria-labelledby="model-catalog-heading"
      className="flex flex-col gap-3 rounded-lg border border-border p-4"
    >
      <div>
        <h3 id="model-catalog-heading" className="text-base font-semibold">
          Model Version Catalog
        </h3>
        <p className="text-sm text-muted-foreground">
          Immutable weight history. Roll back to a prior version if a calibration
          underperforms.
        </p>
      </div>

      {error ? (
        <p role="alert" className="text-sm font-medium text-red-500">
          {error}
        </p>
      ) : null}

      {versions === null ? (
        <p className="text-sm text-muted-foreground">Loading versions...</p>
      ) : versions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No model versions recorded.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {versions.map((v) => (
            <li
              key={v.model_version_id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-muted/40 px-3 py-2 text-sm"
            >
              <div className="flex flex-col">
                <span className="font-mono text-xs text-muted-foreground">
                  {shortId(v.model_version_id)} - {formatDate(v.created_at)}
                </span>
                <span>
                  Talent {num(v.talent_pedigree_weight)} / Trope{" "}
                  {num(v.narrative_trope_weight)}
                </span>
              </div>
              {v.is_active ? (
                <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
                  Active
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => rollback(v.model_version_id)}
                  disabled={busyId === v.model_version_id}
                  className="inline-flex items-center rounded-md border border-primary px-2.5 py-1 text-xs font-semibold text-primary disabled:opacity-50"
                >
                  {busyId === v.model_version_id ? "Rolling back..." : "Roll back to this"}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}