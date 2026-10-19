import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/**
 * ContentEvalBreakdown component tests (task 18, R6.5, R8.1).
 *
 * Mirrors the churn-breakdown.test.tsx style: each driver card is a native
 * collapsed `<details>`, so tests click the summary to open it before asserting
 * on the per-feature table. The PROXY / illustrative badge lives in the summary
 * (visible without opening), and the "nothing rendered" cases for an absent
 * content_eval block are asserted on the container.
 */

import { ContentEvalBreakdown } from "./content-eval-breakdown";
import type { ContentEvalExplanation } from "@/lib/types";

/** A fitted content_eval block with a proxy-labeled viewing-hours + engagement driver. */
function fittedContentEval(
  overrides: Partial<ContentEvalExplanation> = {},
): ContentEvalExplanation {
  return {
    projected_viewing_hours: {
      value: "12500.0",
      method: "FITTED",
      version_label: "ce-vh-2024.1",
      label_type: "PROXY",
      params_source: "MODEL_VERSION",
      breakdown: [
        { key: "base_platform_hours", label: "Base Platform Hours", hours: "8000.0" },
        { key: "talent_pedigree", label: "Talent Pedigree", hours: "3000.0" },
        { key: "production_scale", label: "Production Scale", hours: "1500.0" },
        {
          key: "rounding_or_bounds_adjustment",
          label: "Rounding Adjustment",
          hours: "0.0",
        },
      ],
      missing_features: [],
      assumed_features: [],
    },
    watch_time_elasticity: {
      value: "1.35",
      method: "FITTED",
      version_label: "ce-eng-2024.1",
      label_type: "PROXY",
      params_source: "MODEL_VERSION",
      breakdown: [
        { key: "base", label: "Base", points: "1.00" },
        { key: "genre_affinity", label: "Genre Affinity", points: "0.35" },
        { key: "bounds_adjustment", label: "Bounds Adjustment", points: "0.00" },
      ],
      missing_features: [],
      assumed_features: [],
    },
    ...overrides,
  };
}

/** Open the named driver card and return its <details> element for scoped queries. */
async function open(title: string): Promise<HTMLElement> {
  const user = userEvent.setup();
  const summary = screen.getByText(title);
  await user.click(summary);
  return summary.closest("details") as HTMLElement;
}

describe("ContentEvalBreakdown (task 18)", () => {
  it("renders a card per modeled driver when content_eval is present (R6.5)", () => {
    render(<ContentEvalBreakdown contentEval={fittedContentEval()} />);
    expect(screen.getByText("Projected viewing hours")).toBeInTheDocument();
    expect(screen.getByText("Watch-time elasticity")).toBeInTheDocument();
  });

  it("renders the viewing-hours contribution table with hour values (R6.5)", async () => {
    render(<ContentEvalBreakdown contentEval={fittedContentEval()} />);
    const card = await open("Projected viewing hours");

    const table = within(card).getByRole("table");
    const rows: [string, string][] = [
      ["Base Platform Hours", "8,000.0"],
      ["Talent Pedigree", "3,000.0"],
      ["Production Scale", "1,500.0"],
    ];
    for (const [label, hours] of rows) {
      const row = within(table).getByText(label).closest("tr")!;
      expect(within(row).getByText(hours)).toBeInTheDocument();
    }
  });

  it("renders the engagement contribution table with signed point values", async () => {
    render(<ContentEvalBreakdown contentEval={fittedContentEval()} />);
    const card = await open("Watch-time elasticity");

    const table = within(card).getByRole("table");
    const row = within(table).getByText("Genre Affinity").closest("tr")!;
    expect(within(row).getByText("+0.35")).toBeInTheDocument();
  });

  it("shows a visible PROXY / illustrative badge for a modeled value (R8.1)", () => {
    render(<ContentEvalBreakdown contentEval={fittedContentEval()} />);
    // One badge per proxy-labeled driver card; text (not color) carries meaning.
    const badges = screen.getAllByText(/PROXY · illustrative/i);
    expect(badges.length).toBeGreaterThanOrEqual(2);
  });

  it("surfaces a SYNTHETIC label distinctly and never as a real figure", () => {
    render(
      <ContentEvalBreakdown
        contentEval={fittedContentEval({
          watch_time_elasticity: {
            ...fittedContentEval().watch_time_elasticity,
            label_type: "SYNTHETIC",
          },
        })}
      />,
    );
    expect(screen.getByText(/SYNTHETIC · illustrative/i)).toBeInTheDocument();
  });

  it("does NOT show a proxy badge for an OBSERVED driver", () => {
    render(
      <ContentEvalBreakdown
        contentEval={{
          projected_viewing_hours: {
            ...fittedContentEval().projected_viewing_hours,
            label_type: "OBSERVED",
          },
        }}
      />,
    );
    expect(screen.queryByText(/illustrative/i)).not.toBeInTheDocument();
  });

  it("renders nothing when content_eval is null or undefined (demo default)", () => {
    const { container, rerender } = render(
      <ContentEvalBreakdown contentEval={null} />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(<ContentEvalBreakdown contentEval={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when content_eval has no known driver keys", () => {
    const { container } = render(
      <ContentEvalBreakdown contentEval={{ unknown_driver: { value: "1" } }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("coerces string Decimals into formatted numbers via toNumber", async () => {
    render(<ContentEvalBreakdown contentEval={fittedContentEval()} />);
    await open("Projected viewing hours");
    // Resolved value "12500.0" (a JSON string) renders coerced + grouped.
    expect(screen.getByText("12,500.0")).toBeInTheDocument();
  });
});
