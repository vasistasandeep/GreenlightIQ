"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/**
 * TopNav - the single shared navigation bar across the portal.
 *
 * The logo returns home; the links jump between the four main areas with the
 * active one highlighted. Dark theme to match the Asset Studio and guide. Used
 * by every page so navigation is consistent and nobody gets stranded.
 */

const LINKS: { href: string; label: string }[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/studio", label: "Asset Studio" },
  { href: "/backtest", label: "Backtest Studio" },
  { href: "/guide", label: "How It Works" },
];

export function TopNav() {
  const pathname = usePathname() ?? "";

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

        {/* Primary links */}
        <nav className="flex items-center gap-1 text-sm">
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
              <span className="hidden sm:inline">{l.label}</span>
              <span className="sm:hidden">{l.label.split(" ")[0]}</span>
            </Link>
          ))}
        </nav>
      </div>
    </header>
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