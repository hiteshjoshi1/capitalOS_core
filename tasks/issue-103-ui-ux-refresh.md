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
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [ ] T1: Add theme system (`data-theme` + localStorage persistence)
- [ ] T2: Build top nav and user menu components
- [ ] T3: Move month/base-currency/theme controls into user menu
- [ ] T4: Extract dashboard cards into components
- [ ] T5: Refactor `App.tsx` composition/layout
- [ ] T6: Add drill-down links from exposure cards
- [ ] T7: Apply visual hierarchy and responsive layout polish
- [ ] T8: Keep expense cards as placeholders
- [ ] T9: Update/remove obsolete header/subtitle copy
- [ ] T10: Update tests for new dashboard structure
- [ ] T11: Run verification commands (`make lint`, `make typecheck`, `make test-frontend`)
- [ ] T12: Run manual UI validation on desktop/mobile

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
