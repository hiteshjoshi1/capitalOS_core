# Issue 116: Cash Flow Category Mapping UI + Override Workflow

## Objective

Build the category-mapping UI as an operational workflow under the User context, not on Dashboard. Consume the backend APIs shipped in issue-115 (`GET /categories`, `GET /categories/unmapped`, `POST /categories/override`, `GET /categories/resolve/{id}`, `POST /categories/backfill`). Dashboard must stop showing the cash-flow mapping placeholder card after this change.

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
- UI/frontend only in this story (consume existing backend APIs from issue-115).
- No backend schema/API changes.
- No unrelated UI redesign.

## Architecture Decisions

- **Decision 1: Unmapped count in User menu via PageShell prop.** Rather than making PageShell fetch data itself (violating separation of concerns), the mapping page route component and the Dashboard will pass an `unmappedCount` prop to PageShell. Only the CashFlowMapping page needs real-time accuracy; Dashboard can use a lightweight fetch. PageShell renders the badge conditionally when count > 0. This keeps PageShell a pure presentational shell.

- **Decision 2: API types mirror backend Pydantic schemas exactly.** New TypeScript types `CategoryTaxonomy`, `UnmappedTransaction`, `CategoryOverridePayload`, and `CategoryResolution` are added to `web/src/lib/api.ts` matching the backend `CategoryTaxonomyOut`, `UnmappedTransactionOut`, `CategoryOverrideCreate`, and `CategoryResolutionOut` schemas field-for-field. No mapping or transformation layer.

- **Decision 3: Optimistic row removal after override.** When a user selects a category for an unmapped transaction and the `POST /categories/override` succeeds, the transaction row is removed from the local state immediately. No full refetch required. On failure, the row remains and an inline error is shown. This minimizes API calls and provides instant feedback.

- **Decision 4: Dashboard cash-flow PlaceholderCard replacement.** The `PlaceholderCard` in dashboard row2 (lines 144-148 of `App.tsx`) is replaced with an `ExposureLinkCard` that links to `/cash-flow/mapping` and shows spending summary data (income/expense/net from existing `spendingSummary` state). This provides a useful dashboard card while directing users to the mapping workflow.

- **Decision 5: CSS-only badge in User menu.** A small `.menuBadge` CSS class renders a pill-shaped count next to the "Cash Flow Mapping" link in the User menu Navigate section. Uses existing `--warn` color for visibility. No third-party badge component needed.

- **Decision 6: Month-scoped unmapped count.** The unmapped count badge reflects the currently selected month. The `GET /categories/unmapped?month=YYYY-MM` endpoint is used. This ensures the badge is contextually accurate.

## Risks

- **Risk 1: Backend APIs not running.** If issue-115 migration hasn't been applied or API is down, the mapping page will show an error state. Mitigation: graceful error handling with actionable message ("Run `make db-migrate` then `make api-rebuild`").
- **Risk 2: Empty unmapped queue edge case.** If all transactions have been mapped or none exist for the month, the page should render a clear empty state, not a broken UI. Mitigation: explicit empty state component.
- **Risk 3: PageShell prop change affects all pages.** Adding `unmappedCount` prop to PageShell changes its interface. Mitigation: prop is optional with `undefined` default, so all existing usages remain unaffected.
- **Risk 4: Large unmapped transaction list.** If hundreds of unmapped transactions exist, the page could be slow. Mitigation: backend already returns results ordered by `ts DESC` and the list is month-scoped, naturally limiting size. Pagination deferred to future issue if needed.

## Open Questions

- None. All required backend APIs exist. Frontend-only implementation with well-defined API contracts.

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
- [ ] AC15: Dashboard row2 first card is replaced with an ExposureLinkCard linking to `/cash-flow/mapping` showing cash flow summary data.
- [ ] AC16: TypeScript types compile with strict mode (`npx tsc -b`).
- [ ] AC17: ESLint passes (`npx eslint .`).
- [ ] AC18: All existing frontend tests continue to pass (`vitest --run`).
- [ ] AC19: New test file `web/src/__tests__/CashFlowMapping.test.tsx` exists with at least: render test, loading state test, empty state test.
- [ ] AC20: After page refresh, previously applied overrides remain reflected (transaction no longer appears in unmapped list).
- [ ] AC21: `api.ts` exports new types: `CategoryTaxonomy`, `UnmappedTransaction`, `CategoryResolution`, and new API methods: `categories()`, `unmappedTransactions()`, `categoryOverride()`.

## Human Approval Gate

- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist

### 1. Add TypeScript types and API methods (`web/src/lib/api.ts`)
- [ ] Add `CategoryTaxonomy` type matching backend `CategoryTaxonomyOut`: `{ id: number; code: string; name: string; parent_id: number | null; display_order: number }`
- [ ] Add `UnmappedTransaction` type matching backend `UnmappedTransactionOut`: `{ transaction_id: number; ts: string; account_id: number; account_name: string; amount: number; currency: string; type: string; raw_category: string | null; merchant_counterparty: string | null; notes: string | null }`
- [ ] Add `CategoryOverridePayload` type: `{ transaction_id: number; category_id: number }`
- [ ] Add `CategoryResolution` type matching backend `CategoryResolutionOut`: `{ transaction_id: number; raw_category: string | null; override_category: string | null; resolved_category: string; source: string; rule_id: number | null; rule_name: string | null }`
- [ ] Add `api.categories()` → `GET /categories` → `CategoryTaxonomy[]`
- [ ] Add `api.unmappedTransactions(month: string, accountId?: number)` → `GET /categories/unmapped?month=...` → `UnmappedTransaction[]`
- [ ] Add `api.categoryOverride(payload: CategoryOverridePayload)` → `POST /categories/override` → `CategoryResolution`

### 2. Create CashFlowMapping page (`web/src/routes/CashFlowMapping.tsx`)
- [ ] Create page component following established pattern (PageShell, LoadState, useEffect)
- [ ] Fetch both `api.categories()` and `api.unmappedTransactions(month)` in parallel on mount/month change
- [ ] Render table with columns: Date, Account, Merchant, Amount, Currency, Type, Raw Category, Override
- [ ] Override column: `<select>` dropdown populated from taxonomy, grouped by parent categories
- [ ] On select change: call `api.categoryOverride()`, on success remove row from state, on error show inline message
- [ ] Loading state: card with "Loading…" text
- [ ] Empty state: card with "All transactions mapped for {month}." message
- [ ] Error state: card with error message and hint to check API/migration

### 3. Add route (`web/src/main.tsx`)
- [ ] Import `CashFlowMapping` from `./routes/CashFlowMapping.tsx`
- [ ] Add `<Route path="/cash-flow/mapping" element={<CashFlowMapping />} />`

### 4. Update PageShell navigation (`web/src/components/PageShell.tsx`)
- [ ] Add optional `unmappedCount?: number` prop to `PageShellProps`
- [ ] Add "Cash Flow Mapping" entry to `MENU_NAV_ITEMS` array: `{ label: "Cash Flow Mapping", to: "/cash-flow/mapping" }`
- [ ] In the Navigate section render loop, conditionally render a `.menuBadge` span next to the "Cash Flow Mapping" label when `unmappedCount` is defined and > 0

### 5. Update Dashboard (`web/src/App.tsx`)
- [ ] Remove the `PlaceholderCard` in row2 (lines 144-148) that shows "Cash flow ingestion is pending final category mapping"
- [ ] Replace with `ExposureLinkCard` linking to `/cash-flow/mapping`: title "Cash Flow", value shows `formatMoney(spendingSummary?.net)` or spending summary data, subtitle shows month context
- [ ] Optionally fetch unmapped count and pass as `unmappedCount` prop to PageShell (lightweight call)

### 6. Add CSS styles (`web/src/App.css`)
- [ ] Add `.menuBadge` class: small pill/badge with `--warn` background color, white text, positioned inline after link text
- [ ] Add `.mappingTable` styles: table layout matching existing card/grid aesthetic
- [ ] Add `.mappingRow` and `.overrideSelect` styles
- [ ] Add `.overrideError` inline error style

### 7. Add tests (`web/src/__tests__/CashFlowMapping.test.tsx`)
- [ ] Test: CashFlowMapping renders without crashing
- [ ] Test: Shows loading state initially
- [ ] Test: Shows empty state when no unmapped transactions

### 8. Verify
- [ ] `make lint` passes
- [ ] `make typecheck` passes
- [ ] `make test-frontend` passes
- [ ] Manual: navigate to `/cash-flow/mapping`, verify page loads
- [ ] Manual: User menu shows "Cash Flow Mapping" link
- [ ] Manual: Dashboard no longer shows old placeholder card

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

## Workflow Commands

```bash
make task-plan TASK=tasks/issue-116-category-mapping-ui.md
make task-build TASK=tasks/issue-116-category-mapping-ui.md
make task-review TASK=tasks/issue-116-category-mapping-ui.md
make task-rework TASK=tasks/issue-116-category-mapping-ui.md
make task-ship TASK=tasks/issue-116-category-mapping-ui.md
```
