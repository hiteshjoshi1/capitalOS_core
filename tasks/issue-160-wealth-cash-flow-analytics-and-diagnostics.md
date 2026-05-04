# Issue 160: Wealth cash flow analytics and diagnostics

## Objective
- Add a dedicated `Cash Flow` destination that fits the current app shell and visual system introduced in Issue 159.
- Turn cash flow from a thin summary into a real diagnostic workspace that explains where money came from, where it went, what changed versus the prior period, and what is driving deterioration or improvement.
- Preserve the current two-level UX pattern:
- Objective 1a: `Cash Flow` becomes its own primary left-nav section
- Objective 1b: `Wealth` retains only a high-level Cash Flow summary card/box that links into the dedicated Cash Flow section
- Objective 1c: the Cash Flow section uses the same typography, surface treatment, spacing, top-bar controls, and card CTA language as the rest of the current shell
- Objective 1d: the section should use internal tabs so high-level diagnostics and granular audit views do not compete on one overloaded page

## Architecture Decisions
- Decision 1: `Cash Flow` should be its own top-level left-nav section, not a Wealth sub-tab.
- Decision 1a: `Wealth` should continue to show only a concise summary card/box for cash flow and link into the dedicated Cash Flow section.
- Decision 1b: legacy aliases may continue to resolve during transition, but the product model should clearly treat Cash Flow as its own section.
- Decision 2: `Cash Flow` should not be a single monolithic page; it should be a section with internal tabs so charts, answers, and transaction audit workflows are separated cleanly.
- Decision 2a: the first tab should be a genuinely high-level overview rather than a dump of every chart and table.
- Decision 2b: granular inflow, outflow, and mapping workflows should live in their own tabs.
- Decision 3: the page should answer user questions directly through explicit explanatory modules, not only raw tables.
- Decision 4: the page should support both narrative interpretation and structured quantitative breakdowns.
- Decision 5: the page should use the same shell conventions already established:
- Decision 5a: page header title and subtitle
- Decision 5b: top-bar controls such as `Month` and `Base`
- Decision 5c: editorial/glass card treatment
- Decision 5d: strong CTA and grouping patterns consistent with the new landing pages
- Decision 6: the initial implementation should remain deterministic and explainable; metrics and charts must derive from explicit backend aggregations rather than opaque LLM summaries.
- Decision 7: all charting and diagnostics must be backed by API payloads that are testable and verifiable via deterministic frontend tests and curl-compatible backend endpoints.
- Decision 8: the page should answer these specific user questions as first-class product requirements:
- Decision 8a: `Where did my money go this month?`
- Decision 8b: `What were my top spending categories this month?`
- Decision 8c: `How much of my income was saved vs spent?`
- Decision 8d: `What changed in my cash flow versus last month?`
- Decision 8e: `Which recurring expenses are driving most of my outflows?`
- Decision 8f: `What percentage of my inflows came from salary, dividends, and transfers?`
- Decision 8g: `Which categories explain most of the deterioration in free cash flow?`
- Decision 9: the page should distinguish between:
- Decision 9a: money in
- Decision 9b: money out
- Decision 9c: net cash flow
- Decision 9d: recurring vs non-recurring activity
- Decision 9e: fixed vs variable outflows
- Decision 10: charts and tables should be comparative, not merely static snapshots, wherever comparison adds meaning.
- Decision 10a: month-over-month comparison is required
- Decision 10b: current-period-only views are acceptable only where trend comparison is not meaningful
- Decision 11: `Cash Flow` should not duplicate `Credit Cards`, `Dividends`, or `Cash` pages mechanically; instead it should synthesize them into a money-movement lens.
- Decision 12: inflow and outflow groupings must remain metadata-driven and category-driven, not hardcoded for one institution or one account type.
- Decision 13: the initial page should be optimized for explanation and monitoring rather than transaction editing workflows.

## UX Structure
- UX 1: `Cash Flow` should appear as its own primary left-nav section.
- UX 2: the `Cash Flow` section should follow the current shell pattern used elsewhere:
- UX 2a: title/subtitle in the page header
- UX 2b: `Month` and `Base` in the shell top bar
- UX 2c: section-level tabs under the header, similar to how `Wealth` uses tabs
- UX 2d: each tab should contain only the information relevant to that slice, not the entire cash-flow universe
- UX 3: the `Cash Flow` section should expose these tabs:
- UX 3a: `Overview`
- UX 3b: `Direct Answers`
- UX 3c: `Income`
- UX 3d: `Expenses`
- UX 3e: `Map Transactions`
- UX 4: `Overview` should contain the high-level diagnostic view only:
- UX 4a: headline KPIs
- UX 4b: one high-value trend view
- UX 4c: compact inflow/outflow composition
- UX 4d: concise month-over-month change summary
- UX 4e: top drivers, but not every granular chart/table
- UX 4: the page should be legible in both dark and light theme and visually consistent with the current editorial/glass Wealth styling.
- UX 5: chart-heavy content should still degrade gracefully into readable table/card summaries if data is sparse.
- UX 6: `Map Transactions` should replace the current `Mapping` label everywhere in the product-facing UX.

## Functional Scope
### Overview tab
- `Total Inflows`
- `Total Outflows`
- `Net Cash Flow`
- `Savings Rate`
- `Burn Rate`
- `Free Cash Flow Change vs Prior Month`
- Net cash flow trend by month
- Compact inflow composition
- Compact outflow composition
- Concise summary of what changed vs the prior month
- High-level top drivers only

### Direct Answers tab
- A diagnostic card/section explicitly answering:
- Analysis 1: where money went this month
- Analysis 2: top spending categories
- Analysis 3: how much income was saved vs spent
- Analysis 4: what changed versus last month
- Analysis 5: which recurring expenses dominate outflows
- Analysis 6: what percentage of inflows came from salary, dividends, and transfers
- Analysis 7: which categories explain deterioration in free cash flow

### Income tab
- Pie/donut chart of income sources
- Breakdown of salary / business / dividends / interest / transfers
- One-off vs recurring inflow split
- Largest inflow drivers for the selected month
- Inflow composition percentages
- Income transactions table/list

### Expenses tab
- Pie/donut chart of top expense categories for the selected month
- Bar chart of monthly spend by category
- Recurring vs non-recurring outflow split
- Top merchants table/list
- Fixed vs variable expense split
- Largest deteriorating outflow categories versus prior month
- Expense transactions table/list

### Map Transactions tab
- Transaction/category mapping workflow
- Category override workflow
- Audit-oriented transaction evidence
- Product-facing label must be `Map Transactions`, not `Mapping`

### Cross-tab analytical support
- Savings rate trend
- Burn rate
- Waterfall / bridge chart showing:
- Waterfall 1: starting cash
- Waterfall 2: inflows
- Waterfall 3: outflows
- Waterfall 4: ending cash

## Data/API Expectations
- The backend may need new cash-flow-specific aggregation endpoints or optional expansions on existing endpoints.
- The API should expose deterministic aggregates for:
- API 1: inflow categories
- API 2: outflow categories
- API 3: recurring vs non-recurring classification
- API 4: fixed vs variable classification where inferable
- API 5: merchant-level outflow ranking
- API 6: month-over-month category deltas
- API 7: net cash-flow trend history
- API 8: savings-rate and burn-rate calculations
- API 9: waterfall inputs for starting cash / inflows / outflows / ending cash
- If current data models are insufficient, this issue may add optional fields or new endpoints, but must remain OpenAPI-compatible and deterministic.

## Acceptance Criteria
- [ ] `Cash Flow` appears as a dedicated primary left-nav section.
- [ ] `Wealth` retains only a concise Cash Flow summary card/box that links into the dedicated Cash Flow section.
- [ ] `Cash Flow` is implemented as a distinct section, not just a KPI row inside Wealth Overview.
- [ ] The section visually fits the current post-Issue-159 shell and theme system.
- [ ] The section includes top-bar `Month` and `Base` controls consistent with the current shell behavior.
- [ ] The section exposes these tabs: `Overview`, `Direct Answers`, `Income`, `Expenses`, `Map Transactions`.
- [ ] The label `Map Transactions` replaces the old product-facing `Mapping` label.
- [ ] The `Overview` tab remains high-level and does not cram all charts/tables onto one page.
- [ ] The `Direct Answers` tab answers `Where did my money go this month?` using visible structured diagnostics, not only raw transaction tables.
- [ ] The `Direct Answers` tab answers `What were my top spending categories this month?`
- [ ] The `Direct Answers` tab answers `How much of my income was saved vs spent?`
- [ ] The `Direct Answers` tab answers `What changed in my cash flow versus last month?`
- [ ] The `Direct Answers` tab answers `Which recurring expenses are driving most of my outflows?`
- [ ] The `Direct Answers` tab answers `What percentage of my inflows came from salary, dividends, and transfers?`
- [ ] The `Direct Answers` tab answers `Which categories explain most of the deterioration in free cash flow?`
- [ ] The `Expenses` tab includes:
- [ ] a pie/donut of top expense categories
- [ ] a bar chart of monthly spend by category
- [ ] recurring vs non-recurring split
- [ ] top merchants
- [ ] fixed vs variable expenses
- [ ] an expense transaction table/list
- [ ] The `Income` tab includes:
- [ ] a pie/donut of income sources
- [ ] salary / business / dividends / interest / transfers split
- [ ] one-off vs recurring inflows
- [ ] an income transaction table/list
- [ ] Cross-tab cash-flow diagnostics include:
- [ ] net cash flow trend by month
- [ ] savings rate
- [ ] burn rate
- [ ] a waterfall showing starting cash, inflows, outflows, and ending cash
- [ ] All calculations are backed by deterministic API data, not hardcoded frontend math on arbitrary UI samples.
- [ ] Any new backend contract remains OpenAPI-compatible.
- [ ] Tests cover backend calculations if changed, frontend rendering, and chart/diagnostic presence for representative datasets.
- [ ] The change is verifiable via Makefile commands and the page loads correctly in the browser.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `completed`
- Workflow Status: `ready_for_review`
- Provider/Model: `openai/gpt-5`
- Last Updated: `2026-05-03`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `pass` — `/Users/hiteshjoshi/.copilot/session-state/9526429a-3b57-4c19-9aeb-b97c7c2c6879/files/issue-160-logs/make_lint.log`
- `typecheck`: `pass` — `/Users/hiteshjoshi/.copilot/session-state/9526429a-3b57-4c19-9aeb-b97c7c2c6879/files/issue-160-logs/make_typecheck.log`
- `tests`: `pass` — `/Users/hiteshjoshi/.copilot/session-state/9526429a-3b57-4c19-9aeb-b97c7c2c6879/files/issue-160-logs/make_test-backend.log`, `/Users/hiteshjoshi/.copilot/session-state/9526429a-3b57-4c19-9aeb-b97c7c2c6879/files/issue-160-logs/make_contract-backend.log`, `/Users/hiteshjoshi/.copilot/session-state/9526429a-3b57-4c19-9aeb-b97c7c2c6879/files/issue-160-logs/make_test-frontend.log`, `/Users/hiteshjoshi/.copilot/session-state/9526429a-3b57-4c19-9aeb-b97c7c2c6879/files/issue-160-logs/make_contract-frontend.log`, `/Users/hiteshjoshi/.copilot/session-state/9526429a-3b57-4c19-9aeb-b97c7c2c6879/files/issue-160-logs/make_orch-test.log`
- `e2e`: `pass` — `/Users/hiteshjoshi/.copilot/session-state/9526429a-3b57-4c19-9aeb-b97c7c2c6879/files/issue-160-logs/make_e2e.log`
- `api-smoke`: `pass` — `/Users/hiteshjoshi/.copilot/session-state/9526429a-3b57-4c19-9aeb-b97c7c2c6879/files/issue-160-logs/make_api-smoke.log`
- `policy-checks`: `pass` — `/Users/hiteshjoshi/.copilot/session-state/9526429a-3b57-4c19-9aeb-b97c7c2c6879/files/issue-160-logs/make_api-rebuild.log`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `None.` — reason: `All repo changes stayed within the task scope; this task file was updated to record execution state and gate evidence.`

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `Re-run the independent pipeline and review the dedicated Cash Flow section in the browser.`
- Open questions:
  - `None.`
- If PR raised but intent partial:
  - unmet criteria: `None.`
  - follow-up issue: `None.`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `waiting_for_human`

## Workflow Snapshot
- latest_outcome: Implemented the Cash Flow workspace as a dedicated tabbed section with Overview, Direct Answers, Income, Expenses, and Map Transactions routes, kept Wealth on a concise summary card, preserved deterministic API-backed diagnostics, and updated tests plus the task journal.
- next_action: All deterministic gates passed. Review the changes in the working tree, then run `make task-ship TASK=<task_file> THREAD_ID=<thread_id>` to commit, push, and open a PR.
- pipeline_version: `v3`
- provider_model: `copilot/gpt-5.4`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: Cash Flow is a dedicated primary nav section with Overview, Direct Answers, Income, Expenses, and Map Transactions tabs.
- Acceptance criterion: Wealth keeps only a concise Cash Flow summary card linking to the dedicated workspace.
- Acceptance criterion: Overview stays high-level with KPIs, trends, compact composition, MoM summary, drivers, and waterfall diagnostics.
- Acceptance criterion: Direct Answers explicitly answers all required cash-flow diagnostic questions with visible structured modules.
- Acceptance criterion: Income and Expenses tabs separately cover their required charts, splits, rankings, and transaction evidence.
- Acceptance criterion: Map Transactions replaces the old Mapping label everywhere product-facing while preserving the legacy alias.
- Acceptance criterion: All displayed calculations remain backed by deterministic API payloads and existing backend aggregations.
- Acceptance criterion: Frontend tests, backend contracts, e2e, and the full Makefile verification suite passed.

## Prepare
Checked out `feature/issue-160-wealth-cash-flow-analytics-and-diagnostics` from `main` and ensured task file exists.

## Plan Summary
Reused the existing deterministic cash-flow backend payload, split the frontend into route-backed section tabs, renamed Mapping to Map Transactions everywhere user-facing, kept Wealth lightweight, then expanded frontend tests and ran the full make-based verification suite.

### Architecture Decisions
- Kept Cash Flow as its own primary app section and moved tab behavior into route-backed section tabs under /cash-flow.
- Preserved legacy aliases by redirecting /wealth/cash-flow to /cash-flow and /cash-flow/mapping to /cash-flow/map-transactions.
- Reused the existing deterministic /spending/cash-flow-detail backend contract instead of introducing opaque frontend-only calculations or a parallel API.
- Split the monolithic cash-flow page into purpose-specific views so Overview stays high-level while Direct Answers, Income, Expenses, and Map Transactions each own their slice.
- Left Wealth with a concise summary card that links into the dedicated cash-flow workspace rather than duplicating detailed diagnostics there.

### Acceptance Criteria
- Cash Flow is a dedicated primary nav section with Overview, Direct Answers, Income, Expenses, and Map Transactions tabs.
- Wealth keeps only a concise Cash Flow summary card linking to the dedicated workspace.
- Overview stays high-level with KPIs, trends, compact composition, MoM summary, drivers, and waterfall diagnostics.
- Direct Answers explicitly answers all required cash-flow diagnostic questions with visible structured modules.
- Income and Expenses tabs separately cover their required charts, splits, rankings, and transaction evidence.
- Map Transactions replaces the old Mapping label everywhere product-facing while preserving the legacy alias.
- All displayed calculations remain backed by deterministic API payloads and existing backend aggregations.
- Frontend tests, backend contracts, e2e, and the full Makefile verification suite passed.

### Planned Paths
- `web/src/lib`
- `web/src/main.tsx`
- `web/src/routes`
- `web/src/__tests__`
- `tasks/issue-160-wealth-cash-flow-analytics-and-diagnostics.md`

## Build Summary
Implemented the Cash Flow workspace as a dedicated tabbed section with Overview, Direct Answers, Income, Expenses, and Map Transactions routes, kept Wealth on a concise summary card, preserved deterministic API-backed diagnostics, and updated tests plus the task journal.

### Changed Files
- `tasks/issue-160-wealth-cash-flow-analytics-and-diagnostics.md`
- `web/src/__tests__/AppShell.test.tsx`
- `web/src/__tests__/CashFlowDetail.test.tsx`
- `web/src/__tests__/CashFlowMapping.test.tsx`
- `web/src/__tests__/contracts.test.tsx`
- `web/src/lib/navigation.ts`
- `web/src/main.tsx`
- `web/src/routes/CashFlowDetail.tsx`
- `web/src/routes/CashFlowMapping.tsx`
- `web/src/routes/WealthOverview.tsx`

## Latest Verification
- api-rebuild: PASS (exit 0)
- contract-backend: PASS (exit 0)
- test-backend: PASS (exit 0)
- api-smoke: PASS (exit 0)
- lint: PASS (exit 0)
- typecheck: PASS (exit 0)
- contract-frontend: PASS (exit 0)
- test-frontend: PASS (exit 0)
- e2e: PASS (exit 0)
- orch-test: PASS (exit 0)

## Extra Files Changed
- None

## Agent Run Summary
Implemented the Cash Flow workspace as a dedicated tabbed section with Overview, Direct Answers, Income, Expenses, and Map Transactions routes, kept Wealth on a concise summary card, preserved deterministic API-backed diagnostics, and updated tests plus the task journal.

- semantic_intent_achieved: `True`
- provider_model: `copilot/gpt-5.4`

### Semantic Checks
- `pass` Cash Flow appears as a dedicated primary left-nav section.: web/src/lib/navigation.ts defines Cash Flow as a primary section and keeps it separate from Wealth; AppShell/Sidebar tests cover the section links.
- `pass` Wealth retains only a concise Cash Flow summary card/box that links into the dedicated Cash Flow section.: web/src/routes/WealthOverview.tsx keeps a single summary card with income, expenses, savings rate, and an "Open cash flow workspace" link.
- `pass` Cash Flow is implemented as a distinct section with shell-consistent top-bar controls and tabs Overview, Direct Answers, Income, Expenses, and Map Transactions.: web/src/lib/navigation.ts and web/src/main.tsx define the five section tabs and routes; CashFlowDetail and CashFlowMapping both use shell header Month/Base controls.
- `pass` The label Map Transactions replaces the old product-facing Mapping label.: Navigation, route title, links, and tests now use "Map Transactions" while the old /cash-flow/mapping path redirects for compatibility.
- `pass` The Overview tab remains high-level and does not cram all charts/tables onto one page.: web/src/routes/CashFlowDetail.tsx overview path shows hero KPIs, trend/composition, concise change summaries, drivers, and waterfall only; CashFlowDetail.test asserts audit tables are absent on /cash-flow.
- `pass` The Direct Answers tab answers the seven required cash-flow questions with visible structured diagnostics.: web/src/routes/CashFlowDetail.tsx renders detail.analytics.answers on /cash-flow/direct-answers plus deterioration and methodology support; CashFlowDetail.test covers these answers.
- `pass` The Income tab includes a donut of income sources, source splits, recurring vs one-off inflows, and an income transaction table/list.: The /cash-flow/income view renders the income source donut, source split bars, recurring split, inflow drivers/category percentages, and the income transaction audit table.
- `pass` The Expenses tab includes a donut of expense categories, spend-by-category bars, recurring split, top merchants, fixed vs variable expenses, deterioration deltas, and an expense transaction table/list.: The /cash-flow/expenses view renders all required expense diagnostics and the expense transaction audit table; covered in CashFlowDetail.test.
- `pass` Cross-tab diagnostics include net cash flow trend, savings rate, burn rate, and a waterfall showing starting cash, inflows, outflows, and ending cash.: Overview exposes net cash flow trend, savings rate trend, KPI cards for savings/burn, and the cash waterfall backed by detail.analytics.waterfall.
- `pass` All calculations are backed by deterministic API data, contracts remain OpenAPI-compatible, and tests/Makefile verification cover the change.: The implementation keeps using the existing deterministic /spending/cash-flow-detail frontend contract without backend schema changes; contract-backend, contract-frontend, test-backend, test-frontend, e2e, api-smoke, and orch-test all passed.

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->
