# Issue #395: a direct month_bridge call for the live month differs from the API

## Cause
The API binds the request user's home timezone (#202) and opens a request scope that freezes
"now" (#147). A direct call (background job, script, test) had neither: it ran in the app
timezone (Asia/Singapore). For a user in New York, 1 Apr 10:00 SGT is still 31 Mar, so the API
values March as the open, live month while the direct call valued it as closed. Not caused by
#360's Decimal change.

## Change
- `app/valuation/context.py`: `valuation_context(db, user_id)` binds the user's timezone and a
  request scope, so a direct call gives exactly what the API returns.
- `tests/test_decimal_money.py`: the exact bridge check now also compares the live month with
  the API, and a new test reproduces the New York case (bare call: closed; in the context and in
  the API: live, same end value and dates).
