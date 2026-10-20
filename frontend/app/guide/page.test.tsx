import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import GuidePage from "@/app/guide/page";

/**
 * Guide tablist keyboard navigation (mobile-ux-improvements, Req 5.4).
 *
 * The guide tabs use a roving tabindex with ArrowLeft/ArrowRight (wrap-around).
 * GuidePage renders the shared TopNav (usePathname), so next/navigation is
 * mocked. scrollIntoView is not implemented in jsdom, so it is stubbed.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/guide",
}));

beforeEach(() => {
  // jsdom has no layout engine; the active-tab centering effect calls this.
  Element.prototype.scrollIntoView = vi.fn();
});

function tab(name: RegExp) {
  return screen.getByRole("tab", { name });
}

describe("Guide tablist keyboard navigation", () => {
  it("moves the selection with ArrowRight / ArrowLeft (Req 5.4)", async () => {
    const user = userEvent.setup();
    render(<GuidePage />);

    const overview = tab(/^Overview$/);
    expect(overview).toHaveAttribute("aria-selected", "true");

    await user.click(overview); // focus the active tab
    fireEvent.keyDown(overview, { key: "ArrowRight" });

    // The second tab becomes selected.
    expect(tab(/Features/)).toHaveAttribute("aria-selected", "true");
    expect(overview).toHaveAttribute("aria-selected", "false");
  });

  it("wraps from the first tab to the last on ArrowLeft (Req 5.4)", async () => {
    const user = userEvent.setup();
    render(<GuidePage />);

    const overview = tab(/^Overview$/);
    await user.click(overview);
    fireEvent.keyDown(overview, { key: "ArrowLeft" });

    // Wrap-around: the last tab (Glossary) becomes selected.
    expect(tab(/Glossary/)).toHaveAttribute("aria-selected", "true");
  });
});

describe("Guide glossary improvements", () => {
  async function openGlossary(user: ReturnType<typeof userEvent.setup>) {
    render(<GuidePage />);
    await user.click(screen.getByRole("tab", { name: /Glossary/ }));
  }

  it("filters to a single category when a chip is pressed", async () => {
    const user = userEvent.setup();
    await openGlossary(user);

    // Both an inputs-group heading and a governance-group heading are shown initially.
    expect(screen.getByRole("heading", { name: /What You Enter/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Governance & Trust/ })).toBeInTheDocument();

    // Press the "Governance & Trust" chip (aria-pressed toggle).
    const chip = screen.getByRole("button", { name: "Governance & Trust" });
    await user.click(chip);
    expect(chip).toHaveAttribute("aria-pressed", "true");

    // Now only the governance group heading remains.
    expect(screen.getByRole("heading", { name: /Governance & Trust/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /What You Enter/ })).toBeNull();

    // Pressing "All" restores every group.
    await user.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByRole("heading", { name: /What You Enter/ })).toBeInTheDocument();
  });

  it("narrows results by search text", async () => {
    const user = userEvent.setup();
    await openGlossary(user);

    const search = screen.getByLabelText(/search glossary terms/i);
    await user.type(search, "payback");

    // The matched substring is highlighted in a <mark>, so assert via that
    // (text is split across nodes by the highlighter) and that an unrelated
    // term (RBAC) is filtered out entirely.
    const marks = document.querySelectorAll("mark");
    expect(marks.length).toBeGreaterThan(0);
    expect(
      Array.from(marks).some((m) => /payback/i.test(m.textContent ?? "")),
    ).toBe(true);
    expect(screen.queryByText(/^RBAC$/)).toBeNull();
  });
});
