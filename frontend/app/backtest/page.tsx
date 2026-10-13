"use client";

import { useEffect, useState } from "react";

import { AppShell } from "@/components/layout/top-nav";
import { api, ApiError } from "@/lib/api-client";
import type {
  BacktestAuditRequest,
  BacktestAuditResponse,
  CalibrationApplyResponse,
  FinalizationStatus,
} from "@/lib/types";
import {
  selectAuditableTitles,
  type AuditableTitleOption,
  type TitlesLoadStatus,
} from "@/lib/backtest/select-auditable-titles";
import { mapAuditError } from "@/lib/backtest/map-audit-error";
import { CalibrationController } from "@/components/backtest/calibration-controller";
import { GroundTruthForm } from "@/components/backtest/ground-truth-form";
import { SignOffPanel } from "@/components/backtest/sign-off-panel";
import { VarianceChart } from "@/components/backtest/variance-chart";

/**
 * Backtesting & Calibration Studio (`/backtest`, R16, R20.5).
 *
 * Split-pane layout: the left pane holds the {@link GroundTruthForm} ground-truth
 * input controls (R16.1); the right pane renders the {@link VarianceChart}
 * side-by-side Predicted vs Actual charts after submission (R16.2), the
 * {@link CalibrationController} that requests auto-tuning offsets from the
 * historical MAPE and shows the applied weight offsets (R16.3, R16.4), and the
 * {@link SignOffPanel} surfacing the required roles and outstanding approvals for
 * a high-budget greenlight (R20.5).
 *
 * On mount the page loads the auditable titles from `GET /dashboard/summary`
 * (titles that already carry a stored prediction) and threads them into the
 * ground-truth selector, so a demo user never types an internal identifier and
 * only submits audits that can succeed. Audit rejections are translated into
 * readable, actionable messages via {@link mapAuditError}.
 *
 * This page owns the request lifecycle and threads results into the presentational
 * components; all backend access goes through the typed {@link api} client.
 */
export default function BacktestStudioPage() {
  const [titles, setTitles] = useState<AuditableTitleOption[]>([]);
  const [titlesStatus, setTitlesStatus] = useState<TitlesLoadStatus>("loading");
  const [titlesError, setTitlesError] = useState<string | null>(null);

  const [auditTitleId, setAuditTitleId] = useState<string | null>(null);

  const [audit, setAudit] = useState<BacktestAuditResponse | null>(null);
  const [auditing, setAuditing] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);

  const [calibration, setCalibration] = useState<CalibrationApplyResponse | null>(null);
  const [calibrating, setCalibrating] = useState(false);
  const [calibrationError, setCalibrationError] = useState<string | null>(null);

  const [finalization, setFinalization] = useState<FinalizationStatus | null>(null);
  const [finalizationLoading, setFinalizationLoading] = useState(false);
  const [finalizationError, setFinalizationError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function loadTitles() {
      setTitlesStatus("loading");
      setTitlesError(null);
      try {
        const summary = await api.getDashboardSummary();
        if (!active) {
          return;
        }
        const auditable = selectAuditableTitles(summary.titles);
        setTitles(auditable);
        setTitlesStatus(auditable.length > 0 ? "loaded" : "empty");
      } catch {
        if (!active) {
          return;
        }
        setTitles([]);
        setTitlesStatus("error");
        setTitlesError("Could not load auditable titles. Please retry.");
      }
    }
    void loadTitles();
    return () => {
      active = false;
    };
  }, []);

  function messageFor(err: unknown): string {
    if (err instanceof ApiError) {
      return err.envelope?.message ?? err.message;
    }
    return "Something went wrong. Please try again.";
  }

  async function handleAudit(request: BacktestAuditRequest) {
    setAuditing(true);
    setAuditError(null);
    // A fresh audit invalidates any prior calibration result.
    setCalibration(null);
    setCalibrationError(null);
    try {
      const response = await api.backtestAudit(request);
      setAudit(response);
      setAuditTitleId(request.title_id);
      void loadFinalization(request.title_id);
    } catch (err) {
      setAudit(null);
      setAuditTitleId(null);
      setAuditError(mapAuditError(err));
    } finally {
      setAuditing(false);
    }
  }

  async function handleCalibrate() {
    if (!auditTitleId) {
      return;
    }
    setCalibrating(true);
    setCalibrationError(null);
    try {
      const response = await api.applyCalibration({ title_id: auditTitleId });
      setCalibration(response);
    } catch (err) {
      setCalibration(null);
      setCalibrationError(messageFor(err));
    } finally {
      setCalibrating(false);
    }
  }

  async function loadFinalization(decisionId: string) {
    setFinalizationLoading(true);
    setFinalizationError(null);
    try {
      const status = await api.getFinalization(decisionId);
      setFinalization(status);
    } catch (err) {
      setFinalization(null);
      setFinalizationError(messageFor(err));
    } finally {
      setFinalizationLoading(false);
    }
  }

  // The predicted CPVH is only known once the audit returns; surface it to the
  // form so the read-only "Predicted" CPVH field can fill in after Run audit.
  const predictedCpvh =
    audit?.metrics.find((m) => m.metric === "cpvh")?.predicted ?? null;

  return (
    <AppShell>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Backtesting &amp; Calibration Studio</h1>
        <p className="text-muted-foreground">
          Compare historical predictions against ground truth and recalibrate the
          model.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,22rem)_1fr]">
        {/* Left pane: ground-truth input (R16.1). */}
        <div className="rounded-lg border border-border p-5">
          <GroundTruthForm
            titles={titles}
            titlesStatus={titlesStatus}
            predictedCpvh={predictedCpvh}
            onSubmit={handleAudit}
            submitting={auditing}
          />
          {titlesStatus === "error" && titlesError ? (
            <p role="alert" className="mt-4 text-sm font-medium text-red-600">
              {titlesError}
            </p>
          ) : null}
        </div>

        {/* Right pane: variance charts, calibration, and sign-off. */}
        <div className="flex flex-col gap-6">
          {auditError ? (
            <p role="alert" className="text-sm font-medium text-red-600">
              {auditError}
            </p>
          ) : null}

          {audit ? (
            <div className="rounded-lg border border-border p-5">
              <VarianceChart metrics={audit.metrics} />
              {audit.no_eligible_metrics ? (
                <p className="mt-3 text-sm text-amber-700">
                  No eligible metrics - every actual was zero, so MAPE is undefined.
                </p>
              ) : typeof audit.mape === "number" ? (
                <p className="mt-3 text-sm text-muted-foreground">
                  Overall MAPE:{" "}
                  <span className="font-semibold text-foreground">
                    {audit.mape.toFixed(2)}%
                  </span>
                </p>
              ) : null}
            </div>
          ) : (
            <div className="flex min-h-48 items-center justify-center rounded-lg border border-dashed border-border p-5">
              <p className="text-sm text-muted-foreground">
                Submit ground truth to see Predicted vs Actual variance.
              </p>
            </div>
          )}

          <CalibrationController
            onCalibrate={handleCalibrate}
            calibrating={calibrating}
            enabled={Boolean(auditTitleId)}
            result={calibration}
            error={calibrationError}
          />

          <SignOffPanel
            status={finalization}
            loading={finalizationLoading}
            error={finalizationError}
          />
        </div>
      </div>
    </AppShell>
  );
}