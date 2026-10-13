import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AssetDataGrid } from "@/components/dashboard/asset-data-grid";
import type { TitleSummary } from "@/lib/types";

/**
 * AssetDataGrid sorting + row-click navigation tests (R14.4, R14.5).
 *
 * `next/navigation`'s useRouter is mocked so navigation (R14.5) can be
 * asserted via push calls. Column-header clicks drive the sort order (R14.4),
 * including direction toggling on repeat selection.
 */

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
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

describe("AssetDataGrid", () => {
  beforeEach(() => {
    pushMock.mockReset();
  });

  it("renders an empty-state message when there are no titles", () => {
    render(<AssetDataGrid titles={[]} />);
    expect(
      screen.getByText(/No active titles in the pipeline yet/i),
    ).toBeInTheDocument();
    // The empty state offers a clear next action.
    expect(
      screen.getByRole("link", { name: /Evaluate an asset/i }),
    ).toBeInTheDocument();
  });

  it("defaults to ascending sort by title name", () => {
    render(<AssetDataGrid titles={TITLES} />);
    expect(rowTitleOrder()).toEqual([
      "Alpha Dawn",
      "Bravo Nights",
      "Charlie's Saga",
    ]);
  });

  describe("column sorting (R14.4)", () => {
    it("reorders rows ascending by asking price when the header is selected", async () => {
      const user = userEvent.setup();
      render(<AssetDataGrid titles={TITLES} />);

      await user.click(screen.getByRole("button", { name: /Asking Price/ }));

      // 1,000,000 (Alpha) < 3,000,000 (Bravo) < 5,000,000 (Charlie)
      expect(rowTitleOrder()).toEqual([
        "Alpha Dawn",
        "Bravo Nights",
        "Charlie's Saga",
      ]);
    });

    it("toggles to descending when the same header is selected twice", async () => {
      const user = userEvent.setup();
      render(<AssetDataGrid titles={TITLES} />);

      const priceHeader = screen.getByRole("button", { name: /Asking Price/ });
      await user.click(priceHeader);
      await user.click(priceHeader);

      expect(rowTitleOrder()).toEqual([
        "Charlie's Saga",
        "Bravo Nights",
        "Alpha Dawn",
      ]);
    });

    it("sorts CPVH status by severity ranking rather than alphabetically", async () => {
      const user = userEvent.setup();
      render(<AssetDataGrid titles={TITLES} />);

      await user.click(screen.getByRole("button", { name: /CPVH Status/ }));

      // Rank order ascending: PASS(0) < NO_CEILING(1) < BREACH(2)
      expect(rowTitleOrder()).toEqual([
        "Charlie's Saga", // PASS
        "Bravo Nights", // NO_CEILING
        "Alpha Dawn", // BREACH
      ]);
    });

    it("reflects the active sort direction via aria-sort on the header cell", async () => {
      const user = userEvent.setup();
      render(<AssetDataGrid titles={TITLES} />);

      const titleHeaderCell = screen.getByRole("columnheader", {
        name: /Title/,
      });
      expect(titleHeaderCell).toHaveAttribute("aria-sort", "ascending");

      await user.click(screen.getByRole("button", { name: /^Title/ }));
      expect(titleHeaderCell).toHaveAttribute("aria-sort", "descending");
    });
  });

  describe("row-click navigation (R14.5)", () => {
    it("navigates to the title evaluation view when a row is clicked", async () => {
      const user = userEvent.setup();
      render(<AssetDataGrid titles={TITLES} />);

      await user.click(
        screen.getByRole("button", { name: "Open evaluation for Alpha Dawn" }),
      );

      expect(pushMock).toHaveBeenCalledTimes(1);
      expect(pushMock).toHaveBeenCalledWith("/titles/t-alpha");
    });

    it("navigates when a row is activated via the keyboard", async () => {
      const user = userEvent.setup();
      render(<AssetDataGrid titles={TITLES} />);

      const row = screen.getByRole("button", {
        name: "Open evaluation for Bravo Nights",
      });
      row.focus();
      await user.keyboard("{Enter}");

      expect(pushMock).toHaveBeenCalledWith("/titles/t-bravo");
    });

    it("does not navigate on a sort-header click", async () => {
      const user = userEvent.setup();
      render(<AssetDataGrid titles={TITLES} />);

      await user.click(screen.getByRole("button", { name: /Asking Price/ }));

      expect(pushMock).not.toHaveBeenCalled();
    });
  });
});
