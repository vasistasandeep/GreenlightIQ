"use client";

/**
 * TitleTabs - switches the title page between the saved Scorecard and the
 * read-only What-If Explorer. URL-driven (?tab=what-if) so a Scenario_Link
 * lands directly on the explorer. Excluded from print via `no-print` on the bar.
 */

import { useRouter, useSearchParams } from "next/navigation";

export type TitleTab = "scorecard" | "what-if";

export function TitleTabs({
  titleId,
  active,
}: {
  titleId: string;
  active: TitleTab;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  function go(tab: TitleTab) {
    const params = new URLSearchParams(searchParams.toString());
    if (tab === "scorecard") params.delete("tab");
    else params.set("tab", tab);
    const qs = params.toString();
    router.replace(qs ? `/titles/${titleId}?${qs}` : `/titles/${titleId}`, { scroll: false });
  }

  const tabs: { id: TitleTab; label: string }[] = [
    { id: "scorecard", label: "Scorecard" },
    { id: "what-if", label: "What-If Explorer" },
  ];

  return (
    <div className="no-print mb-6 flex gap-1 rounded-lg border border-slate-800 bg-slate-900/60 p-1" role="tablist" aria-label="Title views">
      {tabs.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={active === t.id}
          onClick={() => go(t.id)}
          className={
            "flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition " +
            (active === t.id ? "bg-emerald-500/15 text-emerald-300" : "text-slate-300 hover:bg-slate-800 hover:text-slate-100")
          }
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}