"use client";

import { cn } from "@/lib/utils";
import type { CalibrationApplyResponse } from "@/lib/types";

/**
 * CalibrationController (R16.3, R16.4).
 *
 * Requests auto-tuning offsets derived from a historical title's MAPE
 * (`POST /calibration/apply`, R16.3). On success it displays the applied weight
 * offsets and the new model version when the error exceeded the threshold and a
 * recalibration occurred (R16.4); when MAPE was within tolerance it reports that
 * no adjustment was needed and the active weights are unchanged (R12.5).
 *
 * The parent owns the request lifecycle (loading / error / result); this
 * component renders the trigger and the applied-offset confirmation.
 */

function formatOffset(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}`;
}

const WEIGHT_LABELS: Record<string, string> = {
  talent_pedigree_weight: "Talent Pedigree",
  narrative_trope_weight: "Narrative Trope",
};

function weightLabel(key: string): string {
  return WEIGHT_LABELS[key] ?? key;
}

export interface CalibrationControllerProps {
  /** Trigger a calibration request for the audited title. */
  onCalibrate: () => void | Promise<void>;
  /** True while a calibration request is in flight. */
  calibrating?: boolean;
  /** True once a ground-truth audit exists so calibration can be requested. */
  enabled?: boolean;
  /** The latest calibration outcome, or null before any request. */
  result?: CalibrationApplyResponse | null;
  /** A calibration error message, if the last request failed. */
  error?: string | null;
  className?: string;
}

export function CalibrationController({
  onCalibrate,
  calibrating = false,
  enabled = false,
  result = null,
  error = null,
  className,
}: CalibrationControllerProps) {
  const offsets = result?.offsets ?? null;
  const offsetEntries = offsets ? Object.entries(offsets) : [];

  return (
    <section
      className={cn("flex flex-col gap-4 rounded-lg border border-border p-4", className)}
      aria-labelledby="calibration-heading"
    >
      <div>
        <h3 id="calibration-heading" className="text-base font-semibold">
          Model Calibration
        </h3>
        <p className="text-sm text-muted-foreground">
          Auto-tune feature weights from this title&apos;s historical prediction
          error.
        </p>
      </div>

      <button
        type="button"
        onClick={() => onCalibrate()}
        disabled={!enabled || calibrating}
        className={cn(
          "inline-flex w-fit items-center justify-center rounded-md border border-primary",
          "bg-background px-4 py-2 text-sm font-semibold text-primary",
          "disabled:cursor-not-allowed disabled:opacity-50",
        )}
      >
        {calibrating ? "Requesting offsets…" : "Request auto-tuning"}
      </button>

      {error ? (
        <p role="alert" className="text-sm font-medium text-red-600">
          {error}
        </p>
      ) : null}

      {result ? (
        result.adjustment_required ? (
          <div className="flex flex-col gap-3" data-testid="calibration-applied">
            <p className="text-sm font-medium text-emerald-700">
              Recalibration applied — a new model version was activated.
            </p>
            {typeof result.mape === "number" ? (
              <p className="text-sm text-muted-foreground">
                Historical MAPE: {result.mape.toFixed(2)}%
              </p>
            ) : null}
            {result.new_model_version_id ? (
              <p className="text-xs text-muted-foreground">
                New model version:{" "}
                <span className="font-mono">{result.new_model_version_id}</span>
              </p>
            ) : null}
            {offsetEntries.length > 0 ? (
              <div>
                <h4 className="mb-1 text-sm font-medium">Applied weight offsets</h4>
                <ul className="flex flex-col gap-1">
                  {offsetEntries.map(([key, value]) => (
                    <li
                      key={key}
                      className="flex items-center justify-between rounded-md bg-muted px-3 py-1.5 text-sm"
                    >
                      <span>{weightLabel(key)}</span>
                      <span
                        className={cn(
                          "font-mono font-semibold",
                          value > 0 ? "text-emerald-700" : value < 0 ? "text-red-600" : "text-muted-foreground",
                        )}
                      >
                        {formatOffset(value)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : (
          <div className="flex flex-col gap-1" data-testid="calibration-noop">
            <p className="text-sm font-medium">
              No adjustment needed — the active weights are unchanged.
            </p>
            {typeof result.mape === "number" ? (
              <p className="text-sm text-muted-foreground">
                Historical MAPE of {result.mape.toFixed(2)}% is within tolerance.
              </p>
            ) : null}
          </div>
        )
      ) : null}
    </section>
  );
}
