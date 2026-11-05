# Issue 151: Errors and accessibility: error boundary, LoadError, keyboard drill-down

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/151

Based on #150's branch (PR #198), which is based on #148's branch (PR #195). The diff includes both until they merge.

## Objective
- One render exception must never blank the whole app. A failed panel must never look like a zero (#130 finding 7.5).
- The History drill-down works from the keyboard, with focus management. The aria basics are fixed: theme `aria-pressed`, chart roles and labels, announced loading, a skip link (7.7 and the #131 accessibility findings).

## Architecture Decisions
- `RouteErrorBoundary` wraps AppShell's `<Outlet>`, keyed by pathname, so navigating away clears the error. It shows a `LoadError` with "Try again". The sidebar and header stay usable.
- `LoadError` (`role="alert"`, title, message, optional Retry, compact variant) replaces the page-local error cards on 16 pages. Hook-backed pages retry through `reload()`.
- Wealth Overview panels whose own call fails (vs last month, since last update, allocation, cash flow, positions, today's movers) show a compact `LoadError` with a retry instead of `—`.
- The History chart and attribution strip are one tab stop each (`role="group"`, instructions in the label):
  - ←/→ move between months, Home/End jump to the ends, Enter or Space inspects, Escape lets go.
  - The focused month is announced in a polite live region.
  - The drill-down panel focuses its heading on open, closes on Escape, and returns focus to the opener.
- Charts are `role="img"` with a stable name and an `aria-describedby` that carries the data ("Cash by account: DBS 62.5%, OCBC 37.5%"). This is done via `lib/chartA11y.ts`. Names stay stable, so existing `getByLabelText` queries and the visible titles don't change.
- Loading cards are `role="status"`.
- Contrast token bumps from the #131 probe and axe:
  - light `--bad`/`--warn` `#b55d2d` → `#a3501f`;
  - light `--muted` `#66717a` → `#5d6770`;
  - dark `--muted` 68% → 72% L;
  - dark inline links lifted from the accent.
- No new dependency. axe-core was loaded from cdnjs into the QA browser only, for the audit; it is not added to the project.

## Acceptance Criteria
- [x] Axe/keyboard checks on the affected pages. Axe (wcag2a/aa/21aa) found 0 violations on 12 pages, light and dark, after the token bumps; before them there were 2 contrast violations. The keyboard drill-down is covered by unit tests and the browser check.

## How To Test
- `cd web && npx vitest run src/__tests__/LoadErrorAndBoundary.test.tsx src/__tests__/WealthHistoryChart.test.tsx src/__tests__/WealthAttributionStrip.test.tsx src/__tests__/WealthDrilldownPanel.test.tsx src/__tests__/AppShell.test.tsx src/__tests__/WealthOverview.test.tsx src/__tests__/chartA11y.test.ts`
- `make verify`

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `lint`: pass — `npx eslint .`
- `typecheck`: pass — `npx tsc -b --pretty false`
- `tests`: pass — `npx vitest run` (55 files, 394 tests); `make verify`
- `e2e`: browser QA only (axe + keyboard on the worktree stack, demo data)
- `api-smoke`: skip (no backend change)
