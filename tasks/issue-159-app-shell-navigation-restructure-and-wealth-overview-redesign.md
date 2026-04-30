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
