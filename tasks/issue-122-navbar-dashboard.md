# Issue 122: Sidebar Navigation And Thin Dashboard

## Objective
- Introduce a durable left-sidebar app shell that scales to future sections without overloading the current homepage.
- Refactor the current dashboard into a thinner, faster landing page focused on net worth, monthly cash flow, exposure split, and action-oriented summaries.
- Do only the navigation shell and dashboard restructuring in this issue; leave deeper page-by-page rewiring for follow-up issues.

## Architecture Decisions
- Decision 1: Implement the new app shell with a persistent left sidebar and keep the existing routes working; do not redesign every downstream page in this issue.
- Decision 2: Treat `Dashboard` as a fast control-tower page, not the place for full geography/risk/platform/deep analysis.
- Decision 3: Introduce the information architecture now, even if some destinations are initially lightweight placeholders or route through existing pages.
- Decision 4: Keep detailed analytics under later section pages such as `Wealth Overview`, not on the default homepage.
- Decision 5: cash flow summary on Dashboard with click-through to the existing detailed cash-flow page


## Acceptance Criteria
- [ ] Add a left sidebar navigation shell that becomes the primary app navigation on desktop.
- [ ] The first/default nav item is `Dashboard`, and the dashboard loads by default.
- [ ] Sidebar information architecture is introduced as:
- [ ] `Dashboard`
- [ ] `Wealth` with `Overview`, `Stocks`, `Crypto`, `Cash`
- [ ] `Liabilities` with `Credit Cards`, `Loans`
- [ ] `Intelligence` with `Companies`, `Alerts`, `AI Guru`
- [ ] `Operations` with `Ingest`, `Market Data`
- [ ] `Settings`
- [ ] user/profile area at the bottom of the sidebar
- [ ] The new dashboard is intentionally thin and shows only high-level information:
- [ ] net worth
- [ ] cash / stocks / crypto / liabilities with percentages
- [ ] monthly cash flow summary
- [ ] actions queue placeholder / what changed style summaries
- [ ] Dashboard no longer repeats heavy detail sections that belong to deeper pages.
- [ ] Existing detailed analysis content is either moved off the dashboard or clearly deferred from the default landing experience.
- [ ] Dashboard initial load should be faster than the current `issue-121` state and should ideally have no extraneous or repeating calls for same data
- [ ] Existing routes remain navigable; do not break current pages while introducing the new shell.
- [ ] Frontend tests are updated for the new shell/navigation behavior and default dashboard rendering.
- [ ] Verification commands for frontend and any touched backend paths are recorded.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement app shell / sidebar navigation
- [ ] Refactor dashboard layout/content to the thin landing-page model
- [ ] Preserve or adapt existing routes without broad unrelated rewrites
- [ ] Add/update tests
- [ ] Run verification commands

## Implementation Prompt
Build the new app shell and dashboard in a scoped, reviewable way.

Requirements:
- Create a persistent left sidebar navigation for desktop.
- Keep the current visual/product language coherent, but it is acceptable to improve layout/style where needed to support the new shell.
- Dashboard must become a fast high-level overview page, not a deep analytics page.
- Dashboard should show:
  - net worth
  - cash / stocks / crypto / liabilities with percentages
  - monthly cash flow summary
  - action queue / alerts / what changed summaries
- Do not keep heavy repeated sections on Dashboard such as full geography/risk/platform-detail blocks if they belong to later pages.
- Introduce the following sidebar IA now:
  - Dashboard
  - Wealth: Overview, Stocks, Crypto, Cash
  - Liabilities: Credit Cards, Loans
  - Intelligence: Companies, Alerts, AI Guru
  - Operations: Ingest, Market Data
  - Settings
  - bottom user/profile area
- It is acceptable in this issue for some destinations to be lightweight placeholders or to route to existing pages, but the shell and navigation model must be real.
- Keep this issue scoped:
  - do not fully redesign every destination page
  - do not implement AI Guru backend logic
  - do not attempt the full information architecture rollout in one pass
- Preserve working behavior of existing pages while changing the navigation shell.
- Optimize for:
  - fast initial load
  - clear hierarchy
  - future scalability of features
  - minimal duplication on Dashboard

Suggested implementation approach:
- Introduce the app shell and sidebar first.
- Make Dashboard the default route/landing experience within the shell.
- Recompose Dashboard around a small set of high-value cards/sections.
- Route deeper analysis to section pages instead of keeping everything on the homepage.
- If needed, reuse existing pages behind the new nav until later issues refine them.

Design intent:
- `Dashboard` = current state + quick actions
- `Wealth Overview` = deeper portfolio analysis later
- `Operations` groups `Ingest` and `Market Data`


## Implementation Reasoning Addendum (Codex Mutable)
_Codex appends execution reasoning entries here._

## Verification Evidence (Codex Mutable)
_Codex appends lint/typecheck/test evidence here._

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Human Rework Input (Mutable)
_Before running `task-rework`, add/update:_
- `### Review Cycle R<n> - Human Input` with a `text` block containing:
  `HUMAN_QUESTIONS: ...`
  `UNRESOLVED_COMMENTS: ...`
  `RESPONSE_REQUIREMENTS: ...`

## Retry Log (Max 3)
_Failed command/rework retries are appended here._

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `human_approval_gate`
**Workflow Status**: `running`

## Prepare
Checked out `feature/issue-122-navbar-dashboard` from `main` and ensured task file exists.

## Plan Summary
Introduce a persistent left-sidebar app shell with the new information architecture, refactor the dashboard into a thin control-tower landing page (net worth, exposure split, cash-flow summary, action queue), and move heavy analytics sections off the default view. All existing routes remain functional inside the new shell.

### Architecture Decisions
- Create an AppShell layout component that renders a persistent left Sidebar alongside an <Outlet/> content area, replacing per-page PageShell header navigation
- Use React Router v6 nested routes: AppShell wraps all child routes via <Outlet/>, so sidebar stays mounted across navigations
- Sidebar component owns the full IA tree (Dashboard, Wealth>{Overview,Stocks,Crypto,Cash}, Liabilities>{Credit Cards,Loans}, Intelligence>{Companies,Alerts,AI Guru}, Operations>{Ingest,Market Data}, Settings) with collapsible section groups
- Dashboard becomes a thin page: keeps bootstrap-phase data (net worth hero, exposure links, cash-flow summary card, action-queue placeholder) and drops secondary-phase heavy panels (RiskCard, geography AllocationCard, platform AllocationCard)
- Heavy analytics panels (risk, geography, platform allocation) are deferred to a future Wealth Overview page—placeholder created now
- Existing PageShell is retained but simplified: it keeps the title/subtitle/headerActions pattern for inner-page headers but drops the top nav bar and user menu (those move to the sidebar)
- New IA destinations that don't have real pages yet (Loans, Companies, AI Guru, Settings, Wealth Overview) get lightweight placeholder route components
- Pure CSS approach maintained: sidebar styles added to App.css using existing CSS custom properties
- Map existing routes to new IA paths: /holdings→Wealth>Stocks, /crypto/holdings→Wealth>Crypto, /cash→Wealth>Cash, /credit-cards→Liabilities>Credit Cards, /ingest→Operations>Ingest, /market-data→Operations>Market Data, /alerts→Intelligence>Alerts
- User/profile area placed at bottom of sidebar with theme toggle and base-currency selector (moved from PageShell user menu)

### Acceptance Criteria
- Left sidebar renders on desktop with all IA sections: Dashboard, Wealth (Overview/Stocks/Crypto/Cash), Liabilities (Credit Cards/Loans), Intelligence (Companies/Alerts/AI Guru), Operations (Ingest/Market Data), Settings
- Dashboard is the default route and loads by default when app opens
- User/profile area renders at sidebar bottom with theme toggle
- Dashboard shows only: net worth hero, cash/stocks/crypto/liabilities with percentages, monthly cash-flow summary card with link to /cash-flow, action queue placeholder
- Dashboard does NOT render RiskCard, geography AllocationCard, or platform AllocationCard (those belong to deeper pages)
- Dashboard initial load makes fewer API calls than before (bootstrap + spending summary only; drops platformAllocation, full dashboardSummary, creditCardSummary, cryptoSummary from critical path)
- All existing routes (/holdings, /cash, /cash-flow, /credit-cards, /crypto, /crypto/holdings, /ingest, /market-data, /alerts, /accounts/new, /cash-flow/mapping) remain navigable and functional
- Placeholder pages exist for Wealth Overview, Loans, Companies, AI Guru, and Settings
- Sidebar highlights the active route/section correctly
- TypeScript compiles with no errors (tsc -b)
- Vitest tests pass for new AppShell/Sidebar and updated Dashboard
- ESLint passes (npm run lint)

### Planned Paths
- `web/src/components/Sidebar.tsx`
- `web/src/components/AppShell.tsx`
- `web/src/main.tsx`
- `web/src/App.tsx`
- `web/src/App.css`
- `web/src/components/PageShell.tsx`
- `web/src/routes/WealthOverview.tsx`
- `web/src/routes/Loans.tsx`
- `web/src/routes/Companies.tsx`
- `web/src/routes/AIGuru.tsx`
- `web/src/routes/Settings.tsx`
- `web/src/routes/Dashboard.tsx`
- `web/src/__tests__/App.test.tsx`
- `web/src/__tests__/Sidebar.test.tsx`
- `web/src/__tests__/AppShell.test.tsx`
- `web/src/App.test.tsx`
- `web/src/routes/`

## Human Gate Decisions

### Plan Approval
- decision: `approved`
- reviewer: `Hitesh`
- decided_at: `2026-03-26T01:06:09.173006+00:00`
- notes: I have added some new files which are out of scope, these are pipeline changes which had issues, also added caffeinate into the pipeline.

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->
