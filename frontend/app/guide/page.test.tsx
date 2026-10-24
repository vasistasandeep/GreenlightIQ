import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import GuidePage from "@/app/guide/page";

/**
 * Guide tablist arrow-key navigation test (mobile-ux-improvements, Req 5.4).
 *
 * The guide tabs use a roving-tabindex tablist: the selected tab is tabIndex=0,
 * the rest tabIndex=-1, and ArrowRight/ArrowLeft move the selection (with
 * wrap-around). This mirrors the design's Decision 2 (scroll-snap strip +
 * roving tabindex + arrow keys). We only assert the keyboard selection moves
 * aria-selected to the adjacent tab; the strip/scroll behavior is visual.
 *
 * GuidePage renders TopNav (which calls usePathname), so next/navigation is
 * mocked as elsewhere in the suite. The active-tab effect calls scrollIntoView,
 * which jsdom does not implement, so it is stubbed.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/guide",
}));

beforeAll(() => {
  // jsdom has no layout engine; scrollIntoView is undefined there.
  Element.prototype.scrollIntoView = vi.fn();
});

beforeEach(() => {
  vi.clearAllMocks();
});

/** The six guide tabs in order, matching TABS in guide/page.tsx. */
const TAB_NAMES = [
  "Overview",
  "Features & How-To",
  "The 4 Guardrails",
  "How Numbers Are Calculated",
  "Worked Examples",
  "Glossary",
];

function tab(name: string) {
  return screen.getByRole("tab", { name });
}

describe("Guide tablist arrow-key navigation (Req 5.4)", () => {
  it("starts with the first tab selected", () => {
    render(<GuidePage />);
    expect(tab("Overview")).toHaveAttribute("aria-selected", "true");
    expect(tab("Features & How-To")).toHaveAttribute("aria-selected", "false");
  });

  it("ArrowRight moves the active tab to the next tab", () => {
    render(<GuidePage />);
    const first = tab("Overview");
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });

    expect(tab("Overview")).toHaveAttribute("aria-selected", "false");
    expect(tab("Features & How-To")).toHaveAttribute("aria-selected", "true");
  });

  it("ArrowLeft moves the active tab to the previous tab", () => {
    render(<GuidePage />);
    // Move right once first so there is a previous tab to return to.
    const first = tab("Overview");
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowRight" });

    const second = tab("Features & How-To");
    fireEvent.keyDown(second, { key: "ArrowLeft" });
    expect(tab("Overview")).toHaveAttribute("aria-selected", "true");
  });

  it("ArrowLeft from the first tab wraps around to the last tab", () => {
    render(<GuidePage />);
    const first = tab("Overview");
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowLeft" });

    expect(tab("Overview")).toHaveAttribute("aria-selected", "false");
    expect(tab(TAB_NAMES[TAB_NAMES.length - 1])).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("ArrowRight from the last tab wraps around to the first tab", () => {
    render(<GuidePage />);
    // Wrap left to land on the last tab, then press right to wrap forward.
    const first = tab("Overview");
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowLeft" });

    const last = tab(TAB_NAMES[TAB_NAMES.length - 1]);
    fireEvent.keyDown(last, { key: "ArrowRight" });
    expect(tab("Overview")).toHaveAttribute("aria-selected", "true");
  });
});
