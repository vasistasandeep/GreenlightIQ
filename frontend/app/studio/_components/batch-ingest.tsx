"use client";

/**
 * BatchIngest (R1 - batch slate ingestion).
 *
 * Upload a CSV or JSON slate (e.g. a festival catalog) and dispatch it to the
 * asynchronous ingestion pipeline (POST /titles/ingest -> 202 + job id), then
 * poll the job (GET /jobs/{id}) until it reaches a terminal state and show the
 * accepted / rejected summary. Heavy per-row work runs on the Celery worker.
 */

import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/lib/api-client";
import type { JobStatusInfo } from "@/lib/types";

type Format = "csv" | "json";

const POLL_MS = 1500;

// Downloadable CSV template for the Batch Slate uploader. Columns and allowed
// values mirror sample-imports/README.md ("The fields"). The leading `#` lines
// are hints; the ingest pipeline ignores comment lines, so the file imports
// as-is after the user fills in their own rows.
const CSV_TEMPLATE_HINTS = [
  "# CineROI AI - Batch Slate template. Fill in one row per title, then upload this file in Asset Studio -> Batch Slate.",
  "# Remove these # hint lines or leave them (they are ignored on import). Keep the header row below.",
  "# title_name            Required. The title.",
  "# asset_type            ORIGINAL_SERIES | ORIGINAL_FILM | LICENSED_LIBRARY | CO_PRODUCTION. Blank -> LICENSED_LIBRARY.",
  "# acquisition_cost_or_budget  Required. Native-currency amount, 0.01 .. 999999999.99.",
  "# native_currency       USD | INR | EUR | GBP. Blank -> USD.",
  "# target_territories    Semicolon-delimited, e.g. IN;SEA (use ; not , so it stays in one cell).",
  "# genre_tag             Free text, e.g. cricket, drama, documentary. Drives the genre churn driver.",
  "# content_format        live-sports | live-event | reality-competition | scripted-series | original-film | documentary | library.",
  "# projected_viewing_hours  Optional. Estimated total hours watched; drives Cost-per-Viewing-Hour.",
];
const CSV_TEMPLATE_HEADER =
  "title_name,asset_type,acquisition_cost_or_budget,native_currency,target_territories,genre_tag,content_format,projected_viewing_hours";
const CSV_TEMPLATE_ROWS = [
  "Bharat T20 Smash 2026,LICENSED_LIBRARY,304200000.00,INR,IN,cricket,live-sports,296000000.00",
  "Monsoon Heirs,ORIGINAL_SERIES,52000000.00,INR,IN;SEA,drama,scripted-series,41000000.00",
  "The Tide Keepers,ORIGINAL_FILM,34000000.00,USD,US;GB,sci-fi,original-film,9000000.00",
];

function downloadCsvTemplate() {
  const body = [...CSV_TEMPLATE_HINTS, CSV_TEMPLATE_HEADER, ...CSV_TEMPLATE_ROWS].join("\n") + "\n";
  const blob = new Blob([body], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "cineroi-slate-template.csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function BatchIngest() {
  const [format, setFormat] = useState<Format>("csv");
  const [content, setContent] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<JobStatusInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Poll the dispatched job until it reaches a terminal state.
  useEffect(() => {
    if (!jobId) return;
    let active = true;
    async function tick() {
      try {
        const status = await api.getJob(jobId!);
        if (!active) return;
        setJob(status);
        if (status.status === "COMPLETED" || status.status === "FAILED") {
          return; // terminal; stop polling
        }
      } catch {
        if (!active) return;
        setError("Lost contact with the ingestion job.");
        return;
      }
      pollRef.current = setTimeout(tick, POLL_MS);
    }
    void tick();
    return () => {
      active = false;
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [jobId]);

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    if (file.name.toLowerCase().endsWith(".json")) setFormat("json");
    else if (file.name.toLowerCase().endsWith(".csv")) setFormat("csv");
    setContent(await file.text());
  }

  async function submit() {
    if (content.trim() === "") {
      setError("Provide a CSV or JSON slate to ingest.");
      return;
    }
    setSubmitting(true);
    setError(null);
    setJob(null);
    setJobId(null);
    try {
      const accepted = await api.ingestBatch(content, format);
      setJobId(accepted.job_id);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.envelope?.message ?? err.message);
      } else {
        setError("Could not dispatch the batch. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  const terminal = job && (job.status === "COMPLETED" || job.status === "FAILED");
  const result = (job?.result ?? {}) as {
    accepted_count?: number;
    rejected_count?: number;
    rejections?: { row?: number | null; reason?: string }[];
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3 text-sm">
        <span className="text-slate-400">Format</span>
        {(["csv", "json"] as Format[]).map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setFormat(f)}
            className={
              "rounded-md px-3 py-1 text-xs font-semibold uppercase " +
              (format === f ? "bg-emerald-500 text-emerald-950" : "bg-slate-800 text-slate-300")
            }
          >
            {f}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-1 text-sm">
        <span className="text-slate-400">New to the format? Start from a template</span>
        <button
          type="button"
          onClick={downloadCsvTemplate}
          className="inline-flex w-fit items-center gap-1 rounded-md border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-semibold text-slate-200 hover:bg-slate-700"
        >
          <span aria-hidden="true">&#8595;</span> Download CSV template
        </button>
        <span className="text-xs text-slate-500">
          Includes the header row, allowed values as comment hints, and 3 example titles. Fill it in, then upload it below.
        </span>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-slate-400">Upload a slate file (CSV or JSON)</span>
        <input
          type="file"
          accept=".csv,.json,text/csv,application/json"
          onChange={onFile}
          className="text-sm text-slate-300 file:mr-3 file:rounded-md file:border-0 file:bg-slate-800 file:px-3 file:py-1.5 file:text-slate-200"
        />
        {fileName ? <span className="text-xs text-slate-500">{fileName}</span> : null}
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-slate-400">...or paste the slate contents</span>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={6}
          placeholder={format === "csv" ? "title_name,asset_type,..." : '[{"title_name": "..."}]'}
          className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-xs text-slate-200"
        />
      </label>

      {error ? (
        <p role="alert" className="text-sm font-medium text-rose-400">
          {error}
        </p>
      ) : null}

      <button
        type="button"
        onClick={submit}
        disabled={submitting || (jobId !== null && !terminal)}
        className="inline-flex w-fit items-center rounded-md bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 hover:bg-emerald-400 disabled:opacity-60"
      >
        {submitting ? "Dispatching..." : "Ingest slate"}
      </button>

      {jobId && !terminal ? (
        <div className="flex items-center gap-3 rounded-md border border-slate-800 bg-slate-900/60 px-4 py-3 text-sm text-slate-300">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-emerald-500 border-t-transparent" />
          Processing slate (job {jobId.slice(0, 8)}, status {job?.status ?? "PENDING"})...
        </div>
      ) : null}

      {terminal ? (
        <div
          className={
            "rounded-md border px-4 py-3 text-sm " +
            (job!.status === "COMPLETED"
              ? "border-emerald-800 bg-emerald-950/30 text-emerald-200"
              : "border-rose-800 bg-rose-950/30 text-rose-200")
          }
        >
          {job!.status === "COMPLETED" ? (
            <>
              <p className="font-semibold">Ingestion complete.</p>
              <p className="mt-1">
                Accepted {result.accepted_count ?? 0}
                {typeof result.rejected_count === "number"
                  ? `, rejected ${result.rejected_count}`
                  : ""}
                .
              </p>
              {result.rejections && result.rejections.length > 0 ? (
                <ul className="mt-2 list-disc pl-5 text-xs text-rose-300">
                  {result.rejections.slice(0, 10).map((r, i) => (
                    <li key={i}>
                      Row {r.row ?? "-"}: {r.reason ?? "rejected"}
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : (
            <>
              <p className="font-semibold">Ingestion failed.</p>
              <p className="mt-1">{job!.failure_reason ?? "The batch could not be processed."}</p>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}