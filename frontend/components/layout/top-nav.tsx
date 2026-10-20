"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * TopNav - the single shared navigation bar across the portal.
 *
 * The logo returns home; the links jump between the four main areas with the
 * active one highlighted. On desktop (>= sm) the four links render inline. On
 * mobile (< sm) they collapse behind a hamburger toggle that opens a fixed
 * overlay drawer (so opening it never shifts page layout), with backdrop/Escape
 * dismissal, focus management, body scroll lock, and an auto-close when the
 * viewport grows back to desktop width.
 */

const LINKS: { href: string; label: string }[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/studio", label: "Asset Studio" },
  { href: "/backtest", label: "Backtest Studio" },
  { href: "/guide", label: "How It Works" },
];

const MENU_ID = "mobile-nav-menu";

export function TopNav() {
  const pathname = usePathname() ?? "";
  const [menuOpen, setMenuOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const closeMenu = useCallback(() => setMenuOpen(false), []);

  function isActive(href: string): boolean {
    return pathname === href || pathname.startsWith(href + "/");
  }

  return (
    <header className="sticky top-0 z-30 border-b border-slate-800 bg-slate-950/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
        {/* Logo -> home */}
        <Link href="/" className="group flex items-center gap-2.5 shrink-0">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-400 to-emerald-600 text-emerald-950 shadow-sm shadow-emerald-900/40 ring-1 ring-white/10 transition group-hover:scale-105">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M3 17l6-6 4 4 7-8" />
              <path d="M14 7h6v6" />
            </svg>
          </span>
          <span className="text-base font-bold tracking-tight text-slate-100">
            CineROI<span className="text-emerald-400"> AI</span>
          </span>
          <span className="hidden text-[10px] uppercase tracking-widest text-slate-500 md:inline">
            Greenlight Intelligence
          </span>
        </Link>

        {/* Desktop inline links (>= sm) */}
        <nav className="hidden items-center gap-1 text-sm sm:flex">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              aria-current={isActive(l.href) ? "page" : undefined}
              className={cn(
                "rounded-md px-3 py-1.5 font-medium transition-colors",
                isActive(l.href)
                  ? "bg-emerald-500/15 text-emerald-300"
                  : "text-slate-300 hover:bg-slate-800 hover:text-slate-100",
              )}
            >
              {l.label}
            </Link>
          ))}
        </nav>

        {/* Mobile hamburger toggle (< sm) */}
        <button
          ref={toggleRef}
          type="button"
          aria-expanded={menuOpen}
          aria-controls={MENU_ID}
          aria-label={menuOpen ? "Close navigation menu" : "Open navigation menu"}
          onClick={() => setMenuOpen((o) => !o)}
          className="inline-flex h-11 w-11 items-center justify-center rounded-md text-slate-300 hover:bg-slate-800 hover:text-slate-100 sm:hidden"
        >
          <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            {menuOpen ? (
              <>
                <path d="M18 6 6 18" />
                <path d="m6 6 12 12" />
              </>
            ) : (
              <>
                <path d="M3 12h18" />
                <path d="M3 6h18" />
                <path d="M3 18h18" />
              </>
            )}
          </svg>
        </button>
      </div>

      <MobileMenu
        open={menuOpen}
        onClose={closeMenu}
        links={LINKS}
        isActive={isActive}
        menuId={MENU_ID}
        toggleRef={toggleRef}
      />
    </header>
  );
}

interface MobileMenuProps {
  open: boolean;
  onClose: () => void;
  links: { href: string; label: string }[];
  isActive: (href: string) => boolean;
  menuId: string;
  toggleRef: React.RefObject<HTMLButtonElement>;
}

function MobileMenu({ open, onClose, links, isActive, menuId, toggleRef }: MobileMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  // Focus into the menu on open; Escape closes and restores focus to the toggle.
  useEffect(() => {
    if (!open) return;
    const firstLink = menuRef.current?.querySelector<HTMLElement>("a");
    firstLink?.focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        toggleRef.current?.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose, toggleRef]);

  // Body scroll lock + auto-close when the viewport reaches desktop width, so the
  // lock can never be stranded by a rotate/resize that hides the overlay.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const mq = window.matchMedia("(min-width: 640px)");
    const handleChange = (e: MediaQueryListEvent) => {
      if (e.matches) onClose();
    };
    mq.addEventListener("change", handleChange);

    return () => {
      document.body.style.overflow = prev;
      mq.removeEventListener("change", handleChange);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="sm:hidden">
      {/* Backdrop: tap to dismiss. cursor-pointer so iOS Safari fires the tap. */}
      <div
        aria-hidden
        onClick={onClose}
        className="fixed inset-0 z-40 cursor-pointer bg-slate-950/90 backdrop-blur-sm motion-safe:transition-opacity"
      />
      {/* Menu region: fixed dropdown under the h-14 bar; scrolls in short/landscape viewports. */}
      <div
        ref={menuRef}
        id={menuId}
        role="navigation"
        aria-label="Site"
        className="fixed inset-x-0 top-14 z-50 max-h-[calc(100dvh-3.5rem)] overflow-y-auto border-b border-slate-800 bg-slate-950/95 p-2 backdrop-blur motion-safe:transition-transform"
      >
        {links.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            onClick={onClose}
            aria-current={isActive(l.href) ? "page" : undefined}
            className={cn(
              "flex min-h-[44px] items-center rounded-md px-3 text-sm font-medium",
              isActive(l.href)
                ? "bg-emerald-500/15 text-emerald-300"
                : "text-slate-300 hover:bg-slate-800 hover:text-slate-100",
            )}
          >
            {l.label}
          </Link>
        ))}
      </div>
    </div>
  );
}

/**
 * AppShell - wraps a page in the dark portal chrome: shared TopNav + a centered
 * content container. Pages render their own content inside.
 */
export function AppShell({
  children,
  maxWidth = "max-w-7xl",
}: {
  children: React.ReactNode;
  maxWidth?: string;
}) {
  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-950 to-slate-900 text-slate-100">
      <TopNav />
      <main className={cn("mx-auto px-4 py-8 sm:px-6", maxWidth)}>{children}</main>
    </div>
  );
}