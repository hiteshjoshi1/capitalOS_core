# Issue #371: phone tab rail keeps the active tab in view

## Problem
Found by #73's smoke tests: at 375px, `AppShell` scrolled the section tab rail to the active tab once per route change. The rail's and tabs' widths change afterwards (web fonts, a lazy page filling the top bar), so the active tab could end up off-screen. The smoke test lined the rail up itself to hide it.

## Change
- `web/src/lib/tabRail.ts`: `revealActiveTab` moves only the rail's `scrollLeft` (never the page, unlike `scrollIntoView`) just enough to show the active tab; `watchActiveTab` does it now, after `document.fonts.ready`, and whenever the rail or the active tab changes size (ResizeObserver).
- `AppShell` uses `watchActiveTab` per route / section.
- The smoke workaround in `web/tests/smoke/screens.spec.ts` is removed.

## Tests
- `web/src/__tests__/tabRail.test.ts` (5): right/left overflow, already visible, wider-than-rail tab, re-reveal on resize and stop after cleanup.
- `make e2e-smoke`: 45 passed, 3 runs in a row, no baseline changes.
