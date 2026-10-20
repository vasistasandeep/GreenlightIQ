import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TopNav } from "@/components/layout/top-nav";

/**
 * TopNav mobile-navigation tests (mobile-ux-improvements, Req 4).
 *
 * The desktop inline nav is sm:flex and the overlay is sm:hidden; jsdom has no
 * layout engine, so both the toggle and the overlay are in the DOM and directly
 * assertable. We mock next/navigation's usePathname (the only external hook) and
 * provide a controllable window.matchMedia stub so the resize auto-close path is
 * testable.
 */

const pathname = vi.hoisted(() => ({ value: "/dashboard" }));
vi.mock("next/navigation", () => ({
  usePathname: () => pathname.value,
}));

// Controllable matchMedia stub: tests can fire a `change` with matches=true.
type MqlListener = (e: MediaQueryListEvent) => void;
const mqListeners: MqlListener[] = [];

beforeEach(() => {
  pathname.value = "/dashboard";
  mqListeners.length = 0;
  document.body.style.overflow = "";
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: (_: string, cb: MqlListener) => mqListeners.push(cb),
    removeEventListener: (_: string, cb: MqlListener) => {
      const i = mqListeners.indexOf(cb);
      if (i >= 0) mqListeners.splice(i, 1);
    },
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
});

afterEach(() => {
  document.body.style.overflow = "";
});

function toggle() {
  return screen.getByRole("button", { name: /navigation menu/i });
}

function overlayLink(name: RegExp) {
  // The overlay menu region has aria-label="Site"; scope the query to it.
  const region = screen.queryByRole("navigation", { name: "Site" });
  if (!region) return null;
  return within(region).queryByRole("link", { name });
}


describe("TopNav mobile navigation", () => {
  it("toggle opens and closes the menu (Req 4.1)", async () => {
    const user = userEvent.setup();
    render(<TopNav />);

    expect(screen.queryByRole("navigation", { name: "Site" })).toBeNull();
    await user.click(toggle());
    expect(screen.getByRole("navigation", { name: "Site" })).toBeInTheDocument();
    await user.click(toggle());
    expect(screen.queryByRole("navigation", { name: "Site" })).toBeNull();
  });

  it("aria-expanded reflects open/closed state (Req 4.2)", async () => {
    const user = userEvent.setup();
    render(<TopNav />);

    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle());
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    await user.click(toggle());
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
  });

  it("aria-controls matches the rendered menu region id (Req 2.2)", async () => {
    const user = userEvent.setup();
    render(<TopNav />);

    const controls = toggle().getAttribute("aria-controls");
    expect(controls).toBeTruthy();
    await user.click(toggle());
    expect(document.getElementById(controls as string)).not.toBeNull();
  });

  it("exposes all four destinations in the overlay (Req 4.3)", async () => {
    const user = userEvent.setup();
    render(<TopNav />);
    await user.click(toggle());

    expect(overlayLink(/^Dashboard$/)).toBeInTheDocument();
    expect(overlayLink(/^Asset Studio$/)).toBeInTheDocument();
    expect(overlayLink(/^Backtest Studio$/)).toBeInTheDocument();
    expect(overlayLink(/^How It Works$/)).toBeInTheDocument();
  });

  it("Escape closes the menu and restores focus to the toggle", async () => {
    const user = userEvent.setup();
    render(<TopNav />);
    await user.click(toggle());
    expect(screen.getByRole("navigation", { name: "Site" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("navigation", { name: "Site" })).toBeNull();
    expect(document.activeElement).toBe(toggle());
  });

  it("selecting a link closes the menu (Req 1.5)", async () => {
    const user = userEvent.setup();
    render(<TopNav />);
    await user.click(toggle());

    await user.click(overlayLink(/^Backtest Studio$/) as HTMLElement);
    expect(screen.queryByRole("navigation", { name: "Site" })).toBeNull();
  });

  it("marks the active destination with aria-current in both navs (Req 1.6/3.3)", async () => {
    const user = userEvent.setup();
    pathname.value = "/backtest";
    render(<TopNav />);

    // Desktop inline link.
    const desktop = screen.getAllByRole("link", { name: /^Backtest Studio$/ });
    expect(desktop.some((a) => a.getAttribute("aria-current") === "page")).toBe(true);

    // Overlay link.
    await user.click(toggle());
    expect(overlayLink(/^Backtest Studio$/)).toHaveAttribute("aria-current", "page");
  });

  it("locks body scroll while open and restores it on close", async () => {
    const user = userEvent.setup();
    render(<TopNav />);

    expect(document.body.style.overflow).toBe("");
    await user.click(toggle());
    expect(document.body.style.overflow).toBe("hidden");
    await user.click(toggle());
    expect(document.body.style.overflow).toBe("");
  });

  it("auto-closes and releases the lock when the viewport reaches desktop width", async () => {
    const user = userEvent.setup();
    render(<TopNav />);
    await user.click(toggle());
    expect(document.body.style.overflow).toBe("hidden");

    // Simulate a resize/rotate to >= sm: fire the matchMedia change with matches=true.
    act(() => {
      mqListeners.forEach((cb) => cb({ matches: true } as MediaQueryListEvent));
    });

    expect(screen.queryByRole("navigation", { name: "Site" })).toBeNull();
    expect(document.body.style.overflow).toBe("");
  });
});