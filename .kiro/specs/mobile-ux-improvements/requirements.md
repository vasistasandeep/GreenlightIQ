# Requirements Document

## Introduction

This spec is a tightly scoped mobile UX-polish effort for the CineROI AI Next.js
frontend (App Router + Tailwind, dark theme). The goal is to make the portal clean
and usable on narrow phones (approximately 360-430px wide) without regressing the
existing desktop layout or behavior.

The work is grounded in three confirmed issues found by reading the code:

1. The shared top navigation (`frontend/components/layout/top-nav.tsx`) renders a
   logo plus four links in a single `justify-between` row. On mobile it only
   shortens labels to their first word (`label.split(" ")[0]`) and has no
   hamburger or overflow menu, so at 360px the logo and four links crowd and the
   right-most link is clipped.
2. The guide tab bar (`frontend/app/guide/page.tsx`) uses a `role="tablist"` with
   `flex flex-wrap gap-1` holding six tabs, which wraps into a clunky multi-row
   block on mobile. (The current tabs are also plain `onClick` buttons with no
   keyboard arrow-key navigation.)
3. General mobile spacing and tap-target sizing across the AppShell main padding,
   the dashboard data-grid filter toolbar
   (`frontend/components/dashboard/asset-data-grid.tsx`), and the backtest
   split-pane (`frontend/app/backtest/page.tsx`,
   `grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,22rem)_1fr]`).

This is responsive polish of existing components only. The mobile navigation is
the one piece with real interactive logic and therefore the only piece that gains
automated test coverage; everything else is visual/example-level change.

## Glossary

- **Portal**: The CineROI AI Next.js frontend application under `frontend/`.
- **TopNav**: The shared navigation component in `frontend/components/layout/top-nav.tsx` rendered on every page.
- **AppShell**: The layout wrapper in `frontend/components/layout/top-nav.tsx` that renders TopNav plus a centered `main` content container.
- **Mobile_Menu**: The new collapsible/overflow navigation surface shown on narrow viewports that exposes all four TopNav destinations.
- **Guide_Tablist**: The `role="tablist"` tab bar in `frontend/app/guide/page.tsx` holding the six guide section tabs.
- **Data_Grid_Toolbar**: The filter/search toolbar in `frontend/components/dashboard/asset-data-grid.tsx` (search input, recommendation select, deal-stage select, clear-filters button).
- **Backtest_Panes**: The two-column split-pane layout in `frontend/app/backtest/page.tsx` (ground-truth input pane and results pane).
- **Mobile viewport**: A viewport width in the approximate range 360px to 430px, below Tailwind's `sm` breakpoint.
- **Desktop viewport**: A viewport width at or above Tailwind's `sm` breakpoint (and, where noted, `lg`), where the current layout must remain visually unchanged.
- **Tap target**: The interactive hit area of a control, measured as its rendered width and height.

## Requirements

### Requirement 1: Mobile navigation that fits the viewport

**User Story:** As a phone user, I want the top navigation to fit my screen and expose every destination, so that I can reach all four areas of the portal without any link being cut off.

#### Acceptance Criteria

1. WHILE the viewport is a Mobile viewport, THE TopNav SHALL render all of its content (logo and navigation control) within the viewport width without horizontal clipping or overflow.
2. WHILE the viewport is a Mobile viewport, THE TopNav SHALL expose the four destinations (Dashboard, Asset Studio, Backtest Studio, How It Works) through the Mobile_Menu rather than as four always-visible inline links.
3. WHEN a user activates the Mobile_Menu toggle WHILE the Mobile_Menu is closed, THE TopNav SHALL open the Mobile_Menu and reveal links to all four destinations.
4. WHEN a user activates the Mobile_Menu toggle WHILE the Mobile_Menu is open, THE TopNav SHALL close the Mobile_Menu.
5. WHEN a user selects a destination link from the Mobile_Menu, THE TopNav SHALL navigate to that destination and close the Mobile_Menu.
6. WHILE the Mobile_Menu is displayed, THE TopNav SHALL indicate the destination matching the current route as the active item.

### Requirement 2: Accessible and usable mobile navigation

**User Story:** As a keyboard or screen-reader user on a phone, I want the mobile navigation to be operable and clearly labeled, so that I can open it, understand its state, and reach every destination.

#### Acceptance Criteria

1. THE Mobile_Menu toggle SHALL expose an `aria-expanded` state that reads `true` WHILE the Mobile_Menu is open and `false` WHILE the Mobile_Menu is closed.
2. THE Mobile_Menu toggle SHALL reference the controlled menu region via an `aria-controls` attribute whose value matches the identifier of that region.
3. THE Mobile_Menu toggle SHALL expose an accessible name that identifies the control as the site navigation menu.
4. WHEN a user opens the Mobile_Menu using the keyboard, THE TopNav SHALL move keyboard focus into the Mobile_Menu so that the revealed links are reachable by keyboard.
5. THE Mobile_Menu toggle and each Mobile_Menu destination link SHALL render with a tap target of at least 44px by 44px on a Mobile viewport.
6. WHERE a new transition or animation is introduced for opening or closing the Mobile_Menu, THE TopNav SHALL honor the user's reduced-motion preference by suppressing or minimizing that motion.

### Requirement 3: Desktop navigation unchanged

**User Story:** As a desktop user, I want the navigation to look and behave exactly as it does today, so that the mobile polish introduces no regression on larger screens.

#### Acceptance Criteria

1. WHILE the viewport is a Desktop viewport, THE TopNav SHALL display the four destinations as inline links with their full labels, matching the current layout.
2. WHILE the viewport is a Desktop viewport, THE TopNav SHALL NOT display the Mobile_Menu toggle.
3. WHILE the viewport is a Desktop viewport, THE TopNav SHALL apply the existing active-item highlight styling to the destination matching the current route.

### Requirement 4: Mobile navigation test coverage

**User Story:** As a maintainer, I want automated tests for the mobile navigation logic, so that open/close behavior, accessibility state, and the destination set stay correct as the code changes.

#### Acceptance Criteria

1. THE Portal vitest suite SHALL include coverage asserting that activating the Mobile_Menu toggle opens and closes the Mobile_Menu.
2. THE Portal vitest suite SHALL include coverage asserting that the Mobile_Menu toggle's `aria-expanded` value reflects the open and closed states.
3. THE Portal vitest suite SHALL include coverage asserting that the Mobile_Menu exposes links to all four destinations (Dashboard, Asset Studio, Backtest Studio, How It Works).

### Requirement 5: Clean guide tabs on mobile

**User Story:** As a phone user reading the guide, I want the six section tabs presented cleanly, so that I can switch sections without a clunky multi-row wrapped block.

#### Acceptance Criteria

1. WHILE the viewport is a Mobile viewport, THE Guide_Tablist SHALL present the six tabs in a single tidy arrangement (such as a horizontal scroll strip, a select, or a controlled wrap) rather than an uncontrolled multi-row wrap.
2. WHILE the viewport is a Mobile viewport, THE Guide_Tablist SHALL keep every tab reachable and selectable without horizontal clipping of the active tab.
3. THE Guide_Tablist SHALL preserve `role="tablist"` on the container and `role="tab"` with an `aria-selected` state on each tab.
4. WHEN a user moves between tabs using the left and right arrow keys WHILE focus is on a tab, THE Guide_Tablist SHALL move the active/focused tab accordingly.
5. WHILE the viewport is a Desktop viewport, THE Guide_Tablist SHALL retain its current appearance and tab-switching behavior.

### Requirement 6: Mobile spacing and tap targets for shared controls

**User Story:** As a phone user, I want interactive controls and stacked panels sized and spaced for touch, so that the dashboard filters and backtest studio are comfortable to use and nothing is clipped off-screen.

#### Acceptance Criteria

1. WHILE the viewport is a Mobile viewport, THE Data_Grid_Toolbar interactive controls (search input, recommendation select, deal-stage select, clear-filters button) SHALL render with a tap target of at least 44px in height.
2. THE asset data grid SHALL retain its horizontal-scroll container (`overflow-x-auto`) so that wide table content is scrollable rather than clipped on a Mobile viewport.
3. WHILE the viewport is a Mobile viewport, THE Backtest_Panes SHALL stack in a single column with vertical spacing between the ground-truth input pane and the results pane.
4. WHILE the viewport is a Desktop viewport, THE Backtest_Panes SHALL retain the current two-column split-pane layout.
5. WHILE the viewport is a Mobile viewport, THE AppShell main content container SHALL keep its content within the viewport width without introducing horizontal overflow.

### Requirement 7: Scope and regression boundaries (non-goals)

**User Story:** As a reviewer, I want the scope boundaries stated as requirements, so that no one "fixes" things that are intentionally out of scope.

#### Acceptance Criteria

1. THE Portal SHALL NOT add or modify any snackbar or toast in response to the browser-native "tab closed" notification observed in a screenshot, because that notification is produced by the browser from the presentation deck's document title and is not rendered by the Portal.
2. THE Portal SHALL NOT modify the presentation deck at `presentation/index.html`, because it is a separate artifact with its own mobile handling.
3. THE Portal SHALL limit all changes to the named components (`frontend/components/layout/top-nav.tsx`, `frontend/app/guide/page.tsx`, `frontend/components/dashboard/asset-data-grid.tsx`, `frontend/app/backtest/page.tsx`) and the associated navigation test file.
4. THE Portal SHALL NOT introduce new pages, new runtime dependencies, or color/brand changes as part of this effort.
5. WHILE the viewport is a Desktop viewport, THE Portal SHALL keep the layout and behavior of the named components visually unchanged from their current state.
