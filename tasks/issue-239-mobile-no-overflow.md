# Issue 239: Mobile: no page wider than a 375px phone

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/239

## Objective
- Every main route fits a 375px phone: no sideways scroll, header controls on screen.
- Overview: the hero card keeps its right edge and the Liabilities card shows on a phone.
- The bottom-nav tab for Cash Flow no longer reads "Cash" (Wealth → Cash is balances).

## Architecture Decisions
- D-64 (docs/decisions.md): on a phone (≤980px, the shell's existing breakpoint) the top bar
  holds only the brand and the account menu. A page's header actions (month pill, currency,
  CSV) render in a wrapping row under its title (`PageShell`), chosen by a `matchMedia` hook
  (`lib/useMediaQuery.ts`) shared through `ShellHeaderContext.actionsInPage`. The theme switch
  moves into the account menu; the account pill shows only its avatar. Bottom tab: "Flow".
- Fix shared layout, not pages (sprint-9 branches #240, #241, #243 edit Overview, Risk, Cash
  Flow): `.wealthOverviewLayout` (the page grid most pages use) gets one `minmax(0, 1fr)`
  column, the Liabilities grids the same; the Overview signal cards stack; trend-bar labels
  wrap on a phone; the closed freshness tooltip leaves the layout on a phone. No route `.tsx`
  is edited.
- The guard measures `max(html, body, #main-content).scrollWidth`: `html, body
  { overflow-x: hidden }` keeps `documentElement.scrollWidth` at 375 even when the page is
  604px wide, so that number alone can't fail.

## Acceptance Criteria
- [x] Header-actions row fits at 375px on every page (month pill, CSV, theme, account).
- [x] Overview hero right edge visible; Liabilities card rendered on mobile.
- [x] Bottom-nav "Cash" renamed ("Flow").
- [x] Automated check: every main route at 375px has no sideways scroll (Playwright e2e,
      `web/tests/e2e/mobile-no-overflow.spec.ts`, runs in CI's e2e step on recorded demo data).
- [x] 1440px unchanged (screenshot diff, light and dark, demo data).

## How To Test
- `cd web && npx playwright test mobile-no-overflow` → 22 passed.
- `cd web && npx vitest run src/__tests__/AppShell.test.tsx` → phone-width cases pass.
- On a worktree stack with demo data: every route at 375px, light and dark; open the account
  menu (Settings, Dark/Light mode, Log Out); 1440px looks as before.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `review`
- Workflow Status: `shipped`
- Provider/Model: `claude-code/claude-opus-5-5`
- Last Updated: `2026-11-06`

- Batch CI follow-up: on CI (Linux fonts) /crypto was 388px wide: the mobile `.coExposureGrid` used
  a bare `1fr` column, as wide as the longest wallet address in "Connected wallets". Now
  `minmax(0, 1fr)`, and `.listRowMeta` wraps long values (`overflow-wrap: anywhere`). Every route in
  the guard now fits at 375, 360 and 340px locally, which leaves room for wider CI fonts.

## Deterministic Gate Results (Codex Mutable)
- See the PR description for command output and counts.

## Extra Files Changed (Codex Mutable)
- `docs/decisions.md` — reason: D-64.

## Human Action Summary (Codex Mutable)
- Next expected action: test on the test instance at 375px and 1440px.
- Re-record the e2e fixture after an API shape change: `E2E_RECORD_FROM=http://localhost:<worktree web port> npx playwright test mobile-no-overflow` against a worktree stack with `make db-seed-demo`.

## Automation Log (Mutable)

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
