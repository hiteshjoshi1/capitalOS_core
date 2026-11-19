# Issue 450: Liabilities page becomes Cards; Overview hero labels estimated card debt

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/450

Part of #432 (UX review, V2).

## Objective
- The "Liabilities" page is about credit cards: call it **Cards** (sidebar, bottom nav, heading) at `/cards`.
- Drop its subtitle "… without unreliable balance estimates": card balances are estimates when no statement
  balance is on file.
- The Overview hero says how much of the card debt it subtracts is estimated ("incl. S$ 53K estimated card debt").

## Architecture Decisions
- Route: `/cards` renders the page; `/liabilities`, `/liabilities/credit-cards`, `/credit-cards` and `/loans`
  redirect to it with `RedirectKeepingSearch` (keeps `?card=` from Inbox links, which a plain `<Navigate>` drops).
  Backend links (bridge items, Inbox card actions, insight alerts) now point at `/cards`.
- Internal names stay (`LiabilitiesOverview.tsx`, `lib/liabilities.ts`, CSS classes, e2e spec file name): renaming
  them is churn with no user-visible effect.
- "Liabilities" stays where it means the net-worth component: the Overview signal card ("LIABILITIES", its link
  now "Open cards"), History's table column and chart tooltip, the drill-down panel.
- API (additive): `NetWorth.estimated_liabilities` (optional float): the part of `liabilities` from cards with no
  dated (statement) balance on file, i.e. `_credit_card_liability_details` entries with `method == "transactions"`.
  Present on every `net_worth` / `current_net_worth` / `view_net_worth` built by `_networth_components`, and on the
  timeline's `now` point. History rows don't store it (no migration); stored points don't carry it.
- Hero shows the label only when `estimated_liabilities >= 0.5`; nothing otherwise. Compact money, links to `/cards`.

## Acceptance Criteria
- [x] Nav (sidebar + bottom), page heading say Cards; old URL redirects.
- [x] Subtitle gone.
- [x] Hero shows "incl. <amount> estimated card debt" only when some card debt is an estimate.
- [x] New API field with a backend test; TS types mirror it.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest tests/test_dashboard.py -k estimated`
- `cd web && npx vitest run src/__tests__/WealthOverview.test.tsx src/__tests__/RedirectKeepingSearch.test.tsx`
- `make e2e-smoke`: `/cards` screenshots replace `/liabilities` ones.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Deterministic Gate Results (Codex Mutable)
- `lint`: pass — `make lint`
- `typecheck`: pass — `make typecheck` (mypy), `npx tsc -b`
- `tests`: pass — backend 1346 passed, 27 skipped (Docker); frontend `npm test -- --run` 88 files, 729 tests
- `e2e`: pass — `make e2e-smoke-update` 45 passed. The demo fixture was edited by a script, not re-recorded
  (a re-record pulls today's data into every page and drops the hand-added `POST /dashboard/visit`):
  `estimated_liabilities` (= `liabilities`, the demo cards have no statement balance) on the 12 net-worth
  objects, and the 4 bridge links `/liabilities` → `/cards`. Screenshots: wealth (hero label, "Open cards"),
  cards (new name/path; liabilities PNGs removed).

## Extra Files Changed (Codex Mutable)
- `web/tests/e2e/fixtures/demo-api.json` — reason: new field + `/cards` links (scripted edit).
- `api/tests/golden/valuation/*.json` — reason: regenerated (UPDATE_GOLDEN=1); only `estimated_liabilities` lines added.
- `api/tests/test_valuation_invariants.py`, `test_past_months_history.py`, `test_user_timezone.py`,
  `test_contracts.py` — reason: they compared History points / key sets against the dashboard's `net_worth`,
  which now carries the extra field.
