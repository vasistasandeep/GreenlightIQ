import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AssetDataGrid } from "@/components/dashboard/asset-data-grid";
import type { TitleSummary } from "@/lib/types";

/**
 * AssetDataGrid tests (R14.2, R14.4, R14.5).
 *
 * All view state (search, recommendation filter, sort column/direction) is
 * mirrored into the URL. The next/navigation mock is therefore STATEFUL: a
 * module-level URLSearchParams that `router.replace` mutates and
 * `useSearchParams` reads, with a listener that re-renders the component so the
 * component stays a pure function of the (mocked) URL - exactly as it is live.
 * `router.push` is tracked separately to assert row-click navigation (R14.5).
 */

const pushMock = vi.fn();
let currentParams = new URLSearchParams();
let rerender: (() => void) | null = null;

function applyReplace(url: string) {
  const qIndex = url.indexOf("?");
  currentParams = new URLSearchParams(qIndex >= 0 ? url.slice(qIndex + 1) : "");
  rerender?.();
}

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
    replace: (url: string) => applyReplace(url),
  }),
  useSearchParams: () => currentParams,
}));

const TITLES: TitleSummary[] = [
  {
    title_id: "t-charlie",
    title_name: "Charlie's Saga",
    asset_type: "ORIGINAL_SERIES",
    asking_price: 5_000_000,
    native_currency: "USD",
    cpvh_status: "PASS",
    ltv_to_cost_multiple: 3.5,
    recommendation_status: "GREENLIGHT",
  },
  {
    title_id: "t-alpha",
    title_name: "Alpha Dawn",
    asset_type: "ORIGINAL_FILM",
    asking_price: 1_000_000,
    native_currency: "USD",
    cpvh_status: "BREACH",
    ltv_to_cost_multiple: 1.2,
    recommendation_status: "PASS",
  },
  {
    title_id: "t-bravo",
    title_name: "Bravo Nights",
    asset_type: "LICENSED_LIBRARY",
    asking_price: 3_000_000,
    native_currency: "USD",
    cpvh_status: "NO_CEILING",
    ltv_to_cost_multiple: null,
    recommendation_status: "NEGOTIATE_HARD",
  },
];

/** Return the title-name cell text for every body row, in render order. */
function rowTitleOrder(): string[] {
  const rows = screen.getAllByRole("button", { name: /Open evaluation for/ });
  return rows.map((row) => {
    const firstCell = within(row).getAllByRole("cell")[0];
    return firstCell.textContent?.trim() ?? "";
  });
}

function renderGrid() {
  const utils = render(<AssetDataGrid titles={TITLES} />);
  rerender = () => utils.rerender(<AssetDataGrid titles={TITLES} />);
  return utils;
}

describe("AssetDataGrid", () => {
  beforeEach(() => {
    pushMock.mockReset();
    currentParams = new URLSearchParams();
    rerender = null;
  });

  it("renders an empty-state message when there are no titles", () => {
    render(<AssetDataGrid titles={[]} />);
    expect(
      screen.getByText(/No active titles in the pipeline yet/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Evaluate an asset/i }),
    ).toBeInTheDocument();
  });

  it("defaults to ascending sort by title name", () => {
    renderGrid();
    expect(rowTitleOrder()).toEqual([
      "Alpha Dawn",
      "Bravo Nights",
      "Charlie's Saga",
    ]);
  });

  describe("column sorting (R14.4)", () => {
    it("reorders rows ascending by asking price when the header is selected", async () => {
      const user = userEvent.setup();
      renderGrid();

      await user.click(screen.getByRole("button", { name: /Asking Price/ }));

      expect(rowTitleOrder()).toEqual([
        "Alpha Dawn",
        "Bravo Nights",
        "Charlie's Saga",
      ]);
    });

    it("toggles to descending when the same header is selected twice", async () => {
      const user = userEvent.setup();
      renderGrid();

      const priceHeader = screen.getByRole("button", { name: /Asking Price/ });
      await user.click(priceHeader);
      await user.click(screen.getByRole("button", { name: /Asking Price/ }));

      expect(rowTitleOrder()).toEqual([
        "Charlie's Saga",
        "Bravo Nights",
        "Alpha Dawn",
      ]);
    });

    it("reflects the active sort direction via aria-sort on the header cell", async () => {
      const user = userEvent.setup();
      renderGrid();

      const titleHeaderCell = screen.getByRole("columnheader", { name: /Title/ });
      expect(titleHeaderCell).toHaveAttribute("aria-sort", "ascending");

      await user.click(screen.getByRole("button", { name: /^Title/ }));
      expect(
        screen.getByRole("columnheader", { name: /Title/ }),
      ).toHaveAttribute("aria-sort", "descending");
    });

    it("persists the sort into the URL query string", async () => {
      const user = userEvent.setup();
      renderGrid();

      await user.click(screen.getByRole("button", { name: /Asking Price/ }));

      expect(currentParams.get("sort")).toBe("asking_price");
      expect(currentParams.get("dir")).toBe("asc");
    });
  });

  describe("search + filter (URL-driven)", () => {
    it("filters rows by the title search box and records it in the URL", async () => {
      const user = userEvent.setup();
      renderGrid();

      await user.type(screen.getByLabelText(/Search titles by name/i), "bravo");

      expect(rowTitleOrder()).toEqual(["Bravo Nights"]);
      expect(currentParams.get("q")).toBe("bravo");
    });

    it("filters rows by the recommendation dropdown", async () => {
      const user = userEvent.setup();
      renderGrid();

      await user.selectOptions(
        screen.getByLabelText(/Recommendation/i),
        "GREENLIGHT",
      );

      expect(rowTitleOrder()).toEqual(["Charlie's Saga"]);
      expect(currentParams.get("rec")).toBe("GREENLIGHT");
    });

    it("hydrates initial state from the URL params", () => {
      currentParams = new URLSearchParams("rec=PASS");
      renderGrid();
      expect(rowTitleOrder()).toEqual(["Alpha Dawn"]);
    });

    it("shows a no-match state and clears filters on demand", async () => {
      const user = userEvent.setup();
      renderGrid();

      await user.type(screen.getByLabelText(/Search titles by name/i), "zzz");
      expect(screen.getByText(/No titles match your filters/i)).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: /Clear filters/i }));
      expect(currentParams.get("q")).toBeNull();
      expect(rowTitleOrder()).toHaveLength(3);
    });
  });

  describe("row-click navigation (R14.5)", () => {
    it("navigates to the title evaluation view when a row is clicked", async () => {
      const user = userEvent.setup();
      renderGrid();

      await user.click(
        screen.getByRole("button", { name: "Open evaluation for Alpha Dawn" }),
      );

      expect(pushMock).toHaveBeenCalledWith("/titles/t-alpha");
    });

    it("navigates when a row is activated via the keyboard", async () => {
      const user = userEvent.setup();
      renderGrid();

      const row = screen.getByRole("button", {
        name: "Open evaluation for Bravo Nights",
      });
      row.focus();
      await user.keyboard("{Enter}");

      expect(pushMock).toHaveBeenCalledWith("/titles/t-bravo");
    });

    it("does not navigate on a sort-header click", async () => {
      const user = userEvent.setup();
      renderGrid();

      await user.click(screen.getByRole("button", { name: /Asking Price/ }));

      expect(pushMock).not.toHaveBeenCalled();
    });
  });
});