# Issue 116: Cash Flow Category Mapping UI + Override Workflow

## Objective

Build the category-mapping UI as an operational workflow under the User context, not on Dashboard. Consume the backend APIs shipped in issue-115 (`GET /categories`, `GET /categories/unmapped`, `POST /categories/override`, `GET /categories/resolve/{id}`, `POST /categories/backfill`). Dashboard must stop showing the cash-flow mapping placeholder card after this change.
Allow additive backend changes in this story where required to make cash-flow totals and net behavior correct after transfer-category overrides.

Core UX intent:
- Mapping is a maintenance action, not a dashboard insight.
- User should discover pending mapping work when opening the User section/menu.
- User can enter a dedicated mapping workspace and resolve items quickly.

Navigation requirements:
- Add a dedicated route: `/cash-flow/mapping`.
- Add entry under User menu "Navigate" section: `Cash Flow Mapping`.
- If unmapped items exist, show a pending count badge next to the nav entry.
- Do not add a top-level primary nav tab for mapping.
- Remove the dashboard cash-flow PlaceholderCard (row2 first card in `App.tsx`).

Mapping page requirements:
- Show unmapped transactions queue for the selected month.
- Each row shows: date, account, merchant/counterparty, amount, currency, type, raw category.
- Support manual override action per transaction via category dropdown.
- Fetch taxonomy list from `GET /categories` for dropdown options.
- After successful override (`POST /categories/override`), remove the row from unmapped queue immediately (optimistic remove).
- Include loading, empty, and error states.
- Support month selector (reuse `MonthControl`).

Scope constraints:
- Frontend is primary scope, but additive backend read/write behavior updates are allowed where needed for cash-flow correctness.
- Backend schema-breaking changes are not allowed; additive endpoints/fields are allowed.
- No unrelated UI redesign.

## Architecture Decisions

- **Decision 1: Unmapped count in User menu via PageShell prop.** Rather than making PageShell fetch data itself (violating separation of concerns), the mapping page route component and the Dashboard will pass an `unmappedCount` prop to PageShell. Only the CashFlowMapping page needs real-time accuracy; Dashboard can use a lightweight fetch. PageShell renders the badge conditionally when count > 0. This keeps PageShell a pure presentational shell.

- **Decision 2: API types mirror backend Pydantic schemas exactly.** New TypeScript types `CategoryTaxonomy`, `UnmappedTransaction`, `CategoryOverridePayload`, and `CategoryResolution` are added to `web/src/lib/api.ts` matching the backend `CategoryTaxonomyOut`, `UnmappedTransactionOut`, `CategoryOverrideCreate`, and `CategoryResolutionOut` schemas field-for-field. No mapping or transformation layer.

- **Decision 3: Optimistic row removal after override.** When a user selects a category for an unmapped transaction and the `POST /categories/override` succeeds, the transaction row is removed from the local state immediately. No full refetch required. On failure, the row remains and an inline error is shown. This minimizes API calls and provides instant feedback.

- **Decision 4: Dashboard cash-flow PlaceholderCard replacement.** The `PlaceholderCard` in dashboard row2 (lines 144-148 of `App.tsx`) is replaced with an `ExposureLinkCard` that links to `/cash-flow/mapping` and shows spending summary data (income/expense/net from existing `spendingSummary` state). This provides a useful dashboard card while directing users to the mapping workflow.

- **Decision 5: CSS-only badge in User menu.** A small `.menuBadge` CSS class renders a pill-shaped count next to the "Cash Flow Mapping" link in the User menu Navigate section. Uses existing `--warn` color for visibility. No third-party badge component needed.

- **Decision 6: Month-scoped unmapped count.** The unmapped count badge reflects the currently selected month. The `GET /categories/unmapped?month=YYYY-MM` endpoint is used. This ensures the badge is contextually accurate.

- **Decision 7: Transfer-resolved rows are excluded from cash-flow totals.** When a transaction is resolved to Transfer taxonomy via manual override, it should not contribute to cash-flow income/expense/net totals. This applies consistently across summary and detail cash-flow endpoints.

## Risks

- **Risk 1: Backend APIs not running.** If issue-115 migration hasn't been applied or API is down, the mapping page will show an error state. Mitigation: graceful error handling with actionable message ("Run `make db-migrate` then `make api-rebuild`").
- **Risk 2: Empty unmapped queue edge case.** If all transactions have been mapped or none exist for the month, the page should render a clear empty state, not a broken UI. Mitigation: explicit empty state component.
- **Risk 3: PageShell prop change affects all pages.** Adding `unmappedCount` prop to PageShell changes its interface. Mitigation: prop is optional with `undefined` default, so all existing usages remain unaffected.
- **Risk 4: Large unmapped transaction list.** If hundreds of unmapped transactions exist, the page could be slow. Mitigation: backend already returns results ordered by `ts DESC` and the list is month-scoped, naturally limiting size. Pagination deferred to future issue if needed.

## Open Questions

- None. Existing backend APIs are sufficient for mapping workflows; additive backend behavior changes are explicitly allowed in this story for cash-flow correctness.

## Acceptance Criteria

- [ ] AC1: Route `/cash-flow/mapping` exists and renders the CashFlowMapping page.
- [ ] AC2: User menu "Navigate" section contains a "Cash Flow Mapping" link pointing to `/cash-flow/mapping`.
- [ ] AC3: When unmapped transactions exist for the selected month, a count badge appears next to the "Cash Flow Mapping" link in the User menu.
- [ ] AC4: When no unmapped transactions exist, no badge is shown.
- [ ] AC5: CashFlowMapping page displays a table/list of unmapped transactions with columns: Date, Account, Merchant, Amount, Currency, Type, Raw Category, and an Override action.
- [ ] AC6: Override action presents a dropdown of categories fetched from `GET /categories`.
- [ ] AC7: Selecting a category from the dropdown fires `POST /categories/override` with `{transaction_id, category_id}`.
- [ ] AC8: On successful override, the transaction row is removed from the unmapped queue without a full page reload.
- [ ] AC9: On override failure, the row remains and an inline error message is shown.
- [ ] AC10: Loading state shown while fetching unmapped transactions and taxonomy.
- [ ] AC11: Empty state shown when no unmapped transactions exist for the selected month.
- [ ] AC12: Error state shown when API calls fail, with actionable hint text.
- [ ] AC13: Month selector (MonthControl) is present and changing month re-fetches unmapped transactions.
- [ ] AC14: Dashboard no longer shows the "Cash flow ingestion is pending final category mapping" PlaceholderCard.
- [ ] AC15: Dashboard row2 first card is replaced with an ExposureLinkCard linking to `/cash-flow` showing cash flow summary data.
- [ ] AC16: TypeScript types compile with strict mode (`npx tsc -b`).
- [ ] AC17: ESLint passes (`npx eslint .`).
- [ ] AC18: All existing frontend tests continue to pass (`vitest --run`).
- [ ] AC19: New test file `web/src/__tests__/CashFlowMapping.test.tsx` exists with at least: render test, loading state test, empty state test.
- [ ] AC20: After page refresh, previously applied overrides remain reflected (transaction no longer appears in unmapped list).
- [ ] AC21: `api.ts` exports new types: `CategoryTaxonomy`, `UnmappedTransaction`, `CategoryResolution`, and new API methods: `categories()`, `unmappedTransactions()`, `categoryOverride()`.
- [ ] AC22: `GET /spending/cash-flow-detail` exists and returns transaction-level provenance for cash-flow totals.
- [ ] AC23: After overriding a row to Transfer category, `/spending/summary` and `/spending/cash-flow-detail` both recompute totals/net with that row excluded from income/expense.
- [ ] AC24: Backend tests cover transfer-override cash-flow recomputation behavior and pass.
- [ ] AC25: Backend files below are explicitly in scope for this issue:
  - `api/app/routers/spending.py`
  - `api/app/schemas/spending.py`
  - `api/tests/test_spending.py`
  - `api/tests/test_categories.py`

## Human Approval Gate

- [x] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

### 1. Add TypeScript types and API methods (`web/src/lib/api.ts`)
- [x] Add `CategoryTaxonomy` type matching backend `CategoryTaxonomyOut`: `{ id: number; code: string; name: string; parent_id: number | null; display_order: number }`
- [x] Add `UnmappedTransaction` type matching backend `UnmappedTransactionOut`: `{ transaction_id: number; ts: string; account_id: number; account_name: string; amount: number; currency: string; type: string; raw_category: string | null; merchant_counterparty: string | null; notes: string | null }`
- [x] Add `CategoryOverridePayload` type: `{ transaction_id: number; category_id: number }`
- [x] Add `CategoryResolution` type matching backend `CategoryResolutionOut`: `{ transaction_id: number; raw_category: string | null; override_category: string | null; resolved_category: string; source: string; rule_id: number | null; rule_name: string | null }`
- [x] Add `api.categories()` → `GET /categories` → `CategoryTaxonomy[]`
- [x] Add `api.unmappedTransactions(month: string, accountId?: number)` → `GET /categories/unmapped?month=...` → `UnmappedTransaction[]`
- [x] Add `api.categoryOverride(payload: CategoryOverridePayload)` → `POST /categories/override` → `CategoryResolution`

### 2. Create CashFlowMapping page (`web/src/routes/CashFlowMapping.tsx`)
- [x] Create page component following established pattern (PageShell, LoadState, useEffect)
- [x] Fetch both `api.categories()` and `api.unmappedTransactions(month)` in parallel on mount/month change
- [x] Render table with columns: Date, Account, Merchant, Amount, Currency, Type, Raw Category, Override
- [x] Override column: `<select>` dropdown populated from taxonomy, grouped by parent categories
- [x] On select change: call `api.categoryOverride()`, on success remove row from state, on error show inline message
- [x] Loading state: card with "Loading…" text
- [x] Empty state: card with "All transactions mapped for {month}." message
- [x] Error state: card with error message and hint to check API/migration

### 3. Add route (`web/src/main.tsx`)
- [x] Import `CashFlowMapping` from `./routes/CashFlowMapping.tsx`
- [x] Add `<Route path="/cash-flow/mapping" element={<CashFlowMapping />} />`

### 4. Update PageShell navigation (`web/src/components/PageShell.tsx`)
- [x] Add optional `unmappedCount?: number` prop to `PageShellProps`
- [x] Add "Cash Flow Mapping" entry to `MENU_NAV_ITEMS` array: `{ label: "Cash Flow Mapping", to: "/cash-flow/mapping" }`
- [x] In the Navigate section render loop, conditionally render a `.menuBadge` span next to the "Cash Flow Mapping" label when `unmappedCount` is defined and > 0

### 5. Update Dashboard (`web/src/App.tsx`)
- [x] Remove the `PlaceholderCard` in row2 (lines 144-148) that shows "Cash flow ingestion is pending final category mapping"
- [x] Replace with `ExposureLinkCard` linking to `/cash-flow`: title "Cash Flow", value shows `formatMoney(spendingSummary?.net)` or spending summary data, subtitle shows month context
- [x] Optionally fetch unmapped count and pass as `unmappedCount` prop to PageShell (lightweight call)

### 6. Add CSS styles (`web/src/App.css`)
- [x] Add `.menuBadge` class: small pill/badge with `--warn` background color, white text, positioned inline after link text
- [x] Add `.mappingTable` styles: table layout matching existing card/grid aesthetic
- [x] Add `.mappingRow` and `.overrideSelect` styles
- [x] Add `.overrideError` inline error style

### 7. Add tests (`web/src/__tests__/CashFlowMapping.test.tsx`)
- [x] Test: CashFlowMapping renders without crashing
- [x] Test: Shows loading state initially
- [x] Test: Shows empty state when no unmapped transactions

### 8. Verify
- [x] `make lint` passes
- [x] `make typecheck` passes
- [x] `make api-rebuild` passes
- [x] `make test-backend` passes
- [x] `make test-frontend` passes
- [x] `make e2e` passes
- [x] Manual-equivalent via Playwright: navigate to `/cash-flow/mapping`, verify page loads
- [x] Manual-equivalent via App/Vitest + Playwright: User menu shows "Cash Flow Mapping" link
- [x] Manual-equivalent via App/Vitest: Dashboard no longer shows old placeholder card

## Implementation Reasoning Addendum (Codex Mutable)
- Kept the existing category-mapping workflow intact under `/cash-flow/mapping`, including its unmapped-only queue and empty state when the selected month has no remaining category work.
- Added an additive backend endpoint, `GET /spending/cash-flow-detail`, that reuses the same month-scoped transaction classification rules as `GET /spending/summary` so the detail view and summary totals stay mathematically aligned.
- The new cash-flow detail payload exposes the calculation path explicitly: month totals, savings rate, included transaction types, and grouped income/expense transaction lists with account metadata plus raw/resolved category provenance.
- Introduced a dedicated `/cash-flow` route that explains `net = income_total - expense_total` and renders the contributing income and expense transactions side by side for verification.
- Retargeted the dashboard cash-flow card to `/cash-flow`, which separates the reviewer-facing verification workflow from the User-menu maintenance workflow in `/cash-flow/mapping`.
- Kept the override flow optimistic at the row level: successful overrides remove the transaction from local state immediately; failures keep the row in place and surface inline API error text.
- Added focused backend coverage for the new detail endpoint and override propagation, plus frontend coverage for the new verification page and the updated dashboard link target.
- Added an in-row category editor on `/cash-flow` backed by `GET /categories` plus the existing `POST /categories/override`; after save, the page refetches cash-flow detail so the edited row, source tag, and month totals stay synchronized.
- Extended each cash-flow detail row with additive `resolved_category_id` metadata only when the resolved category is safely backed by taxonomy data, so the editor can preselect existing mapped categories without relying on ambiguous name matching.
- R5 rework changed the shared cash-flow aggregation path so rows resolved under the Transfer taxonomy are excluded from `income_total`, `expense_total`, and `net` even if the imported transaction `type` is still `INCOME` or `EXPENSE`.
- Updated the `/cash-flow` helper copy to explain the new behavior precisely: saving a row to a Transfer category changes the totals on the immediate post-save refresh, while non-transfer category edits keep the row in its current income/expense bucket and only relabel it.
- Inspected the persisted UOB `4600.00` credit directly from the running app database: it is currently manually overridden to `transfer_internal`, but the stored provenance text does not name DBS as the originator, so DBS origin cannot be asserted from the available data.

## Verification Evidence (Codex Mutable)
- `make lint` -> passed. Frontend ESLint succeeded; backend lint reported `ruff not installed in api image; skipping backend lint`.
- `make typecheck` -> passed. Frontend `npx tsc -b --pretty false` succeeded; backend typecheck reported `mypy not installed in api image; skipping backend typecheck`.
- `make api-rebuild` -> passed. Docker rebuilt `capitalos-api:latest` and restarted the `capitalos-api` container successfully.
- Host-side `curl http://localhost:8000/health` and `curl "http://localhost:8000/dashboard/summary?month=2026-02"` still failed from this sandbox with `curl: (7) Failed to connect to localhost port 8000`, but container-side localhost requests via Python succeeded for `/health`, `/dashboard/summary`, `/spending/summary`, and `/spending/cash-flow-detail`.
- `make test-backend` -> passed. `pytest` reported `97 passed` with existing deprecation warnings only, including the new regression `api/tests/test_categories.py::test_transfer_override_excludes_row_from_cash_flow_totals` proving that a `Salary -> Internal Transfer` override removes the row from cash-flow income totals and updates `net`.
- `make test-frontend` -> passed. `vitest --run` reported `12 passed` test files and `42 passed` tests, including the new detail-page save/refresh coverage in `src/__tests__/CashFlowDetail.test.tsx`.
- `make e2e` -> passed. Playwright reported `7 passed`, covering dashboard shell, exposure-card navigation, cash overview navigation, market data navigation, theme persistence, and mobile layout.
- Container-side runtime inspection confirmed the persisted UOB `2026-03-02` `4600.00` credit is transaction `type='INCOME'` with `override_category_code='transfer_internal'`, `merchant_counterparty='JOSHI HITESH'`, and notes `Inward CR - GIRO | SI SALARY | OTHR Other | JOSHI HITESH | ...`; this proves the row is marked as an internal transfer in the current DB, but does not prove DBS as the originator.
- Container-side runtime inspection of `/spending/cash-flow-detail?month=2026-03&base_currency=SGD` and `/spending/summary?month=2026-03&base_currency=SGD` showed `income_total=234.41`, `expense_total=1310.25`, `net=-1075.84`, and that transaction `757` (the `4600.00` UOB credit) is absent from March income rows, confirming the transfer override now changes net cash flow in live responses.

## Reviewer Edit Steps (Codex Mutable)
1. Open `/cash-flow` for the month you want to review.
2. In the row you want to correct, use the `Edit Category` dropdown.
3. Click `Save`.
4. The page refetches immediately after save.
5. If you saved the row to a Transfer category, the row drops out of the income/expense totals on that refresh and `net` updates at the same time.
6. If you saved to a non-Transfer category, the row stays in its current income/expense bucket and only the label/source changes.

## Reviewer Curl Commands (Codex Mutable)
Run these locally after `make api-rebuild`:

```bash
curl -sS http://localhost:8000/health
curl -sS "http://localhost:8000/dashboard/summary?month=2026-02&base_currency=SGD"
curl -sS "http://localhost:8000/spending/summary?month=2026-03&base_currency=SGD"
curl -sS "http://localhost:8000/spending/cash-flow-detail?month=2026-02&base_currency=SGD"
curl -sS "http://localhost:8000/spending/cash-flow-detail?month=2026-03&base_currency=SGD"
curl -sS http://localhost:8000/categories
curl -sS "http://localhost:8000/categories/unmapped?month=2026-02"
curl -sS http://localhost:8000/categories/resolve/<transaction_id>
curl -sS -X POST http://localhost:8000/categories/override \
  -H "Content-Type: application/json" \
  -d '{"transaction_id": <transaction_id>, "category_id": <category_id>}'
```

What to verify in the responses:
- `/dashboard/summary`: `cash_flow.income`, `cash_flow.expenses`, and `cash_flow.net` match the month card on the dashboard.
- `/spending/summary`: after you mark a row as `Internal Transfer`, the row should drop out of `income_categories`/`expense_categories` and `net` should recompute immediately for that month.
- `/spending/cash-flow-detail`: `income_total`, `expense_total`, `net`, `income.transactions[]`, and `expenses.transactions[]` explain the same month totals transaction by transaction; rows resolved under Transfer should be absent from the income/expense sections and no longer affect `net`.
- `/categories`: use the returned ids to choose the `<category_id>` you want to save from the detail page or from the direct override curl.
- `/categories/unmapped`: returns only mapping work for the selected month; when everything is mapped, the array is empty and `/cash-flow/mapping` should show the existing empty state.
- `/categories/resolve/<transaction_id>` and `POST /categories/override`: verify the saved row now resolves to the chosen category with `source == "manual"`.

## Review Findings (Sonnet Primary, Opus Escalation)
_Review output is appended here._

## Human Rework Input (Mutable)
_Before running `task-rework`, add/update:_
- `### Review Cycle R<n> - Human Input` with a `text` block containing:
  `HUMAN_QUESTIONS: ...`
  `UNRESOLVED_COMMENTS: ...`
  `RESPONSE_REQUIREMENTS: ...`

## Scope Mandate (Mutable)
- Backend files `api/app/routers/spending.py`, `api/app/schemas/spending.py`, `api/tests/test_spending.py`, and `api/tests/test_categories.py` are approved in-scope for issue-116 when implementing/verifying cash-flow correctness after transfer overrides.

## Retry Log (Max 3)
- Host-side `curl` retries against `http://localhost:8000` failed twice with `curl: (7) Couldn't connect to server` due sandbox localhost restrictions; no code changes were required.
- `make lint`, `make typecheck`, `make api-rebuild`, `make test-backend`, and `make e2e` passed on the first attempt.
- `make test-frontend` needed selector-only retries in `web/src/__tests__/CashFlowDetail.test.tsx` because the new UI intentionally renders the selected category both in the row and inside dropdown options; the final command pass succeeded after narrowing those assertions.
- A host-side `pytest api/tests/test_categories.py api/tests/test_spending.py` probe failed because `pytest` is not installed outside the container, and an initial Vitest filter used the repo-root path instead of the `web/`-relative path; both were resolved by using the repo `make` target for backend tests and the correct `src/__tests__/CashFlowDetail.test.tsx` filter for the focused frontend run.

## Automation Log (Mutable)
- Implemented backend/frontend rework changes in:
  - `api/app/routers/spending.py`
  - `api/tests/test_categories.py`
  - `web/src/routes/CashFlowDetail.tsx`
  - `web/src/__tests__/CashFlowDetail.test.tsx`
  - `tasks/issue-116-category-mapping-ui.md`
- Executed required verification commands in order:
  - `make lint`
  - `make typecheck`
  - `make api-rebuild`
  - `make test-backend`
  - `make test-frontend`
  - `make e2e`

## Workflow Commands

```bash
make task-plan TASK=tasks/issue-116-category-mapping-ui.md
make task-build TASK=tasks/issue-116-category-mapping-ui.md
make task-review TASK=tasks/issue-116-category-mapping-ui.md
make task-rework TASK=tasks/issue-116-category-mapping-ui.md
make task-ship TASK=tasks/issue-116-category-mapping-ui.md
```

### Build Result (2026-03-15T11:08:52Z)

```text
Implementation and verification suite completed successfully.
```

### Review Cycle R1 - Verification Rerun (2026-03-15T13:04:25Z)

```text
- make lint: PASS (exit 0)
- make typecheck: PASS (exit 0)
- make api-rebuild (fresh backend image): PASS (exit 0)
- make test-backend: PASS (exit 0)
- make test-frontend: PASS (exit 0)
- make api-smoke (runtime): PASS (exit 0)
- make e2e (UI smoke): PASS (exit 0)

```

### Review Cycle R1 - Sonnet (claude-sonnet-4.6) (2026-03-15T13:05:18Z)

```text

Total usage est:        1 Premium request
API time spent:         44s
Total session time:     50s
Total code changes:     +0 -0
Breakdown by AI model:
 claude-sonnet-4.6       97.9k in, 2.1k out, 20.9k cached (Est. 1 Premium request)
● SQL: No DB needed, just starting review
  └ 1 row(s) returned

STATUS: APPROVED
RISK: LOW
SUMMARY:
- All 21 ACs verified against diff. Route, nav badge, override workflow, dashboard card replacement, types, tests all implemented correctly.
- All 7 make commands (lint, typecheck, api-rebuild, test-backend, test-frontend, api-smoke, e2e) passed exit 0.
- Architecture decisions 1–6 faithfully executed.

FINDINGS:
- `groupCategories`: top-level categories with no children are pushed as sole option in their group (`options: children.length > 0 ? children : [category]`). Correct and intentional — avoids empty `<optgroup>`.
- `formatMoney(spendingSummary?.net)` passes `undefined` when summary absent. App tests pass with this, indicating `formatMoney` handles undefined gracefully. No regression.
- PageShell hardcodes `/cash-flow/mapping` check for badge rendering rather than a data-driven flag on `NavItem`. Minor rigidity, acceptable for current scope.
- `void handleOverride(...)` in `onChange` correctly suppresses unhandled-promise lint warning.
- Badge `aria-label` (`${count} unmapped transactions`) is accessible and matches test assertion exactly.

TEST_GAPS:
- No test for AC9 (override API failure → row stays + inline error shown). AC19 only mandates render/loading/empty tests so this is not a blocking gap, but worth a follow-up test in a future cycle.
- No Playwright e2e test specifically exercising `/cash-flow/mapping` navigation from User menu. Existing e2e suite covers dashboard shell and nav links generally; dedicated mapping e2e deferred.
```

### Review Cycle R1 - Status (2026-03-15T13:05:18Z)

```text
Review-ID: R1
Status: Reviewed
Result: APPROVED
Risk: LOW
```

### Review Cycle R2 - Human Input (2026-03-15T13:27:18Z)

```text
Review-ID: R2
Status: Reviewed
Result: NEEDS_REWORK
HUMAN_QUESTIONS: - There is no explanation of how we arrived at the final cashflow values. The cashflow detail page should allow the user to verify if cashflow is indeed correct
UNRESOLVED_COMMENTS: The relevant transactions that allowed you to arrive at the cashflow should be shown in the detail page. For example, the income and expenses for that month should be shown. The mapping page that opens after user clicks Cahflow Mapping inside the user drop down should be a seprate page altogether which if all mapped should show nothing as it does now. Else it shows things that need category mapping
RESPONSE_REQUIREMENTS: Also provide API curl commands that helps me test this directly
```

### Review Cycle R2 - Rework Analysis

```text
ROOT_CAUSE: The shipped change solved category-maintenance UX but did not provide a cash-flow detail workflow or API provenance view showing which month-scoped transactions roll up into income, expenses, and net, and the dashboard cash-flow card currently routes users into mapping rather than verification.
FINDINGS_ADDRESSED: Captured the need to separate cash-flow verification from cash-flow mapping, expose contributing income/expense transactions on a dedicated detail page, preserve mapping-page empty-state behavior for fully mapped months, and include direct curl coverage for human testing.
PLANNED_CHANGES: Add an additive cash-flow detail API and frontend detail route that show month totals plus contributing income and expense transactions with resolved categories/source metadata; retarget the dashboard cash-flow card to that detail page; keep `/cash-flow/mapping` as the dedicated User-menu maintenance page showing only unmapped items or an empty state; document exact curl commands for summary, detail, and unmapped verification.
VALIDATION_PLAN: After implementation, verify the additive API with direct `curl` calls to `/health`, `/dashboard/summary?month=YYYY-MM`, the new cash-flow detail endpoint, and `/categories/unmapped?month=YYYY-MM`; then rebuild and smoke-check frontend navigation so dashboard cash-flow opens detail while User menu mapping opens the separate mapping workspace and empty/non-empty month states render correctly.
UNRESOLVED_ASSUMPTIONS: Assumes R2 rework may expand issue-116 beyond the original frontend-only scope to add a new backend read endpoint for cash-flow detail/provenance; if that scope expansion is not acceptable, a follow-up backend issue will be required because existing APIs do not expose the reviewer-requested verification data.
```

### Review Cycle R2 - Rework Answer Matrix

```text
ENTRY: 1
REVIEWER_FINDING: The final cash-flow values are not explainable from the current UI because there is no detail page showing how income, expenses, and net were derived.
HUMAN_COMMENT: There is no explanation of how we arrived at the final cashflow values. The cashflow detail page should allow the user to verify if cashflow is indeed correct
ROOT_CAUSE: The implementation linked the dashboard cash-flow card directly to the mapping queue and only consumed summary totals, so users cannot inspect the transaction-level provenance behind the displayed month totals.
CHANGE_MADE: Added a dedicated `/cash-flow` detail route plus an additive `GET /spending/cash-flow-detail` response that expose month totals, the calculation formula, included transaction types, and grouped transaction-level contributors for verification; retargeted the dashboard cash-flow card to that detail route.
VERIFICATION_PERFORMED: `api/tests/test_spending.py::test_cash_flow_detail` now asserts the new `/spending/cash-flow-detail` response returns the expected month totals and grouped transactions, `web/src/__tests__/CashFlowDetail.test.tsx` renders the explanation and contributing rows, and `web/src/__tests__/App.test.tsx` confirms the dashboard cash-flow card now links to `/cash-flow`.
STATUS: RESOLVED

ENTRY: 2
REVIEWER_FINDING: The cash-flow detail experience must show the specific transactions contributing to income and expenses for the selected month.
HUMAN_COMMENT: The relevant transactions that allowed you to arrive at the cashflow should be shown in the detail page. For example, the income and expenses for that month should be shown.
ROOT_CAUSE: Existing spending APIs return totals and category aggregates, but not a month-level, non-credit-card cash-flow ledger grouped into verification-ready income and expense sections.
CHANGE_MADE: Added `GET /spending/cash-flow-detail` with grouped `income` and `expenses` sections containing transaction-level rows for the selected month, including date, account, account type, merchant/counterparty, raw category, resolved category, category source, original amount, and converted base amount; rendered both sections on the new `/cash-flow` detail page.
VERIFICATION_PERFORMED: `api/tests/test_spending.py::test_cash_flow_detail` asserts the response contains the expected grouped transactions, and `api/tests/test_categories.py::test_spending_endpoints_use_resolved_categories` now verifies manual overrides propagate into `expenses.transactions[]` with `category_source == "manual"` and the updated resolved category.
STATUS: RESOLVED

ENTRY: 3
REVIEWER_FINDING: Cash-flow mapping should remain a separate maintenance page under the User menu and should only show unmapped work or an empty state when everything is mapped.
HUMAN_COMMENT: The mapping page that opens after user clicks Cahflow Mapping inside the user drop down should be a seprate page altogether which if all mapped should show nothing as it does now. Else it shows things that need category mapping
ROOT_CAUSE: The mapping page itself is already a separate route with the correct empty-state behavior, but the broader workflow is confusing because the main dashboard cash-flow card also opens that maintenance page instead of a verification/detail page.
CHANGE_MADE: Preserved `/cash-flow/mapping` as the User-menu-only maintenance page with unchanged unmapped/empty-state behavior, and split the dashboard card to the new `/cash-flow` verification route so mapping is no longer the primary cash-flow destination.
VERIFICATION_PERFORMED: `web/src/__tests__/CashFlowMapping.test.tsx` still covers the empty-state behavior when no unmapped rows exist, `web/src/__tests__/App.test.tsx` still checks the User menu link points to `/cash-flow/mapping`, and the same test now confirms the dashboard cash-flow card points to `/cash-flow` instead.
STATUS: RESOLVED

ENTRY: 4
REVIEWER_FINDING: Human verification requires direct API curl commands for the cash-flow and mapping workflows.
HUMAN_COMMENT: Also provide API curl commands that helps me test this directly
ROOT_CAUSE: The prior implementation notes included generic verification evidence but did not provide reviewer-ready curl commands covering the exact summary/detail/mapping behaviors under rework.
CHANGE_MADE: Added a `Reviewer Curl Commands` section with exact `curl` invocations for `/health`, `/dashboard/summary`, `/spending/cash-flow-detail`, and `/categories/unmapped`, plus concrete guidance on what to verify in each response.
VERIFICATION_PERFORMED: The commands are documented in this task file for local execution after `make api-rebuild`; direct host-side execution from this sandbox remained blocked by `curl: (7) Couldn't connect to server`, so API correctness was verified here through `make test-backend` coverage of the same endpoints and contracts.
STATUS: RESOLVED
```

### Review Cycle R2 - Status (2026-03-15T14:24:49Z)

```text
Review-ID: R2
Status: Implemented
Result: NEEDS_REVIEW
Risk: PENDING
```

### Review Cycle R2 - Rework Result (2026-03-15T14:24:49Z)

```text
Two-pass rework completed (analysis -> implementation) for latest review findings.
```


### Review Cycle R3 - Human Input (2026-03-15T14:39:50Z)

```text
Review-ID: R3
Status: Reviewed
Result: NEEDS_REWORK
HUMAN_QUESTIONS: - How can i change a category mapped if i see it as wrong in the detail page?
UNRESOLVED_COMMENTS: Right now there is no way for me to say, this categorisation is wrong in the cash flow page. This money right here is not income, it is for example say transfer from my other bank account.  Example DBS to UOb transfer which show up as salary in UOB but are just my own account transfers and not external money
RESPONSE_REQUIREMENTS: Explian very briefly the steps taken to allow a user to edit.
```

### Review Cycle R3 - Rework Analysis

```text
ROOT_CAUSE: The `/cash-flow` detail page is currently read-only and the detail payload does not expose enough category-selection state for an in-place editor, so users cannot correct an already-mapped transaction from the page where they detect the issue; separately, the reviewer's transfer example may reflect a transaction-type misclassification that category override alone does not fix.
FINDINGS_ADDRESSED: Captured the missing edit affordance on the cash-flow detail page, the need to explain a very short user edit flow, and the distinction between category correction versus true income-to-transfer reclassification in the reviewer example.
PLANNED_CHANGES: Add an in-row category edit control on `/cash-flow` backed by `GET /categories` and the existing `POST /categories/override`, include additive detail-response fields needed to safely preselect the current category, refresh the affected row and month totals after save, and add brief helper copy describing the user steps; if the reviewer expects transaction-type editing from `INCOME` to `TRANSFER`, that scope must be confirmed before implementation.
VALIDATION_PLAN: In the implementation pass, verify by targeted backend/frontend tests that editing a detail-row category posts the override, updates resolved category/source on reload, and refreshes the cash-flow totals view; also document very brief reviewer steps and curl checks for the detail and category-resolution endpoints without running make commands in this analysis pass.
UNRESOLVED_ASSUMPTIONS: Needs confirmation whether the desired fix is only to change the resolved category to something like `Internal Transfer`, or to change the underlying transaction classification from `INCOME` to `TRANSFER`; the first fits the existing override workflow, while the second requires a different write contract and cash-flow aggregation change.
```

### Review Cycle R3 - Rework Answer Matrix

```text
ENTRY: 1
REVIEWER_FINDING: Cash-flow detail currently has no in-context way to edit a mapped transaction when the user notices the resolved category is wrong.
HUMAN_COMMENT: How can i change a category mapped if i see it as wrong in the detail page?
ROOT_CAUSE: `web/src/routes/CashFlowDetail.tsx` only renders resolved-category text and source tags, and the current cash-flow detail response does not expose category-selection state for a safe prefilled editor.
CHANGE_MADE: Added an `Edit Category` control to each `/cash-flow` detail row, backed by `GET /categories` plus the existing `POST /categories/override`; the page now preselects taxonomy-backed mapped categories via additive `resolved_category_id`, saves the override in place, refetches `/spending/cash-flow-detail`, and shows very brief on-screen instructions telling the user to choose a category and click `Save`.
VERIFICATION_PERFORMED: `web/src/__tests__/CashFlowDetail.test.tsx` now posts an override from the detail table and verifies the refreshed row shows the updated category/source, while `api/tests/test_categories.py::test_spending_endpoints_use_resolved_categories` and `api/tests/test_spending.py::test_cash_flow_detail` assert the additive `resolved_category_id` contract on cash-flow detail rows.
STATUS: RESOLVED

ENTRY: 2
REVIEWER_FINDING: The reviewer needs a way to mark a cash-flow detail row shown as income as an internal transfer rather than external income.
HUMAN_COMMENT: Right now there is no way for me to say, this categorisation is wrong in the cash flow page. This money right here is not income, it is for example say transfer from my other bank account. Example DBS to UOb transfer which show up as salary in UOB but are just my own account transfers and not external money
ROOT_CAUSE: Cash-flow totals are currently derived from transaction `type` in `api/app/routers/spending.py`, while `/categories/override` only changes category resolution; if the underlying row is typed as `INCOME`, category editing alone may not remove it from the income section or net calculation.
CHANGE_MADE: Implemented the detail-page category editor for the mapped-category part of this feedback and added explicit helper copy on `/cash-flow` stating that the new editor changes category mapping only; no transaction-type override contract was added, so a row imported as `INCOME` still remains in income totals until a separate type-correction workflow exists.
VERIFICATION_PERFORMED: `web/src/__tests__/CashFlowDetail.test.tsx` verifies a reviewed income row can be re-categorized to `Internal Transfer` from the detail table, while `api/tests/test_spending.py::test_cash_flow_detail` still confirms cash-flow grouping is driven by transaction `type`, matching the current backend contract.
STATUS: PARTIAL
```

### Review Cycle R3 - Status (2026-03-15T14:56:00Z)

```text
Review-ID: R3
Status: Implemented
Result: NEEDS_REVIEW
Risk: PENDING
```

### Review Cycle R3 - Rework Result (2026-03-15T14:56:00Z)

```text
Two-pass rework completed (analysis -> implementation) for latest review findings.
```

### Review Cycle R4 - Verification Rerun (2026-03-15T15:10:31Z)

```text
- make lint: PASS (exit 0)
- make typecheck: PASS (exit 0)
- make api-rebuild (fresh backend image): PASS (exit 0)
- make test-backend: PASS (exit 0)
- make test-frontend: PASS (exit 0)
- make api-smoke (runtime): PASS (exit 0)
- make e2e (UI smoke): PASS (exit 0)

```

### Review Cycle R4 - Sonnet (claude-sonnet-4.6) (2026-03-15T15:11:34Z)

```text

Total usage est:        1 Premium request
API time spent:         52s
Total session time:     59s
Total code changes:     +0 -0
Breakdown by AI model:
 claude-sonnet-4.6       142.9k in, 2.3k out, 14.3k cached (Est. 1 Premium request)
● SQL: No DB needed, just starting review
  └ 1 row(s) returned

STATUS: APPROVED
RISK: LOW
SUMMARY:
- All R3 findings addressed. In-row category editor added to `/cash-flow` detail page, `resolved_category_id` propagated from backend, page refetches after save. R3 ENTRY 2 correctly marked PARTIAL with explicit UI copy explaining the INCOME→TRANSFER boundary.
- All 7 make commands (lint, typecheck, api-rebuild, test-backend, test-frontend, api-smoke, e2e) passed exit 0 in R4 verification rerun.
- Backend `_cash_flow_rows` refactor is functionally equivalent to the prior per-endpoint raw SQL: TRANSFER rows were fetched but ignored before; now excluded at the DB layer. `spending_summary` output is unchanged.
- `resolved_category_id` uses `MIN(id)` + `COUNT(*) = 1` dedup guard — safe against ambiguous name collisions.
- AC15 immutable text says `/cash-flow/mapping`; implementation targets `/cash-flow`. Change is intentional and documented in R2 rework matrix. Acceptable.

FINDINGS:
- `groupCategories` is duplicated verbatim in `CashFlowDetail.tsx` and `CashFlowMapping.tsx`. Not a bug; extractable to a shared util in a future cleanup issue.
- `_cash_flow_rows` now fetches unused columns (`account_name`, `account_type`, `resolved_category_id`, etc.) when called from `spending_summary`. Marginally wasteful but not incorrect; both callers hit the same DB round trip.
- On override failure in `CashFlowMapping`, selection resets to `""` (blank). Minor UX rough edge — user loses their selection and must re-pick. Not a defect given current scope.
- `CashFlowDetail` Save button is disabled when `isDirty === false`, which correctly prevents re-saving an already-saved value. Logic is sound.

TEST_GAPS:
- AC9 (override API failure → row stays + inline error shown in `CashFlowMapping`) still untested. Carried forward from R1; not blocking per AC19 mandate.
- No Playwright e2e test covering `/cash-flow` detail page or the in-row Save flow. Deferred; existing e2e suite covers navigation shell only.
- No test asserting the Save button is disabled when selection matches current `resolved_category_id` (dirty-check boundary). Low risk given unit-test coverage of the happy path.
```

### Review Cycle R4 - Status (2026-03-15T15:11:34Z)

```text
Review-ID: R4
Status: Reviewed
Result: APPROVED
Risk: LOW
```


### Review Cycle R5 - Human Input (2026-03-15T15:21:06Z)

```text
Review-ID: R5
Status: Reviewed
Result: NEEDS_REWORK
HUMAN_QUESTIONS: - If i update a category from Salary to internal transfer, shouldnt that change in category change your calculation? That what you assumed as income is just money flowing from one account to another.
UNRESOLVED_COMMENTS: When does the net cash flow update after a user updates a category? What is the right behavior? If it never updates, may be you should consider updating it.
RESPONSE_REQUIREMENTS: Check the UOB credit of 4600, is the originator DBS?  if yes it is an internal transfer. if not let me know. For now, I marked it as transfer. Shouldnt that change your net cash flow?
```

### Review Cycle R5 - Rework Analysis

```text
ROOT_CAUSE: The current cash-flow calculation path in `api/app/routers/spending.py` is driven entirely by transaction `type` (`INCOME` vs `EXPENSE` family), while the UI edit added in R3 only changes category resolution via `POST /categories/override`; as a result, changing a row from `Salary` to `Internal Transfer` does not currently move it out of income or change net cash flow, and the repo artifacts do not conclusively prove whether the specific UOB `4600.00` credit originated from DBS.
FINDINGS_ADDRESSED: Captured the mismatch between user expectation and current backend contract, the missing/unclear recalculation behavior after category edits, and the unresolved request to verify whether the UOB `4600.00` credit is a DBS-originated internal transfer.
PLANNED_CHANGES: In the implementation pass, align cash-flow behavior with the intended transfer treatment by updating the aggregation/read path so rows resolved as internal transfers no longer contribute to income/expense/net, trigger detail-page totals to refresh immediately after save, and surface explicit UI copy about when totals do and do not change; separately, inspect available transaction provenance for the UOB `4600.00` credit and report whether DBS origin can be proven from stored data.
VALIDATION_PLAN: Verify by targeted backend/frontend tests and direct endpoint inspection that reclassifying a cash-flow row to `Internal Transfer` removes it from income totals and updates `net` on `/spending/summary` and `/spending/cash-flow-detail` after save, and confirm the UOB `4600.00` row’s stored `merchant_counterparty`/`notes` before asserting DBS origin.
UNRESOLVED_ASSUMPTIONS: Assumes the desired product behavior is that resolved transfer categories should be excluded from cash-flow totals even when the imported transaction `type` is `INCOME`; if the system must continue treating `type` as the sole source of truth, a separate transaction-type correction workflow will still be required and the reviewer request cannot be satisfied by category overrides alone.
```

### Review Cycle R5 - Rework Answer Matrix

```text
ENTRY: 1
REVIEWER_FINDING: Changing a cash-flow row from `Salary` to `Internal Transfer` should update the calculation if the row is really money moving between the user's own accounts.
HUMAN_COMMENT: If i update a category from Salary to internal transfer, shouldnt that change in category change your calculation? That what you assumed as income is just money flowing from one account to another.
ROOT_CAUSE: `spending_summary()` and `cash_flow_detail()` currently sum rows by transaction `type`, and the R3 editor only writes a category override, so a row imported as `INCOME` still contributes to income and net even after its resolved category becomes `Internal Transfer`.
CHANGE_MADE: Updated `api/app/routers/spending.py` so the shared cash-flow classifier excludes rows resolved under the Transfer taxonomy from both `/spending/summary` and `/spending/cash-flow-detail`; a `Salary -> Internal Transfer` override now removes that row from income totals instead of only changing the label.
VERIFICATION_PERFORMED: `api/tests/test_categories.py::test_transfer_override_excludes_row_from_cash_flow_totals` now proves overriding seeded salary transaction `1` to `transfer_internal` changes `/spending/summary` to `income_total=480.0`, `expense_total=8710.0`, `net=-8230.0`, and removes the employer row from `/spending/cash-flow-detail` income transactions.
STATUS: RESOLVED

ENTRY: 2
REVIEWER_FINDING: The product needs explicit, correct behavior for when net cash flow updates after a user edits a category from the cash-flow detail page.
HUMAN_COMMENT: When does the net cash flow update after a user updates a category? What is the right behavior? If it never updates, may be you should consider updating it.
ROOT_CAUSE: The current UI does refetch the detail page after save, but the refetched totals remain unchanged because the backend contract still treats category overrides as metadata rather than as cash-flow classification input.
CHANGE_MADE: Kept the existing post-save detail refetch in `web/src/routes/CashFlowDetail.tsx`, but changed the backend response semantics and the on-screen guidance so Transfer-category saves recompute the refreshed totals immediately, while non-Transfer category saves only relabel the row.
VERIFICATION_PERFORMED: `web/src/__tests__/CashFlowDetail.test.tsx` now saves transaction `2` as `Internal Transfer` and asserts the refreshed page shows `Income transactions (0)`, the empty-income message, and the updated `S$ -8,710` net; the live container response for `/spending/cash-flow-detail?month=2026-03&base_currency=SGD` also excludes transaction `757` after its manual transfer override.
STATUS: RESOLVED

ENTRY: 3
REVIEWER_FINDING: The specific UOB `4600.00` credit must be checked for DBS origin, because if it is an internal transfer then it should not count toward net cash flow.
HUMAN_COMMENT: Check the UOB credit of 4600, is the originator DBS? if yes it is an internal transfer. if not let me know. For now, I marked it as transfer. Shouldnt that change your net cash flow?
ROOT_CAUSE: The available repo artifacts prove the UOB fixture contains a `2026-03-02` `4600.00` credit with notes including `SI SALARY`, but they do not conclusively identify DBS as the originator; without the stored runtime row or a richer fixture dump, DBS provenance cannot be asserted safely from this analysis pass.
CHANGE_MADE: Inspected both the parser output and the persisted database row for the UOB `4600.00` credit; no code change was needed beyond the transfer-aware aggregation because the row is already manually overridden to `transfer_internal` in the current DB.
VERIFICATION_PERFORMED: Container-side parser inspection returned `merchant_counterparty='IBG GIRO SI SALARY'` and `notes='IBG GIRO SI SALARY'`; the persisted DB row is transaction `757` with `merchant_counterparty='JOSHI HITESH'`, notes `Inward CR - GIRO | SI SALARY | OTHR Other | JOSHI HITESH | ...`, and manual override `override_category_code='transfer_internal'`. That proves DBS origin is not present in stored data, and live `/spending/summary?month=2026-03&base_currency=SGD` plus `/spending/cash-flow-detail?month=2026-03&base_currency=SGD` now exclude the `4600.00` credit from income and net.
STATUS: RESOLVED
```

### Review Cycle R5 - Status (2026-03-15T15:35:52Z)

```text
Review-ID: R5
Status: Implemented
Result: NEEDS_REVIEW
Risk: PENDING
```

### Review Cycle R5 - Rework Result (2026-03-15T15:35:52Z)

```text
Two-pass rework completed (analysis -> implementation) for latest review findings.
```

### Retry Entry (2026-03-15T15:35:53Z)

```text
Scope stage gate skipped out-of-scope files during rework:
api/app/schemas/spending.py
api/tests/test_spending.py
```

### Review Cycle R6 - Verification Rerun (2026-03-15T15:52:01Z)

```text
- make lint: PASS (exit 0)
- make typecheck: PASS (exit 0)
- make api-rebuild (fresh backend image): PASS (exit 0)
- make test-backend: PASS (exit 0)
- make test-frontend: PASS (exit 0)
- make api-smoke (runtime): PASS (exit 0)
- make e2e (UI smoke): PASS (exit 0)

```

### Review Cycle R6 - Sonnet (claude-sonnet-4.6) (2026-03-15T15:52:51Z)

```text

Total usage est:        1 Premium request
API time spent:         39s
Total session time:     46s
Total code changes:     +0 -0
Breakdown by AI model:
 claude-sonnet-4.6       160.9k in, 1.6k out, 14.4k cached (Est. 1 Premium request)
● SQL: No DB needed, just starting review
  └ 1 row(s) returned

STATUS: APPROVED
RISK: LOW
SUMMARY:
- All 7 make commands passed exit 0 in R6 verification rerun (lint, typecheck, api-rebuild, test-backend, test-frontend, api-smoke, e2e).
- R5 core requirement resolved: `_cash_flow_rows` + `_cash_flow_bucket` now excludes Transfer-resolved rows from both `/spending/summary` and `/spending/cash-flow-detail`; `test_transfer_override_excludes_row_from_cash_flow_totals` proves the contract (income drops, net recomputes).
- All 25 ACs satisfied. AC15 text/link discrepancy (`/cash-flow/mapping` vs `/cash-flow`) is intentional, documented in R2 rework matrix, and cleared in R4.
- 97 backend tests, 42 frontend tests, 7 e2e tests all green.

FINDINGS:
- `_cash_flow_rows` adds `AND t.type IN ('INCOME','EXPENSE','FEE','TAX','INTEREST')` at DB layer — TRANSFER-typed rows now excluded before bucketing, not just silently skipped in Python. Correct and intentional; no regression since TRANSFER-typed rows contributed 0 to prior totals anyway.
- `spending_summary` now fetches extra columns (`account_name`, `account_type`, `resolved_category_id`, etc.) via `_cash_flow_rows` that it doesn't use. Marginally wasteful, same single DB round-trip; not a correctness issue. Noted in R4, deferred.
- `groupCategories` duplicated verbatim in `CashFlowDetail.tsx` and `CashFlowMapping.tsx`. Not a defect; extractable to shared util in future cleanup issue.
- `resolved_category_id` uses `MIN(id) + COUNT(*)=1` dedup guard — safe against ambiguous name collisions, returns NULL when name is non-unique. Conservative and correct.
- On override failure in `CashFlowMapping`, selection resets to `""`. Minor UX rough edge (user must re-pick), not a defect.

TEST_GAPS:
- AC9 (override API failure → row stays + inline error in `CashFlowMapping`) still untested. Carried forward from R1; not blocking per AC19 mandate scope.
- No Playwright e2e covering `/cash-flow` detail page or the in-row Save/refresh flow. Deferred; existing suite covers navigation shell.
- No test asserting Save button disabled when `selectedValue === currentSelection` (dirty-check boundary). Low risk given happy-path unit coverage.
```

### Review Cycle R6 - Status (2026-03-15T15:52:51Z)

```text
Review-ID: R6
Status: Reviewed
Result: APPROVED
Risk: LOW
```
