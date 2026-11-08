# Issue 316: One "needs action" list: API + Inbox page

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/316

## Objective
- The Data Hub Overview puts what needs you first, each with its button (#309's review).

## Architecture Decisions
- `GET /operations/inbox` (`app/services/inbox.py`, D-80): items with kind, severity, title, detail, action
  (route + params, or a refresh `run`), `admin_only` for shared-data actions; `all_good` lines; recent activity.
- Kinds: source_overdue / source_never_loaded (with the freshness row, so the page builds #278's prefilled
  Upload link), unknown_format (NEEDS_MAPPING = no parser matched → "Fix format", `/ingest?job=<id>`, #315),
  import_pending, unpriced_holding, fx_gap, fx_unsupported, job_failing, unmapped_transactions.
- Page: "Refresh all" (header; ▾ menu per source; non-admins don't get the shared refreshes), "Needs you",
  add links, "All good (N)" collapsed, latest activity in one line, every source's schedule collapsed.
  Removed: stat cards, job cards, unpriced card, the refresh grid (all now items or the menu).

## Acceptance Criteria
- [x] 375px: first button at 257px (target < 400). Desktop page height 930px (target < 1,200), demo data.
- [x] Backend tests per item kind, owner scoping, ordering; vitest for the page (7); e2e Data Hub specs pass.

<!-- IMMUTABLE_PLAN_END -->
