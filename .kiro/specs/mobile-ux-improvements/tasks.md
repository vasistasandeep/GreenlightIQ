# Implementation Plan: Mobile UX Improvements

## Overview

This plan turns the mobile UX-polish design into incremental coding steps for the
four named components (`top-nav.tsx`, `guide/page.tsx`, `asset-data-grid.tsx`,
`backtest/page.tsx`) plus one new navigation test file. The only piece with real
interactive logic — the TopNav mobile overlay — is built and tested first, then the
guide tablist, then the two class-level polish surfaces, then a dedicated
desktop-invariance check, and finally a green-build verification task.

All work is in TypeScript/React (TSX) with Tailwind, matching the existing frontend.
No new pages, runtime dependencies, global CSS, color/brand changes, snackbar/toast,
or edits to `presentation/index.html` (Req 7). Scope is strictly the four components
and the one test file (Req 7.3).

## Tasks

- [x] 1. Build the TopNav mobile navigation (hamburger toggle + overlay drawer)
  - [x] 1.1 Refactor the desktop inline nav and add shared TopNav state
    - In `frontend/components/layout/top-nav.tsx`, change the existing inline `<nav>` link container to `hidden sm:flex` and delete the per-link `sm:hidden` first-word label-shortening spans so desktop renders full labels
    - Preserve the existing active-item classes (`bg-emerald-500/15 text-emerald-300`) and `aria-current="page"` on the matching desktop link verbatim
    - Add the single source of state in `TopNav`: `const [menuOpen, setMenuOpen] = useState(false)`, `const toggleRef = useRef<HTMLButtonElement>(null)`, `const MENU_ID = "mobile-nav-menu"`, and a stable `const closeMenu = useCallback(() => setMenuOpen(false), [])`
    - Keep the shared `LINKS` array and the `usePathname`-based `isActive(href)` test single-sourced for both navs
    - _Requirements: 3.1, 3.2, 3.3, 1.6, 7.5_
    - _Design: Property 6 (Desktop invariance)_

  - [x] 1.2 Add the hamburger toggle button
    - Render a `sm:hidden` toggle `<button>` with `ref={toggleRef}`, `type="button"`, `aria-expanded={menuOpen}`, `aria-controls={MENU_ID}`, and `aria-label` that reads "Open navigation menu" / "Close navigation menu" based on `menuOpen`
    - Wire `onClick` to `setMenuOpen((o) => !o)` (functional toggle for rapid-activation coherence)
    - Size the control `h-11 w-11` (44x44px) and render a hamburger icon when closed / X when open, each `aria-hidden`
    - _Requirements: 1.3, 1.4, 2.1, 2.2, 2.3, 2.5, 3.2_
    - _Design: Property 1 (Open/close symmetry), Property 2 (ARIA state fidelity)_

  - [x] 1.3 Implement the MobileMenu overlay drawer (backdrop + menu region)
    - Define `MobileMenu` inside `top-nav.tsx` (per Req 7.3) with the `MobileMenuProps` interface from the design (`open`, `onClose`, `links`, `isActive`, `menuId`, `toggleRef`)
    - Render only when `open`, wrapped in a `sm:hidden` container so it never shows at desktop
    - Backdrop: `fixed inset-0 z-40 cursor-pointer bg-slate-950/90 backdrop-blur-sm motion-safe:transition-opacity`, `aria-hidden`, `onClick={onClose}` (cursor-pointer required for iOS tap dismissal)
    - Menu region: `id={menuId}`, `role="navigation"`, `aria-label="Site"`, classes `fixed inset-x-0 top-14 z-50 max-h-[calc(100dvh-3.5rem)] overflow-y-auto ... motion-safe:transition-transform` (z-50 menu / z-40 backdrop over the z-30 header; `top-14` under the `h-14` bar; max-height + overflow for landscape/short viewports)
    - Render each destination as a `next/link` `<Link>` with `onClick={onClose}`, `min-h-[44px]`, `aria-current={isActive(href) ? "page" : undefined}`, and the shared active/inactive classes
    - Wire `TopNav` to render `<MobileMenu open={menuOpen} onClose={closeMenu} ... />`
    - _Requirements: 1.1, 1.2, 1.5, 1.6, 2.5, 2.6_
    - _Design: Property 1, Property 3 (Destination completeness), Edge Cases: iOS backdrop dismissal, landscape height clamping_

  - [x] 1.4 Add Escape + focus management effect
    - On `open` becoming true, move focus into the menu (focus the first link / menu region) so links are keyboard-reachable (Req 2.4)
    - While open, add a `keydown` listener that closes on `Escape` and restores focus to `toggleRef.current`; clean up the listener on close/unmount
    - _Requirements: 2.4_
    - _Design: Property 4 (Focus round-trip)_

  - [x] 1.5 Add body scroll-lock + resize/orientation auto-close effect
    - While `open`, set `document.body.style.overflow = "hidden"`, capturing the prior value
    - Register `window.matchMedia("(min-width: 640px)")` and call `onClose` on a `change` whose `matches` is true (the rotate/resize scroll-lock trap)
    - Return a cleanup that restores the prior `overflow` value and removes the listener on close, unmount, and breakpoint-triggered close; depend on `[open, onClose]` with `onClose` stable via `useCallback`
    - _Requirements: 1.1_
    - _Design: Property 5 (Scroll-lock conservation), Edge Case: scroll-lock trap on rotate/resize_

- [x] 2. Write the required TopNav navigation tests
  - [x] 2.1 Create `top-nav.test.tsx` covering open/close, ARIA, destinations, focus, and scroll-lock
    - New file `frontend/components/layout/top-nav.test.tsx` using vitest + `@testing-library/react` + `@testing-library/user-event`, mirroring `frontend/components/backtest/ground-truth-form.test.tsx`; mock `next/navigation` `usePathname` to control the active route
    - Toggle open/close: overlay links absent initially, present after clicking the toggle (`getByRole("button", { name: /open navigation menu/i })`), gone after a second click (Req 4.1)
    - `aria-expanded` is `false`, then `true` after open, then `false` after close (Req 4.2)
    - `aria-controls` value matches the `id` of a rendered menu-region element when open (Req 2.2)
    - All four destinations present as links: Dashboard, Asset Studio, Backtest Studio, How It Works (Req 4.3)
    - Escape closes the overlay and restores `document.activeElement` to the toggle
    - Link click closes the overlay (Req 1.5)
    - Active item: with a mocked pathname, the matching link carries `aria-current="page"` (Req 1.6/3.3)
    - Resize to desktop auto-closes + releases lock: mock `window.matchMedia`, dispatch a `change` with `matches: true`, assert overlay closed and `document.body.style.overflow` restored
    - Scroll-lock set/restore: `document.body.style.overflow` is `"hidden"` while open and restored after close/unmount
    - _Requirements: 4.1, 4.2, 4.3, 2.2, 1.5, 1.6_
    - _Design: Property 1, Property 2, Property 3, Property 4, Property 5_

- [x] 3. Checkpoint - TopNav complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Redesign the guide tablist for mobile
  - [x] 4.1 Convert the tablist container to a mobile scroll-snap strip
    - In `frontend/app/guide/page.tsx`, change the `role="tablist"` container from `flex flex-wrap gap-1 ...` to a single-row `flex gap-2 overflow-x-auto scroll-smooth ... snap-x` strip with the inline no-scrollbar arbitrary variants (`[scrollbar-width:none]` and `[&::-webkit-scrollbar]:hidden`), restoring wrap at desktop with `sm:flex-wrap sm:overflow-visible`
    - Make each tab `flex-shrink-0 snap-start` so tabs keep size and snap instead of wrapping
    - Preserve `role="tablist"` on the container and `role="tab"` + `aria-selected` on each tab (and `role="tabpanel"` on the body)
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 7.4_
    - _Design: Decision 2 (scroll-snap strip), Decision 3 (no-scrollbar via inline variants)_

  - [x] 4.2 Add roving tabindex + ArrowLeft/Right keyboard navigation
    - Add `tabRefs` (array or map keyed by `TabId`); set the selected tab `tabIndex={0}` and all others `tabIndex={-1}`
    - Add a shared `onKeyDown(e, index)` handling `ArrowRight`/`ArrowLeft` with wrap-around (optionally `Home`/`End`), calling `setTab(next)` and focusing the new tab button; keep `aria-selected` reflecting the selection
    - _Requirements: 5.4_
    - _Design: Decision 2 (roving tabindex + arrow keys)_

  - [x] 4.3 Center the active tab with a first-mount-guarded scrollIntoView effect
    - Add a `useEffect` on `tab` that calls `scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" })` on the active tab ref
    - Guard the first mount with an `isFirstTabEffect` ref so no horizontal scroll jump fires on initial load; animate only on subsequent tab changes
    - _Requirements: 5.2_
    - _Design: Edge Case: guide initial-mount scroll jump_

  - [x]* 4.4 Write a light guide arrow-key test
    - Render `GuidePage`, focus a tab, fire `ArrowRight`/`ArrowLeft`, and assert `aria-selected` moves to the adjacent tab (wrap-around)
    - _Requirements: 5.4_

- [x] 5. Polish the data grid toolbar tap targets
  - [x] 5.1 Add mobile min-height to the toolbar controls
    - In `frontend/components/dashboard/asset-data-grid.tsx`, append `min-h-[44px] sm:min-h-0` to the existing class strings of the search input, the two `<select>`s, and the clear-filters button
    - Leave the `overflow-x-auto` table wrapper exactly as is so wide content scrolls rather than clips
    - _Requirements: 6.1, 6.2_
    - _Design: Shared control polish (data grid toolbar)_

- [x] 6. Confirm backtest pane stacking and tap sizing
  - [x] 6.1 Verify/adjust backtest panes for mobile stacking and spacing
    - In `frontend/app/backtest/page.tsx`, confirm the `grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,22rem)_1fr]` stacks to one column with vertical spacing below `lg` and restores the two-column split at `lg`
    - Ensure any interactive controls this page owns meet the >=44px tap-height convention; make minimal/no structural change
    - _Requirements: 6.3, 6.4_
    - _Design: Shared control polish (backtest panes)_

- [x] 7. Verify desktop invariance is preserved
  - [x] 7.1 Audit the `sm:`/`lg:` restores across all four components
    - Confirm the overlay/toggle are `sm:hidden`, the inline nav is `hidden sm:flex` with full labels and original active styling, the guide tablist restores `sm:flex-wrap sm:overflow-visible`, the toolbar bumps revert with `sm:min-h-0`, and the backtest grid keeps `lg:grid-cols-[minmax(0,22rem)_1fr]`
    - Confirm no color/brand change, no new page/dependency/global CSS, no snackbar/toast, and `presentation/index.html` untouched
    - _Requirements: 3.1, 3.2, 3.3, 7.3, 7.4, 7.5_
    - _Design: Property 6 (Desktop invariance), Desktop-invariance guarantee_

- [x] 8. Final checkpoint - run frontend typecheck, lint, and vitest
  - Run the frontend typecheck, lint, and vitest suite and confirm all are green; fix any failures surfaced in the four components or the new test file
  - Manual spot-check at ~360-430px and >=640px is a reasonable follow-up but is not a coding task
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 4.1, 4.2, 4.3, 7.5_

## Notes

- Tasks marked with `*` are optional-but-recommended and can be skipped for a faster MVP. The TopNav test file (task 2.1) is required by Req 4 and is NOT optional.
- Each task references the specific requirements and design Correctness Properties it satisfies for traceability.
- The design states property-based testing is not appropriate here (UI rendering + ARIA/keyboard interaction); the "properties" are example-level invariants enforced by the React Testing Library tests, so there are no stand-alone PBT tasks.
- Checkpoints (tasks 3 and 8) provide incremental validation.
- Scope is strictly the four named components plus `top-nav.test.tsx`; no edits to `presentation/index.html`, no snackbar/toast, no global CSS (Req 7).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["1.4", "1.5"] },
    { "id": 3, "tasks": ["2.1"] },
    { "id": 4, "tasks": ["4.1"] },
    { "id": 5, "tasks": ["4.2", "4.3"] },
    { "id": 6, "tasks": ["4.4", "5.1", "6.1"] },
    { "id": 7, "tasks": ["7.1"] }
  ]
}
```
