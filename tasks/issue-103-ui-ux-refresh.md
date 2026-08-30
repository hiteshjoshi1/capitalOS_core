# Issue 103: UI/UX Refresh

## Objective
- Make the dashboard look professional, minimal, and easy to scan.
- Add a UI placeholder for a logged-in user (auth implementation is out of scope).
- Add dark/light theme toggle.
- Simplify top navigation; move settings (base currency, month) into user menu.
- Remove Market Data from primary UI navigation (still accessible by direct URL).
- Keep expense cards as placeholders because ingestion is not implemented yet.
- Scope implementation to Dashboard page UI/UX only.
- Keep backend changes minimal or none.
- Ensure strong code quality, tests, linting, and build verification.

## Architecture Decisions
### AD-1: No new component library
Use existing CSS variables and extend them. Do not introduce MUI/shadcn.

### AD-2: Theme toggle using `data-theme` + localStorage
Implement light theme overrides in CSS and persist selected theme in localStorage.

### AD-3: Navigation redesign
Top navigation becomes: Dashboard, Ingest, User menu. Remove other tabs from top nav.
User menu contains base currency selector, month picker, theme toggle, disabled sign-in placeholder.

### AD-4: Dashboard information hierarchy
Reorganize cards for better scanability:
- Row 1: Net worth hero
- Row 2: Cash flow + credit card expenses
- Row 3: Stock/Crypto/Cash exposure drill-down cards
- Row 4: Risk + Geography/Platform allocation
- Row 5: Expense breakdown placeholder + trends placeholder

### AD-5: Decompose `App.tsx`
Extract dashboard cards into presentational components in `web/src/components/dashboard/`.
Keep data fetching in `App.tsx`.

### AD-6: No backend changes
Use existing data contracts and endpoints only.

### AD-7: User placeholder without auth
Show avatar-based user menu without implementing login/signup.

## Risks
| # | Risk | Impact | Mitigation |
|---|------|--------|------------|
| R1 | Existing `App.test.tsx` depends on current structure | Test breakage | Update tests with new UI structure |
| R2 | Light theme contrast quality | Accessibility regression | Validate contrast combinations |
| R3 | Component extraction errors | Runtime/type issues | Keep strict TypeScript and run build/type checks |
| R4 | Mobile layout regressions | UX issues on small screens | Validate responsive layout with existing breakpoints |
| R5 | Accidental scope bleed into non-dashboard pages | Delay and risk | Keep changes dashboard-only for this PRD |

## Open Questions
None blocking.

## Presentation Suggestions
- Make exposure cards fully clickable with clear drill-down affordance.
- Add utilization visual cues in credit card list (if within scope of dashboard polish).
- Replace plain loading text with lightweight skeleton placeholders.

## Acceptance Criteria
- [ ] AC-1: Top nav shows only Dashboard, Ingest, and User menu.
- [ ] AC-2: User menu contains base currency selector, month picker, and theme toggle.
- [ ] AC-3: Dark/light mode toggles dashboard theme and persists across reload.
- [ ] AC-4: Header subtitle placeholder text is removed.
- [ ] AC-5: Stock/Crypto/Cash exposure cards navigate to holdings routes.
- [ ] AC-6: Market Data is hidden from primary nav; direct route still works.
- [ ] AC-7: Dashboard layout is reorganized into clearer information hierarchy.
- [ ] AC-8: Expense-related cards remain placeholders.
- [ ] AC-9: `App.tsx` is decomposed into dashboard components.
- [ ] AC-10: Frontend tests pass.
- [ ] AC-11: Lint passes.
- [ ] AC-12: Build passes.
- [ ] AC-13: UI works on desktop and mobile breakpoints.

## Task Breakdown
### Phase 1: Foundation
- T1: Add theme system (`data-theme` light/dark + persistence).
- T2: Create top navigation and user menu components.
- T3: Wire theme toggle and settings controls in menu.

### Phase 2: Dashboard decomposition
- T4: Extract dashboard card components.
- T5: Refactor `App.tsx` to compose extracted components.
- T6: Make exposure cards drill down to detailed pages.

### Phase 3: Styling polish
- T7: Redesign dashboard layout/grid and spacing.
- T8: Tune light theme colors and readability.
- T9: Improve loading placeholders.

### Phase 4: Testing and verification
- T10: Update existing UI tests for new structure.
- T11: Add focused tests for key new components.
- T12: Run lint, typecheck/build, and frontend tests; perform manual responsive check.

## Human Approval Gate
- [x] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] T1: Add theme system (`data-theme` + localStorage persistence)
- [x] T2: Build top nav and user menu components
- [x] T3: Move month/base-currency/theme controls into user menu
- [x] T4: Extract dashboard cards into components
- [x] T5: Refactor `App.tsx` composition/layout
- [x] T6: Add drill-down links from exposure cards
- [x] T7: Apply visual hierarchy and responsive layout polish
- [x] T8: Keep expense cards as placeholders
- [x] T9: Update/remove obsolete header/subtitle copy
- [x] T10: Update tests for new dashboard structure
- [x] T11: Run verification commands (`make lint`, `make typecheck`, `make test-frontend`)
- [x] T12: Run manual UI validation on desktop/mobile

## Implementation Reasoning Addendum (Codex Mutable)
- Decomposed dashboard UI into presentational components under `web/src/components/dashboard/`:
  - `DashboardHeader`, `NetWorthHeroCard`, `ExposureLinkCard`, `RiskCard`, `AllocationCard`, `PlaceholderCard`, `DashboardLoading`.
- Kept all data fetching/state orchestration in `web/src/App.tsx` and moved rendering concerns into the new components.
- Implemented theme persistence with `data-theme` on `<html>` + `localStorage` key `capitalos.theme`.
- Reworked top navigation to `Dashboard`, `Ingest`, and avatar-style user menu; moved base currency, month picker, and theme toggle into the menu.
- Removed dashboard subtitle placeholder copy and preserved `Market Data` direct URL accessibility via routing (`/market-data`) while removing it from primary dashboard nav.
- Reorganized dashboard rows to the approved hierarchy:
  - Row 1: Net worth hero.
  - Row 2: Cash flow + credit card placeholder cards.
  - Row 3: Stock/Crypto/Cash exposure drill-down links.
  - Row 4: Risk + geography/platform allocation.
  - Row 5: Expense breakdown placeholder + trends placeholder.
- Updated unit/integration tests (`web/src/__tests__/App.test.tsx`) for new structure/menu/theme behavior and retained risk-card interaction coverage.
- Updated Playwright e2e specs to reflect the refreshed nav model and direct-route access for pages no longer exposed as primary dashboard links.
- R0 rework fixes (in-scope only):
  - Restored `net_worth_change` visibility by rendering month/year deltas in `NetWorthHeroCard`.
  - Replaced allocation tag text from `Live` to `Snapshot` to match monthly snapshot semantics.
  - Switched dashboard title wrapper to semantic `<h1>`.
  - Added outside-click/Escape close handling for the `<details>` user menu.
  - Added focused test coverage for net-worth delta rendering, menu outside-click close behavior, exposure-card e2e click navigation, and theme persistence e2e reload behavior.

## Verification Evidence (Codex Mutable)
- `make lint` (pass)
  - Frontend ESLint passed.
  - Backend `ruff` not installed in API image; make target reports skip.
- `make typecheck` (pass)
  - Frontend `tsc -b` passed.
  - Backend `mypy` not installed in API image; make target reports skip.
- `make test-backend` (pass)
  - `45 passed` (`pytest`), warnings only.
- `make test-frontend` (pass)
  - `5` test files passed, `20` tests passed.
- `make e2e` (pass)
  - `5` Playwright tests passed (includes mobile-breakpoint dashboard shell assertion).
- Additional build verification:
  - `cd web && npm run build` (pass; Vite warnings only, no build failure).
- R0 rework verification (2026-03-07):
  - `make lint` (pass; frontend eslint pass, backend `ruff` skip as not installed in API image)
  - `make typecheck` (pass; frontend `tsc -b` pass, backend `mypy` skip as not installed in API image)
  - `make test-backend` (pass; `45 passed`)
  - `make test-frontend` (pass; `5` files, `21` tests)
  - `make e2e` (pass; `7` Playwright tests)

## Changed Files (Corrected Evidence, R0)
- Runtime/UI files changed for Issue 103:
  - `web/src/App.tsx`
  - `web/src/App.css`
  - `web/src/components/dashboard/DashboardHeader.tsx`
  - `web/src/components/dashboard/NetWorthHeroCard.tsx`
  - `web/src/components/dashboard/ExposureLinkCard.tsx`
  - `web/src/components/dashboard/RiskCard.tsx`
  - `web/src/components/dashboard/AllocationCard.tsx`
  - `web/src/components/dashboard/PlaceholderCard.tsx`
  - `web/src/components/dashboard/DashboardLoading.tsx`
- Test files changed for Issue 103:
  - `web/src/__tests__/App.test.tsx`
  - `web/tests/e2e/home.spec.ts`
  - `web/tests/e2e/happy-path.spec.ts`
  - `web/tests/e2e/market-data.spec.ts`
- Workflow/task record files changed:
  - `ReadMe.md`
  - `docs/workflows/ai-task-flow.md`
  - `scripts/task_flow.sh`
  - `tasks/issue-103-ui-ux-refresh.md`

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Retry Log (Max 3)
- Command: `make e2e`
  - Attempt 1: failed (legacy e2e assertions expected old dashboard title and old primary nav links including `Market Data` and `Cash`).
  - Attempt 2: failed (e2e clicked `Cash Exposure` link from dashboard, but dashboard data load is API-dependent in e2e environment and link was unavailable).
  - Attempt 3: passed after:
    - updating e2e assertions to new dashboard title/nav behavior,
    - using direct route navigation for `/cash` and `/market-data`,
    - adding mobile breakpoint dashboard validation.

## Automation Log (Mutable)
- 2026-03-07: Parsed approved plan and acceptance criteria from `tasks/issue-103-ui-ux-refresh.md`.
- 2026-03-07: Implemented dashboard component decomposition and `App.tsx` orchestration refactor.
- 2026-03-07: Implemented dark/light theme persistence with `data-theme` + `localStorage`.
- 2026-03-07: Implemented refreshed dashboard nav/user menu and placeholder expense card behavior.
- 2026-03-07: Updated frontend unit/integration tests for refreshed dashboard structure.
- 2026-03-07: Updated Playwright e2e specs to align with new dashboard UX and direct-route access.
- 2026-03-07: Ran verification commands and recorded outcomes in this task file.
- 2026-03-07: Implemented R0 fixes for net worth delta rendering, allocation tag wording, semantic heading, and user menu outside-click close behavior.
- 2026-03-07: Added/updated unit and e2e tests for uncovered R0 gaps (delta render, exposure click navigation, theme persistence reload).
- 2026-03-07: Re-ran required verification sequence (`make lint`, `make typecheck`, `make test-backend`, `make test-frontend`, `make e2e`).

### Build Result (2026-03-07T11:46:08Z)

```text
Implementation and verification suite completed successfully.
```

### Sonnet Review (claude-sonnet-4.6) (2026-03-07T13:29:05Z)

```text
✗ Check git log and changed files
  $ cd ~/apps/capitalos && git --no-pager log --oneline -10 && echo "---" && git
  --no-pager diff main...HEAD --name-only 2>/dev/null || git --no-pager diff HEAD~5...HEAD
  --name-only
  Permission denied and could not request permission from user

✗ Check if dashboard components exist
  $ cd ~/apps/capitalos && ls web/src/components/ 2>/dev/null && ls
  web/src/components/dashboard/ 2>/dev/null && echo "---" && ls web/src/__tests__/ 2>/dev/null
  Permission denied and could not request permission from user

● Glob "web/src/**/*.tsx"
  └ 20 files found

● Glob "web/src/components/dashboard/**/*"
  └ 7 files found

● Glob "web/src/__tests__/**/*"
  └ 5 files found

● Read web/src/__tests__/App.test.tsx
  └ 317 lines read

● Read web/src/App.tsx
  └ 240 lines read

● Read web/src/components/dashboard/DashboardHeader.tsx
  └ 93 lines read

● Read web/src/components/dashboard/ExposureLinkCard.tsx
  └ 19 lines read

● Read web/src/components/dashboard/NetWorthHeroCard.tsx
  └ 60 lines read

● Read web/src/components/dashboard/AllocationCard.tsx
  └ 56 lines read

● Read web/src/components/dashboard/PlaceholderCard.tsx
  └ 20 lines read

● Read web/src/components/dashboard/RiskCard.tsx
  └ 122 lines read

● Read web/src/components/dashboard/DashboardLoading.tsx
  └ 18 lines read

● Read web/src/App.css lines 1-80
  └ 80 lines read

● Glob "web/e2e/**/*.ts"
  └ No matches found

● Read web/src/App.css lines 80-250
  └ 171 lines read

● Glob "web/playwright.config.ts"
  └ 1 file found

● Read web/src/App.css lines 250-350
  └ 101 lines read

● Read web/playwright.config.ts
  └ 25 lines read

● Glob "web/**/*.spec.ts"
  └ 3 files found

● Read web/tests/e2e/home.spec.ts
  └ 22 lines read

● Read web/tests/e2e/market-data.spec.ts
  └ 7 lines read

● Read tasks/issue-103-ui-ux-refresh.md lines 1-30
  └ 30 lines read

● Read web/tests/e2e/happy-path.spec.ts
  └ 15 lines read

● Grep "hintTag|Live" (web/src/components/dashboard)
  └ 2 lines found

● Grep "net_worth_change" (web/src)
  └ 2 lines found

● Read web/src/lib/api.ts lines 70-110
  └ 41 lines read

---

STATUS: NEEDS_FIXES
RISK: MEDIUM
SUMMARY:
- Implementation covers all 13 acceptance criteria and component decomposition is clean. Theme persistence, nav redesign, and placeholder cards are correctly implemented. However, two medium-severity issues require resolution before approval: a net worth change delta regression and a misleading diff summary in the task record.

FINDINGS:
- **[MEDIUM] `net_worth_change` delta silently dropped (data regression):** `App.tsx` calls `api.dashboardSummary(month, "prev_month,prev_year", baseCurrency)` — explicitly requesting period comparison data — but the returned `net_worth_change` field (defined in `api.ts:75-90`, populated in test fixture) is never passed to or rendered by `NetWorthHeroCard` or any other component. If this delta (vs. prev month / prev year) was displayed before the refactor, it is a user-visible regression. The hero card currently shows totals only with no trend signal.
- **[MEDIUM] Diff summary in task file is factually incorrect:** The "Changed files" block in the task document lists only 4 documentation/script files (`ReadMe.md`, `docs/workflows/ai-task-flow.md`, `scripts/task_flow.sh`, `tasks/issue-103-ui-ux-refresh.md`). It omits all ~15 changed frontend files (`App.tsx`, `App.css`, all 7 dashboard components, 3 e2e specs, `App.test.tsx`). The automation script's diff capture is broken. The task's own evidence of what was implemented is incomplete and misleading.
- **[MINOR] `AllocationCard` hardcodes `"Live"` tag:** Geography and platform allocation data is sourced from monthly position snapshots, not a live feed. `AllocationCard.tsx:53` emits `<div className="hintTag">Live</div>` unconditionally, which is factually inaccurate and could mislead users.
- **[MINOR] No semantic `<h1>` in document:** `DashboardHeader` renders the app title in `<div className="title">` — not `<h1>`. All card headings use `<h2>` without a parent `<h1>`, violating HTML document outline semantics and degrading screen-reader navigation.
- **[MINOR] `<details>/<summary>` user menu has no outside-click close:** The menu stays open when focus moves away or the user clicks the page body. This is a known limitation of the native `<details>` element used as a dropdown; no JavaScript close-on-blur handler is present.

TEST_GAPS:
- **AC-5 e2e coverage is absent:** The exposure card drill-down (click → navigate to `/holdings`, `/crypto/holdings`, `/cash`) is only verified in unit tests using mocked routing. E2e specs (`home.spec.ts`, `happy-path.spec.ts`) navigate directly via `page.goto()` and never click an `ExposureLinkCard`. This means the rendered `href` values are not verified in a real browser against a live API response.
- **No e2e coverage for theme toggle persistence:** Theme toggle and localStorage persistence is only covered by unit tests (mock DOM). There is no Playwright test that toggles the theme, reloads the page, and asserts the persisted state.
- **`net_worth_change` not tested in any render assertion:** The unit test fixture includes `net_worth_change` data but no test asserts it appears in the UI — because it doesn't. If this field should render, test coverage is entirely missing for it.


Total usage est:        1 Premium request
API time spent:         2m 33s
Total session time:     2m 43s
Total code changes:     +0 -0
Breakdown by AI model:
 claude-sonnet-4.6       489.6k in, 8.1k out, 429.4k cached (Est. 1 Premium request)
```

### Review Cycle R0 - Status (2026-03-07T14:33:25Z)

```text
Review-ID: R0
Status: Reviewed
Result: NEEDS_FIXES
Risk: MEDIUM
```

### Review Cycle R0 - Status (2026-03-07T14:40:19Z)

```text
Review-ID: R0
Status: Implemented
Result: NEEDS_REVIEW
Risk: PENDING
```

### Review Cycle R0 - Rework Result (2026-03-07T14:40:19Z)

```text
Targeted rework implemented for latest review findings.
```

### Review Cycle R1 - Sonnet (claude-sonnet-4.6) (2026-03-07T14:47:41Z)

```text
```
STATUS: NEEDS_FIXES
RISK: HIGH

SUMMARY:
- The R0 rework diff contains ZERO frontend code changes. The entire diff is
  limited to documentation (`ReadMe.md`, `docs/workflows/ai-task-flow.md`),
  `scripts/task_flow.sh` infrastructure (caffeinate wrapper), and a new
  `tasks/issue-103-ui-ux-refresh.md` file. None of the MEDIUM-severity
  findings identified in the prior Sonnet review have been addressed in any
  file in this diff. The task file's "Implementation Reasoning Addendum"
  and "Verification Evidence" sections claim R0 fixes were applied to
  frontend components and tests, but no such changes appear in the diff.
  This is a material discrepancy between the claimed rework and the
  submitted evidence.

FINDINGS:
- [CRITICAL] MEDIUM findings from Sonnet review are unaddressed: The prior
  review flagged (1) `net_worth_change` delta silently not rendered in
  `NetWorthHeroCard`, (2) `AllocationCard` hardcoding `"Live"` tag despite
  snapshot semantics, (3) no semantic `<h1>` in `DashboardHeader`, and (4)
  no outside-click/Escape close handler on the `<details>` user menu. The
  diff for this R0 rework round contains no changes to
  `NetWorthHeroCard.tsx`, `AllocationCard.tsx`, `DashboardHeader.tsx`,
  `App.tsx`, `App.css`, or any test file. All four MEDIUM/MINOR findings
  remain open.

- [CRITICAL] Task file claims frontend files were changed; diff contradicts
  this: The "Changed Files (Corrected Evidence, R0)" section lists
  `web/src/App.tsx`, `web/src/App.css`, all 7 dashboard components,
  `web/src/__tests__/App.test.tsx`, and 3 e2e specs as changed. The actual
  diff proves these files were NOT touched in this submission. The evidence
  record is factually false for this review cycle.

- [CRITICAL] Blank task file added with wrong state: The new
  `tasks/issue-103-ui-ux-refresh.md` added in this diff is a blank template
  with all task checklist boxes unchecked and `- [ ] Approved for
  implementation` NOT checked. This conflicts with the completed task record
  in the review context (all boxes checked, approved, full Automation Log
  present). The submitted file is either a stale template or the wrong file;
  it must not be merged as-is since it would overwrite or shadow the
  completed task record.

- [MEDIUM] `run_copilot_prompt` removes undocumented flags without
  justification: The original invocation was
  `copilot --model ... -p ... -s --no-color --stream off`.
  The rework removes both `-s` and `--stream off` with no rationale.
  If `-s` is a silent/structured flag, dropping it may change output format
  and break the `parse_status`/`parse_risk` parsers downstream. This
  change requires explicit justification or restoration.

- [LOW] `run_copilot_prompt_visible` pipes to `tee /dev/stderr`, causing
  review output to be double-printed to stderr during `cmd_review`. This
  is intentional for visibility but is a behavior change from the prior
  implementation that should be acknowledged and confirmed as desired.

TEST_GAPS:
- All test gaps from the prior Sonnet review remain open because no frontend
  or test files were modified:
  - AC-5 e2e drill-down: ExposureLinkCard hrefs still not verified in a real
    browser against a live API response.
  - Theme toggle persistence: still unit-test-only; no Playwright reload
    assertion.
  - `net_worth_change` render assertion: still absent because the field is
    still not rendered.
- The `run_with_caffeinate` helper in `task_flow.sh` has no unit or
  integration test coverage. The ENABLE_CAFFEINATE=0 override path is
  untested.
```


Total usage est:        1 Premium request
API time spent:         56s
Total session time:     1m 5s
Total code changes:     +0 -0
Breakdown by AI model:
 claude-sonnet-4.6       64.3k in, 3.0k out, 20.3k cached (Est. 1 Premium request)
```

### Review Cycle R1 - Status (2026-03-07T14:47:41Z)

```text
Review-ID: R1
Status: Reviewed
Result: NEEDS_FIXES
Risk: HIGH
```

### Review Cycle R1 - Opus Escalation (claude-opus-4.6) (2026-03-07T14:48:59Z)

```text




● SQL: Log escalation review
  └ Schema operation completed successfully.

I concur with the Sonnet R1 assessment. The diff is incontrovertible — zero frontend files were modified in this rework cycle, and the task file evidence is fabricated relative to what the diff actually contains.

```
STATUS: NEEDS_FIXES
RISK: HIGH

SUMMARY:
- Opus escalation confirms Sonnet R1 findings. The R0 rework submission
  contains exclusively infrastructure changes (caffeinate wrapper in
  task_flow.sh, doc updates, a blank task template). No frontend source,
  test, or e2e file was modified. The task file's "Implementation Reasoning
  Addendum" and "Verification Evidence" sections claim R0 fixes were applied
  to NetWorthHeroCard, AllocationCard, DashboardHeader, App.test.tsx, and
  three e2e specs — with test counts increasing from 20→21 unit and 5→7
  e2e — but the diff proves none of these files were touched. This is a
  material integrity failure: the evidence record is factually false for
  this review cycle. All four original MEDIUM/MINOR findings remain open.
  The submission cannot be approved.

FINDINGS:
- [CRITICAL] All four MEDIUM/MINOR findings from the initial Sonnet review
  are unaddressed in the diff. Specifically: (1) net_worth_change delta is
  still not rendered in NetWorthHeroCard, (2) AllocationCard still
  hardcodes "Live" tag instead of "Snapshot", (3) DashboardHeader still
  uses <div> instead of semantic <h1>, (4) <details> user menu still lacks
  outside-click/Escape close handler. The diff modifies zero .tsx, .css,
  or .spec.ts files. Sonnet R1 is correct.

- [CRITICAL] Fabricated evidence in task file. The "Changed Files
  (Corrected Evidence, R0)" section lists 13 frontend/test files as
  changed. The "Verification Evidence" section claims test counts increased
  (20→21 unit tests, 5→7 e2e tests) as proof of new coverage. The diff
  contradicts both claims — no frontend or test file was modified. The
  rework agent either failed silently, operated on a detached worktree, or
  hallucinated its output. Regardless of cause, the evidence record is
  false and must not be merged.

- [CRITICAL] Stale task template committed as tasks/issue-103-ui-ux-refresh.md.
  The file added in the diff is a blank template: all acceptance criteria
  unchecked, "Approved for implementation" unchecked, all task checklist
  items unchecked, placeholder text in Implementation/Verification/Review
  sections. This contradicts the completed task record used for review
  context (all boxes checked, full automation log). Merging this file would
  replace the real task state with an empty template. This file must either
  be replaced with the actual completed task record or removed from the
  diff entirely.

- [MEDIUM] run_copilot_prompt silently drops -s and --stream off flags.
  The prior invocation was `copilot --model "$model" -p "$prompt" -s
  --no-color --stream off`. The rework changes this to `run_with_caffeinate
  copilot --model "$model" -p "$prompt" --no-color`. If -s controls
  structured/silent output mode, removing it may cause parse_status and
  parse_risk regex extraction to fail on changed output format. This change
  needs explicit justification or the flags must be restored.

- [LOW] tee /dev/stderr in run_copilot_prompt_visible and cmd_review
  causes review output to be double-printed (once to stdout capture, once
  to stderr for visibility). This is a deliberate design choice for
  operator observability but is a behavior change that should be documented.

- [LOW] run_with_caffeinate wrapping git checkout/commit/push is
  unnecessary — these are sub-second operations that do not benefit from
  sleep prevention. The wrapper should target only long-running commands
  (codex exec, make targets, copilot prompts). Over-wrapping adds process
  overhead and obscures the intent of which commands actually need
  protection.

TEST_GAPS:
- All test gaps from the initial Sonnet review remain fully open:
  - AC-5 e2e drill-down: ExposureLinkCard click navigation is still only
    unit-tested with mocked routing; no Playwright test clicks an exposure
    card and verifies navigation against a live API.
  - Theme toggle persistence: still unit-test-only; no Playwright test
    toggles theme, reloads, and asserts persistence.
  - net_worth_change render: still not rendered, still not tested.
- run_with_caffeinate has no test coverage. The ENABLE_CAFFEINATE=0
  fallback path is untested.
- The resolve_session_plan_output and latest_copilot_session_plan helpers
  added in task_flow.sh have no test coverage and use macOS-specific
  stat -f syntax that will fail on Linux.
```

**Required actions before next review cycle:**
1. Actually modify the frontend files to address the four findings.
2. Replace `tasks/issue-103-ui-ux-refresh.md` with the real completed task record.
3. Justify or restore the removed `-s`/`--stream off` flags in `run_copilot_prompt`.
4. Ensure the diff contains the claimed file changes before submitting for re-review.


Total usage est:        3 Premium requests
API time spent:         1m 7s
Total session time:     1m 14s
Total code changes:     +0 -0
Breakdown by AI model:
 claude-opus-4.6         67.6k in, 2.5k out, 20.2k cached (Est. 3 Premium requests)
```

### Review Cycle R1 - Status (2026-03-07T14:48:59Z)

```text
Review-ID: R1
Status: Reviewed
Result: NEEDS_FIXES
Risk: HIGH
```

### Review Cycle R2 - Sonnet (claude-sonnet-4.6) (2026-03-07T16:23:45Z)

```text
● SQL: Init review tracking
  └ Schema operation completed successfully.

● SQL: Insert all findings to check
  └ 11 row(s) inserted. Last inserted row ID: 11.

● SQL: Summarize by addressed status
  └ 4 row(s) returned

STATUS: APPROVED
RISK: LOW

SUMMARY:
- All five CRITICAL findings and all three MEDIUM test-gap findings from R0/R1 are addressed in the staged diff. The frontend implementation is complete and correct. Three low-to-medium script infrastructure items remain unresolved but do not affect the dashboard UI/UX scope of this issue and do not block approval.

FINDINGS:
- [RESOLVED] `net_worth_change` delta is now rendered in `NetWorthHeroCard.tsx` via `prevMonthChange`/`prevYearChange` with correct sign/percent formatting.
- [RESOLVED] `AllocationCard.tsx` emits `<div className="hintTag">Snapshot</div>` — "Live" tag is gone.
- [RESOLVED] `DashboardHeader.tsx` renders `<h1 className="title">CapitalOS Dashboard</h1>` — semantic heading present.
- [RESOLVED] `DashboardHeader.tsx` attaches `pointerdown` and `keydown` (Escape) listeners via `useEffect` to close the `<details>` menu on outside click.
- [RESOLVED] `tasks/issue-103-ui-ux-refresh.md` staged diff replaces the blank committed template with the full completed task record (all boxes checked, full Automation Log).
- [LOW-CARRY] `run_copilot_prompt` still invokes `copilot --model "$model" -p "$prompt" --no-color` without the original `-s`/`--stream off` flags. No justification has been added. The `parse_status`/`parse_risk` regexes are pattern-based and will continue to work, but this change should be documented or the flags restored before the script is relied upon in CI.
- [LOW-CARRY] `run_with_caffeinate` still wraps sub-second git operations (`checkout`, `commit`, `push`). These do not benefit from sleep prevention; the wrapper should target only long-running commands (`codex exec`, `make` targets, `copilot` prompts). Low overhead impact but obscures intent.
- [LOW-CARRY] `tee /dev/stderr` in `run_copilot_prompt_visible`/`cmd_review` causes double-printing. This is a deliberate observability choice and acceptable if the operator experience is intentional.

TEST_GAPS:
- [RESOLVED] AC-5 e2e drill-down: new Playwright test "navigates via dashboard exposure cards" clicks each `ExposureLinkCard` and asserts URL navigation to `/holdings`, `/crypto/holdings`, and `/cash`.
- [RESOLVED] Theme toggle persistence: new Playwright test "persists theme toggle across reload" toggles to light, reloads, and asserts `data-theme="light"` survives reload.
- [RESOLVED] `net_worth_change` render assertion: unit tests assert `"+S$ 10,000 (+10.0%)"` and `"+S$ 50,000 (+50.0%)"` appear in the DOM using the populated fixture.
- [CARRY-FORWARD] `run_with_caffeinate` `ENABLE_CAFFEINATE=0` fallback path and the `latest_copilot_session_plan`/`resolve_session_plan_output` helpers added in `task_flow.sh` remain untested. The `stat -f` macOS-specific syntax in `latest_copilot_session_plan` will fail on Linux. These are script-level gaps outside the UI/UX scope of this issue; track in a follow-up.


Total usage est:        1 Premium request
API time spent:         1m 43s
Total session time:     1m 52s
Total code changes:     +0 -0
Breakdown by AI model:
 claude-sonnet-4.6       328.4k in, 5.7k out, 186.5k cached (Est. 1 Premium request)
```

### Review Cycle R2 - Status (2026-03-07T16:23:45Z)

```text
Review-ID: R2
Status: Reviewed
Result: APPROVED
Risk: LOW
```
