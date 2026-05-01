# Issue 159: App shell navigation restructure and Wealth Overview redesign

## Objective
- Restructure the main application shell to match the navigation model shown in `mock.html`: a primary vertical section nav on the left and section-specific tabs across the top of the content area.
- Remove the current `Dashboard` concept and make `Wealth` the primary landing area for portfolio overview.
- Redesign the Wealth Overview page to adopt the visual language of `mock.html` as closely as practical, including typography, color system, dark/light theming, and glass/editorial layout treatment.

## Architecture Decisions
- Decision 1: The top-level application navigation should become a generic vertical section nav with exactly these primary items:
- Decision 1a: `Wealth`
- Decision 1b: `Liabilities`
- Decision 1c: `Operations`
- Decision 1d: `Intelligence`
- Decision 2: The existing `Dashboard` entry should be removed from the primary navigation and its useful summary content should be re-homed into `Wealth > Overview`.
- Decision 3: The app shell should adopt the two-level navigation pattern from `mock.html`:
- Decision 3a: primary section nav in the left column
- Decision 3b: section-specific tabs in the top/right content header area
- Decision 4: The new shell structure must be generic and extensible; future sections and tabs should not require brittle layout rewrites.
- Decision 5: `Wealth` becomes the default post-login landing section.
- Decision 6: `Wealth` top tabs should include:
- Decision 6a: `Overview`
- Decision 6b: `Stocks`
- Decision 6c: `Dividends`
- Decision 6d: `Crypto`
- Decision 6e: `Cash`
- Decision 6f: `Risk`
- Decision 7: `Wealth > Overview` should include all current dashboard summary content except the action queue.
- Decision 8: `Wealth > Overview` must also explicitly show portfolio composition percentages for at least:
- Decision 8a: stocks/funds
- Decision 8b: crypto
- Decision 8c: cash
- Decision 9: `Wealth > Risk` should combine current risk content with geographic exposure in one tab.
- Decision 10: `Liabilities` should land on a liabilities overview screen with secondary tabs such as:
- Decision 10a: `Overview`
- Decision 10b: `Credit Cards`
- Decision 10c: `Loans`
- Decision 10d: additional liability classes as needed
- Decision 11: `Liabilities > Credit Cards` should reuse/load the current credit-card page or equivalent existing view rather than reimplementing liability detail logic.
- Decision 12: `Operations` should land on an Operations overview page with these top tabs:
- Decision 12a: `Overview`
- Decision 12b: `Ingest`
- Decision 12c: `Add Accounts`
- Decision 12d: `Add Platforms`
- Decision 12e: `Add Crypto Wallets`
- Decision 12f: `Refresh Market Data`
- Decision 12g: `Author Ingestion`
- Decision 13: `Intelligence` should land on an Intelligence overview page with these top tabs:
- Decision 13a: `Overview`
- Decision 13b: `AI Sage`
- Decision 13c: `Author Library`
- Decision 13d: `Companies`
- Decision 14: In this issue, the visual redesign requirement applies primarily to the app shell and `Wealth > Overview`; the other tabs/pages may remain functionally plumbed with lighter styling adjustments for now.
- Decision 15: The design system should move toward the look and feel in `mock.html`:
- Decision 15a: editorial serif + sans pairing similar to `Newsreader` and `Inter`
- Decision 15b: atmospheric dark palette and matching light theme variant
- Decision 15c: glass/translucent surfaces
- Decision 15d: refined spacing, borders, and card hierarchy
- Decision 15e: uppercase micro-labels and stronger typographic rhythm
- Decision 16: The implementation should support both dark and light themes and get as close as practical to the mock’s theme behavior without introducing a one-off styling stack.
- Decision 17: Existing page functionality should be preserved while being re-homed under the new navigation structure.

## Acceptance Criteria
- [ ] The primary left navigation contains `Wealth`, `Liabilities`, `Operations`, and `Intelligence`.
- [ ] `Dashboard` is removed from the primary navigation.
- [ ] The application uses a two-level navigation structure with left-side primary sections and top content tabs for the active section.
- [ ] `Wealth` is the primary landing section.
- [ ] `Wealth > Overview` contains the current useful dashboard summary content, excluding the action queue.
- [ ] `Wealth > Overview` shows net worth composition percentages for stocks/funds, crypto, and cash.
- [ ] `Wealth` exposes tabs for `Overview`, `Stocks`, `Dividends`, `Crypto`, `Cash`, and `Risk`.
- [ ] `Wealth > Risk` includes both risk content and geographic exposure.
- [ ] `Liabilities` lands on an overview page and exposes tabs for at least `Overview`, `Credit Cards`, and `Loans`.
- [ ] `Liabilities > Credit Cards` loads the current credit-card content or equivalent existing liability detail page.
- [ ] `Operations` lands on an overview page and exposes tabs for `Ingest`, `Add Accounts`, `Add Platforms`, `Add Crypto Wallets`, `Refresh Market Data`, and `Author Ingestion`.
- [ ] `Intelligence` lands on an overview page and exposes tabs for `Overview`, `AI Sage`, `Author Library`, and `Companies`.
- [ ] The app shell and Wealth Overview adopt the visual language of `mock.html` as closely as practical, including color palette, typography, and glass/editorial card treatment.
- [ ] Both dark and light themes are supported, with the dark theme closely matching the mock.
- [ ] The redesign does not break existing major page functionality while re-homing routes/views under the new shell.
- [ ] The issue remains primarily a structure-and-shell redesign issue; the detailed look-and-feel of non-Wealth pages may be refined later.
- [ ] Tests cover primary navigation, section tab routing/plumbing, Wealth Overview rendering, and theme-safe layout behavior.
- [ ] The change is verifiable via Makefile commands and the application loads correctly in the browser.

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] Implement scoped code changes
- [ ] Add/update tests
- [ ] Run deterministic safety gates
- [ ] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `not_started`
- Workflow Status: `running`
- Provider/Model: `openai/gpt-5`
- Last Updated: `2026-04-30`

## Deterministic Gate Results (Codex Mutable)
_Append command-level evidence here._
- `lint`: `<pass|fail|skip>` — `<notes/log path>`
- `typecheck`: `<pass|fail|skip>` — `<notes/log path>`
- `tests`: `<pass|fail|skip>` — `<notes/log path>`
- `e2e`: `<pass|fail|skip>` — `<notes/log path>`
- `api-smoke`: `<pass|fail|skip>` — `<notes/log path>`
- `policy-checks`: `<pass|fail>` — `<notes/log path>`

## Extra Files Changed (Codex Mutable)
_List all out-of-scope files with explicit rationale._
- `<path>` — reason: `<why this file was required>`

## Permanently Failed / Gave Up (Codex Mutable)
_Fill only if workflow stops without shipping._
- Stop reason: `<concrete reason>`
- Attempted mitigations:
  - `<mitigation 1>`
  - `<mitigation 2>`
- Suggested human action: `<next action>`

## Human Action Summary (Codex Mutable)
_Human-readable next steps._
- Next expected action: `<command or decision>`
- Open questions:
  - `Should the left navigation also retain secondary utility links like settings/profile in this issue, or should those be deferred?`
  - `Should Wealth remain the landing section for all users, or should the shell support a future configurable default landing page?`
  - `Should the first version re-use existing route paths behind the new shell, or normalize route structure more aggressively now?`
- If PR raised but intent partial:
  - unmet criteria: `<criterion ids>`
  - follow-up issue: `<issue link or TODO>`

## Automation Log (Mutable)
_Automation appends structured logs here._

<!-- MACHINE_RENDERED_START -->
## Execution Journal
**Current Stage**: `deterministic_gates`
**Workflow Status**: `running`

## Workflow Snapshot
- latest_outcome: Implemented a Wealth-first app shell with route-driven primary sections and top tabs, removed Dashboard from primary navigation, re-homed summary content into a redesigned Wealth Overview, added overview landings for Liabilities/Operations/Intelligence, combined risk plus geography in Wealth > Risk, and updated unit/e2e coverage. All required Makefile verification commands passed, including a rerun of make e2e after tightening selectors affected by duplicate overview link labels.
- next_action: Workflow execution is in progress.
- pipeline_version: `v3`
- provider_model: `copilot/gpt-5.4`
- retry_gate_pending: `no`

## Active Requirements
- Acceptance criterion: The primary left navigation contains Wealth, Liabilities, Operations, and Intelligence.
- Acceptance criterion: Dashboard is removed from the primary navigation.
- Acceptance criterion: The application uses a two-level navigation structure with left-side primary sections and top content tabs for the active section.
- Acceptance criterion: Wealth is the primary landing section.
- Acceptance criterion: Wealth > Overview contains the current useful dashboard summary content, excluding the action queue.
- Acceptance criterion: Wealth > Overview shows net worth composition percentages for stocks/funds, crypto, and cash.
- Acceptance criterion: Wealth exposes tabs for Overview, Stocks, Dividends, Crypto, Cash, and Risk.
- Acceptance criterion: Wealth > Risk includes both risk content and geographic exposure.
- Acceptance criterion: Liabilities lands on an overview page and exposes tabs for at least Overview, Credit Cards, and Loans.
- Acceptance criterion: Liabilities > Credit Cards loads the current credit-card content or equivalent existing liability detail page.
- Acceptance criterion: Operations lands on an overview page and exposes tabs for Ingest, Add Accounts, Add Platforms, Add Crypto Wallets, Refresh Market Data, and Author Ingestion.
- Acceptance criterion: Intelligence lands on an overview page and exposes tabs for Overview, AI Sage, Author Library, and Companies.
- Acceptance criterion: The app shell and Wealth Overview adopt the visual language of mock.html as closely as practical, including color palette, typography, and glass/editorial card treatment.
- Acceptance criterion: Both dark and light themes are supported, with the dark theme closely matching the mock.
- Acceptance criterion: The redesign does not break existing major page functionality while re-homing routes/views under the new shell.
- Acceptance criterion: The issue remains primarily a structure-and-shell redesign issue; the detailed look-and-feel of non-Wealth pages may be refined later.
- Acceptance criterion: Tests cover primary navigation, section tab routing/plumbing, Wealth Overview rendering, and theme-safe layout behavior.
- Acceptance criterion: The change is verifiable via Makefile commands and the application loads correctly in the browser.

## Prepare
Checked out `feature/issue-159-app-shell-navigation-restructure-and-wealth-overview-redesign` from `main` and ensured task file exists.

## Plan Summary
Derived and executed a route-driven shell plan: centralize section/tab metadata, preserve existing detailed routes behind the new shell, redirect the root route to Wealth, redesign Wealth Overview around the mock’s editorial/glass language, add lightweight overview pages for the other sections, then update unit/e2e tests and run the full Makefile verification suite.

### Architecture Decisions
- Used a shared navigation config in web/src/lib/navigation.ts so the left primary nav and top section tabs are generated from one source of truth.
- Kept existing detailed route paths such as /holdings, /credit-cards, /ingest, and /ai-sage and re-homed them under the new shell instead of doing a disruptive URL normalization in this issue.
- Made / redirect to /wealth so Wealth is the default landing section without preserving a separate Dashboard page.
- Moved risk concentration and geographic exposure into a dedicated Wealth > Risk route while redesigning Wealth > Overview around net worth, composition, holdings, cash flow, and liabilities summary content.

### Acceptance Criteria
- The primary left navigation contains Wealth, Liabilities, Operations, and Intelligence.
- Dashboard is removed from the primary navigation.
- The application uses a two-level navigation structure with left-side primary sections and top content tabs for the active section.
- Wealth is the primary landing section.
- Wealth > Overview contains the current useful dashboard summary content, excluding the action queue.
- Wealth > Overview shows net worth composition percentages for stocks/funds, crypto, and cash.
- Wealth exposes tabs for Overview, Stocks, Dividends, Crypto, Cash, and Risk.
- Wealth > Risk includes both risk content and geographic exposure.
- Liabilities lands on an overview page and exposes tabs for at least Overview, Credit Cards, and Loans.
- Liabilities > Credit Cards loads the current credit-card content or equivalent existing liability detail page.
- Operations lands on an overview page and exposes tabs for Ingest, Add Accounts, Add Platforms, Add Crypto Wallets, Refresh Market Data, and Author Ingestion.
- Intelligence lands on an overview page and exposes tabs for Overview, AI Sage, Author Library, and Companies.
- The app shell and Wealth Overview adopt the visual language of mock.html as closely as practical, including color palette, typography, and glass/editorial card treatment.
- Both dark and light themes are supported, with the dark theme closely matching the mock.
- The redesign does not break existing major page functionality while re-homing routes/views under the new shell.
- The issue remains primarily a structure-and-shell redesign issue; the detailed look-and-feel of non-Wealth pages may be refined later.
- Tests cover primary navigation, section tab routing/plumbing, Wealth Overview rendering, and theme-safe layout behavior.
- The change is verifiable via Makefile commands and the application loads correctly in the browser.

### Planned Paths
- `web/src`
- `web/src/components`
- `web/src/lib`
- `web/src/routes`
- `web/src/__tests__`
- `web/tests/e2e`

## Build Summary
Implemented a Wealth-first app shell with route-driven primary sections and top tabs, removed Dashboard from primary navigation, re-homed summary content into a redesigned Wealth Overview, added overview landings for Liabilities/Operations/Intelligence, combined risk plus geography in Wealth > Risk, and updated unit/e2e coverage. All required Makefile verification commands passed, including a rerun of make e2e after tightening selectors affected by duplicate overview link labels.

### Changed Files
- `tasks/issue-159-app-shell-navigation-restructure-and-wealth-overview-redesign.md`
- `web/src/App.css`
- `web/src/App.test.tsx`
- `web/src/App.tsx`
- `web/src/__tests__/App.test.tsx`
- `web/src/__tests__/AppShell.test.tsx`
- `web/src/__tests__/AuthScreens.test.tsx`
- `web/src/__tests__/MainEntry.test.tsx`
- `web/src/__tests__/Sidebar.test.tsx`
- `web/src/__tests__/contracts.test.tsx`
- `web/src/components/AppShell.tsx`
- `web/src/components/Sidebar.tsx`
- `web/src/index.css`
- `web/src/lib/navigation.ts`
- `web/src/main.tsx`
- `web/src/routes/AddAccount.tsx`
- `web/src/routes/IntelligenceOverview.tsx`
- `web/src/routes/LiabilitiesOverview.tsx`
- `web/src/routes/Login.tsx`
- `web/src/routes/OperationsOverview.tsx`
- `web/src/routes/Signup.tsx`
- `web/src/routes/WealthOverview.tsx`
- `web/src/routes/WealthRisk.tsx`
- `web/tests/e2e/happy-path.spec.ts`
- `web/tests/e2e/home.spec.ts`
- `web/tests/e2e/operations.spec.ts`

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
Implemented a Wealth-first app shell with route-driven primary sections and top tabs, removed Dashboard from primary navigation, re-homed summary content into a redesigned Wealth Overview, added overview landings for Liabilities/Operations/Intelligence, combined risk plus geography in Wealth > Risk, and updated unit/e2e coverage. All required Makefile verification commands passed, including a rerun of make e2e after tightening selectors affected by duplicate overview link labels.

- semantic_intent_achieved: `True`
- provider_model: `copilot/gpt-5.4`

### Semantic Checks
- `pass` The primary left navigation contains Wealth, Liabilities, Operations, and Intelligence.: Implemented in web/src/lib/navigation.ts and rendered by web/src/components/Sidebar.tsx; covered by web/src/__tests__/Sidebar.test.tsx and web/src/__tests__/contracts.test.tsx.
- `pass` Dashboard is removed from the primary navigation.: Sidebar now renders only the four section links plus utility links; tests assert Dashboard is absent in web/src/__tests__/Sidebar.test.tsx and web/src/__tests__/contracts.test.tsx.
- `pass` The application uses a two-level navigation structure with left-side primary sections and top content tabs for the active section.: Primary sections are rendered in web/src/components/Sidebar.tsx and active-section tabs in web/src/components/AppShell.tsx from shared config in web/src/lib/navigation.ts; covered by web/src/__tests__/AppShell.test.tsx.
- `pass` Wealth is the primary landing section.: web/src/App.tsx redirects / to /wealth, and auth redirects in web/src/routes/Login.tsx and web/src/routes/Signup.tsx also land on /wealth; covered by web/src/App.test.tsx and web/src/__tests__/App.test.tsx.
- `pass` Wealth > Overview contains the current useful dashboard summary content, excluding the action queue.: web/src/routes/WealthOverview.tsx renders the net worth hero, deltas, cash flow, liabilities, and holdings summary while omitting the old action queue; verified in web/src/__tests__/contracts.test.tsx.
- `pass` Wealth > Overview shows net worth composition percentages for stocks/funds, crypto, and cash.: web/src/routes/WealthOverview.tsx calculates and renders composition percentages for stocks/funds, crypto, and cash; verified in web/src/__tests__/contracts.test.tsx.
- `pass` Wealth exposes tabs for Overview, Stocks, Dividends, Crypto, Cash, and Risk.: Configured in web/src/lib/navigation.ts and rendered by web/src/components/AppShell.tsx; covered by web/src/__tests__/AppShell.test.tsx.
- `pass` Wealth > Risk includes both risk content and geographic exposure.: Implemented in web/src/routes/WealthRisk.tsx using risk and geography content together; covered by web/src/__tests__/contracts.test.tsx.
- `pass` Liabilities lands on an overview page and exposes tabs for at least Overview, Credit Cards, and Loans.: Overview route added in web/src/routes/LiabilitiesOverview.tsx, tabs configured in web/src/lib/navigation.ts, and route wiring updated in web/src/main.tsx.
- `pass` Liabilities > Credit Cards loads the current credit-card content or equivalent existing liability detail page.: Existing web/src/routes/CreditCards.tsx remains wired at /credit-cards and is linked from the Liabilities section/tab structure.
- `pass` Operations lands on an overview page and exposes tabs for Ingest, Add Accounts, Add Platforms, Add Crypto Wallets, Refresh Market Data, and Author Ingestion.: Overview route added in web/src/routes/OperationsOverview.tsx, tabs configured in web/src/lib/navigation.ts, route wiring updated in web/src/main.tsx, and Playwright coverage updated in web/tests/e2e/operations.spec.ts.
- `pass` Intelligence lands on an overview page and exposes tabs for Overview, AI Sage, Author Library, and Companies.: Overview route added in web/src/routes/IntelligenceOverview.tsx and tabs configured in web/src/lib/navigation.ts with routes wired in web/src/main.tsx.
- `pass` The app shell and Wealth Overview adopt the visual language of mock.html as closely as practical, including color palette, typography, and glass/editorial card treatment.: Editorial typography, palette changes, glass surfaces, shell chrome, and Wealth overview layout were implemented in web/src/App.css and web/src/index.css, with the new overview structure in web/src/routes/WealthOverview.tsx.
- `pass` Both dark and light themes are supported, with the dark theme closely matching the mock.: Theme tokens and color-scheme behavior were updated in web/src/App.css and web/src/index.css; theme switching remains covered in web/src/__tests__/Sidebar.test.tsx and browser persistence is covered in web/tests/e2e/home.spec.ts.
- `pass` The redesign does not break existing major page functionality while re-homing routes/views under the new shell.: Existing detail pages and routes were preserved and re-linked under the new shell in web/src/main.tsx; all required backend, frontend, e2e, and orchestration Makefile gates passed.
- `pass` The issue remains primarily a structure-and-shell redesign issue; the detailed look-and-feel of non-Wealth pages may be refined later.: Only Wealth Overview and the shell received the deeper editorial redesign, while Liabilities, Operations, and Intelligence overviews remain intentionally lighter landing pages.
- `pass` Tests cover primary navigation, section tab routing/plumbing, Wealth Overview rendering, and theme-safe layout behavior.: Coverage was added or updated in web/src/__tests__/Sidebar.test.tsx, web/src/__tests__/AppShell.test.tsx, web/src/__tests__/contracts.test.tsx, and Playwright specs including web/tests/e2e/home.spec.ts and web/tests/e2e/operations.spec.ts.
- `pass` The change is verifiable via Makefile commands and the application loads correctly in the browser.: All required Makefile gates passed: api-rebuild, contract-backend, test-backend, api-smoke, lint, typecheck, contract-frontend, test-frontend, e2e, and orch-test; logs are under /Users/hiteshjoshi/.copilot/session-state/e2c78900-532e-4f73-be0e-a028014a2148/files/issue-159-logs/.

### Risk Flags
- preexisting-task-file-dirty

## Human Gate Decisions

_No human gate decisions yet._

## Review Cycles

_No review cycles yet._

## Rework Cycles

_No rework cycles yet._
<!-- MACHINE_RENDERED_END -->
