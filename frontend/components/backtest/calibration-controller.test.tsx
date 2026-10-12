import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { CalibrationController } from "@/components/backtest/calibration-controller";
import type { CalibrationApplyResponse } from "@/lib/types";

/**
 * CalibrationController tests (R16.3, R16.4).
 *
 * R16.3: selecting the control requests application of the auto-tuning offsets
 * derived from the historical MAPE. R16.4: when calibration is applied the
 * studio must confirm the applied weight offsets. The no-op path (MAPE within
 * tolerance, R12.5) must instead report that the active weights are unchanged.
 */

const APPLIED: CalibrationApplyResponse = {
  adjustment_required: true,
  mape: 14.5,
  new_model_version_id: "mv-002",
  offsets: {
    talent_pedigree_weight: 0.08,
    narrative_trope_weight: -0.08,
  },
};

const NOOP: CalibrationApplyResponse = {
  adjustment_required: false,
  mape: 6.3,
  new_model_version_id: null,
  offsets: null,
};

describe("CalibrationController", () => {
  let onCalibrate: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onCalibrate = vi.fn();
  });

  describe("auto-tuning request (R16.3)", () => {
    it("requests calibration when the trigger is selected", async () => {
      const user = userEvent.setup();
      render(<CalibrationController onCalibrate={onCalibrate} enabled />);

      await user.click(
        screen.getByRole("button", { name: /Request auto-tuning/i }),
      );

      expect(onCalibrate).toHaveBeenCalledTimes(1);
    });

    it("disables the trigger until a ground-truth audit exists", () => {
      render(<CalibrationController onCalibrate={onCalibrate} enabled={false} />);

      expect(
        screen.getByRole("button", { name: /Request auto-tuning/i }),
      ).toBeDisabled();
    });

    it("disables the trigger and shows progress while a request is in flight", () => {
      render(
        <CalibrationController onCalibrate={onCalibrate} enabled calibrating />,
      );

      expect(
        screen.getByRole("button", { name: /Requesting offsets/i }),
      ).toBeDisabled();
    });

    it("surfaces a calibration error", () => {
      render(
        <CalibrationController
          onCalibrate={onCalibrate}
          enabled
          error="Offset out of range"
        />,
      );

      expect(screen.getByRole("alert")).toHaveTextContent(
        /Offset out of range/i,
      );
    });
  });

  describe("applied-offset confirmation (R16.4)", () => {
    it("confirms the recalibration and the new model version", () => {
      render(
        <CalibrationController
          onCalibrate={onCalibrate}
          enabled
          result={APPLIED}
        />,
      );

      const applied = screen.getByTestId("calibration-applied");
      expect(
        within(applied).getByText(/Recalibration applied/i),
      ).toBeInTheDocument();
      expect(within(applied).getByText(/mv-002/)).toBeInTheDocument();
      expect(within(applied).getByText(/14\.50%/)).toBeInTheDocument();
    });

    it("lists each applied weight offset with a signed value", () => {
      render(
        <CalibrationController
          onCalibrate={onCalibrate}
          enabled
          result={APPLIED}
        />,
      );

      const applied = screen.getByTestId("calibration-applied");
      expect(within(applied).getByText("Talent Pedigree")).toBeInTheDocument();
      expect(within(applied).getByText("+0.08")).toBeInTheDocument();
      expect(within(applied).getByText("Narrative Trope")).toBeInTheDocument();
      expect(within(applied).getByText("-0.08")).toBeInTheDocument();
    });

    it("does not render the no-op panel when an adjustment was applied", () => {
      render(
        <CalibrationController
          onCalibrate={onCalibrate}
          enabled
          result={APPLIED}
        />,
      );

      expect(
        screen.queryByTestId("calibration-noop"),
      ).not.toBeInTheDocument();
    });
  });

  describe("no-op path below threshold (R12.5)", () => {
    it("reports that the active weights are unchanged", () => {
      render(
        <CalibrationController
          onCalibrate={onCalibrate}
          enabled
          result={NOOP}
        />,
      );

      const noop = screen.getByTestId("calibration-noop");
      expect(
        within(noop).getByText(/No adjustment needed/i),
      ).toBeInTheDocument();
      expect(within(noop).getByText(/6\.30%/)).toBeInTheDocument();
    });

    it("does not render the applied-offset panel on a no-op", () => {
      render(
        <CalibrationController
          onCalibrate={onCalibrate}
          enabled
          result={NOOP}
        />,
      );

      expect(
        screen.queryByTestId("calibration-applied"),
      ).not.toBeInTheDocument();
    });
  });

  it("renders no result panel before any request", () => {
    render(<CalibrationController onCalibrate={onCalibrate} enabled />);

    expect(screen.queryByTestId("calibration-applied")).not.toBeInTheDocument();
    expect(screen.queryByTestId("calibration-noop")).not.toBeInTheDocument();
  });
});
