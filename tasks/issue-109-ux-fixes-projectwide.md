# Issue 109: Project-Wide UX Consistency — Theme, Layout & Typography Alignment

## Objective
- The dashboard was redesigned with light/dark theme support, a user menu, and refined typography. All other pages (9 routes) still use the older, simpler header/layout pattern.
- Bring every page to the same UX standard as the dashboard: consistent header with navigation + user menu (including theme toggle), uniform typography, and identical card/panel styling.
- Theme choice (dark/light) must apply globally and persist across page navigations (already works via `localStorage` + `data-theme` attribute on `<html>`).
- Prepare the preference-persistence layer so a future user/auth system can sync the stored theme to a backend profile.

## Architecture Decisions

- **Decision 1 — Shared `PageShell` layout component**: Extract the dashboard's header pattern (title block + nav pills + user menu with theme toggle) into a reusable `PageShell` component (`web/src/components/PageShell.tsx`). Every route will wrap its content with `<PageShell>`. This eliminates duplicated header JSX in each route file and guarantees the user menu (with theme toggle) appears on every page.

- **Decision 2 — Theme context via React Context**: Lift the `theme` / `setTheme` state out of `App.tsx` into a lightweight `ThemeContext` (`web/src/context/ThemeContext.tsx`). This allows any nested component (including `PageShell` and any future settings page) to read and toggle the theme without prop-drilling. The context provider wraps `<BrowserRouter>` in `main.tsx`.

- **Decision 3 — CSS-only; no new framework**: Keep the existing pure-CSS approach with CSS custom properties. No Tailwind or CSS-in-JS will be introduced. New styles go in `App.css` under clearly namespaced class names.

- **Decision 4 — Typography normalization**: Standardize all page titles to the dashboard style (`font-size: 26px; font-weight: 760; letter-spacing: 0.1px`). Subtitle, pill, card, table, and KPI typography stays as-is since it is already consistent across pages.

- **Decision 5 — Navigation consistency**: Define a single canonical nav link set rendered by `PageShell`. Each page passes its `activeRoute` to highlight the current link. The nav set is: Dashboard, Holdings, Cash, Credit Cards, Crypto, Ingest, Market Data.

- **Decision 6 — Future user-sync ready**: Keep `localStorage` as the persistence backend. The `ThemeContext` exposes a `persistTheme(theme)` function that currently writes to `localStorage`. When a user system exists, only this function needs to change to also POST to `PUT /api/users/me/preferences`.

## Risks

| # | Risk | Mitigation |
|---|------|------------|
| 1 | Breaking existing dashboard look/feel during refactor | Snapshot current dashboard in browser before and after; visual diff |
| 2 | Route-specific header elements (month selector, currency selector, refresh button) may not fit the shared shell cleanly | `PageShell` accepts a `headerActions` render prop for per-page controls |
| 3 | CSS specificity conflicts when consolidating styles | Keep existing class names; add new classes with higher specificity only where needed |
| 4 | Merge conflicts with concurrent work on other pages | Scope PR to only UX/styling files; no API changes |

## Open Questions

- **OQ-1**: Should the nav include the `/accounts/new` route as a top-level link, or keep it accessible only from the Ingest page? _Assumption: keep it off the top nav; it is a sub-action._
- **OQ-2**: Should the month and base-currency selectors be elevated into the `PageShell` header for pages that use them, or remain in-page? _Assumption: pass as `headerActions` prop so they render in the header area but are owned by each page._

## Acceptance Criteria

- [ ] Every route (`/`, `/accounts/new`, `/ingest`, `/crypto`, `/crypto/holdings`, `/holdings`, `/cash`, `/credit-cards`, `/market-data`) renders the same header structure: logo/title block, nav pills, user menu with theme toggle.
- [ ] Selecting "Light" or "Dark" theme on any page applies immediately to all pages and persists across browser refresh (localStorage).
- [ ] All page titles use the same font size (26px), weight (760), and letter-spacing (0.1px) as the dashboard.
- [ ] Cards, tables, pills, KPIs on all pages use only CSS custom-property colors (`var(--*)`) — zero hardcoded hex/rgb values in JSX.
- [ ] The user menu dropdown (with theme toggle, navigation links) is accessible from every page, not just the dashboard.
- [ ] Navigating between pages preserves the chosen theme without flicker.
- [ ] No regressions: the dashboard looks identical to its current state.
- [ ] `npm run build` (or `make web-rebuild`) passes with zero TypeScript errors.
- [ ] Mobile responsive layout (≤980px breakpoint) still works on all pages.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

### Phase 1 — Theme Context Extraction
- [ ] Create `web/src/context/ThemeContext.tsx` with `ThemeProvider`, `useTheme` hook
- [ ] Move theme state, `initialTheme()`, and localStorage logic from `App.tsx` into `ThemeContext`
- [ ] Wrap app root in `<ThemeProvider>` in `main.tsx`
- [ ] Update `App.tsx` to consume `useTheme()` instead of local state
- [ ] Verify: theme toggle on dashboard still works, localStorage persists

### Phase 2 — Shared PageShell Component
- [ ] Create `web/src/components/PageShell.tsx` accepting props: `title`, `subtitle?`, `headerActions?` (ReactNode), `activeRoute` (string)
- [ ] Implement header with `.dashboardHeader` class: title block (26px), nav pills, user menu with theme toggle
- [ ] Extract nav link set: Dashboard(`/`), Holdings(`/holdings`), Cash(`/cash`), Credit Cards(`/credit-cards`), Crypto(`/crypto`), Ingest(`/ingest`), Market Data(`/market-data`)
- [ ] Port user menu markup from `DashboardHeader.tsx` into `PageShell`

### Phase 3 — Migrate Each Route to PageShell
- [ ] `App.tsx` (Dashboard) — replace inline header with `<PageShell>`, keep `DashboardHeader` meta pills as `headerActions`
- [ ] `routes/AddAccount.tsx` — wrap with `<PageShell>`
- [ ] `routes/Ingest.tsx` — wrap with `<PageShell>`
- [ ] `routes/CryptoWallets.tsx` — wrap with `<PageShell>`
- [ ] `routes/CryptoHoldings.tsx` — wrap with `<PageShell>`
- [ ] `routes/StockHoldings.tsx` — wrap with `<PageShell>`
- [ ] `routes/CashOverview.tsx` — wrap with `<PageShell>`
- [ ] `routes/CreditCards.tsx` — wrap with `<PageShell>`
- [ ] `routes/MarketData.tsx` — wrap with `<PageShell>`

### Phase 4 — Typography & Spacing Normalization
- [ ] Update `.header .title` CSS to match dashboard title style (26px, fw 760, letter-spacing 0.1px)
- [ ] Ensure `.subtitle` font-size and color are consistent (13px, `var(--muted)`)
- [ ] Audit and remove any per-route CSS overrides that conflict with unified styles

### Phase 5 — CSS Cleanup
- [ ] Remove orphaned CSS classes no longer used after migration (old per-page header styles)
- [ ] Verify no hardcoded hex/rgb values in any route TSX files
- [ ] Verify `[data-theme="light"]` overrides cover any new or moved CSS rules

### Phase 6 — Verification
- [ ] `make web-rebuild` — zero TypeScript errors, zero CSS warnings
- [ ] Manual check: navigate all 9 routes in dark mode — consistent header, cards, typography
- [ ] Manual check: toggle to light mode — all 9 routes render correctly
- [ ] Manual check: refresh browser — theme persists
- [ ] Manual check: responsive layout at ≤980px on 3+ pages
- [ ] `make api-smoke` — ensure no backend regressions (frontend-only change, but verify)

## Implementation Reasoning Addendum (Codex Mutable)
_Codex appends execution reasoning entries here._

## Verification Evidence (Codex Mutable)
_Codex appends lint/typecheck/test evidence here._

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._

## Workflow Commands

```bash
make task-plan TASK=tasks/issue-109-ux-fixes-projectwide.md
make task-build TASK=tasks/issue-109-ux-fixes-projectwide.md
make task-review TASK=tasks/issue-109-ux-fixes-projectwide.md
make task-rework TASK=tasks/issue-109-ux-fixes-projectwide.md
make task-ship TASK=tasks/issue-109-ux-fixes-projectwide.md
```
