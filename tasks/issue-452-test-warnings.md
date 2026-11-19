# Issue 452: Backend test runs print ~450,000 warnings

Issue: https://github.com/hiteshjoshi1/capitalOS_core/issues/452

Part of #431 (review follow-ups).

## Objective
- A backend test run prints (near) zero warnings, so a new one is noticed.
- A warning raised by our own code (`app.*`, `tests.*`) fails the test instead of scrolling past.

## Architecture Decisions
- sqlite3 date/datetime adapters (deprecated in Python 3.12) are registered explicitly in
  `api/tests/conftest.py`, writing the same ISO text as the defaults (`date.isoformat()`,
  `datetime.isoformat(" ")`). No converters: SQLAlchemy doesn't use `detect_types`. Test-only:
  production runs on Postgres.
- `api/pytest.ini` `filterwarnings`: `error` for warnings attributed to `app` / `tests` modules and
  for the two sqlite3 adapter warnings (so the fix can't silently regress); two narrow, commented
  ignores for third-party deprecations whose fix is its own change:
  - Starlette's "use `httpx2` with the TestClient": httpx2 is a new separate client stack (httpx2 +
    httpcore2 + truststore), released almost weekly; the app itself still uses httpx. Not adopted here.
  - pandas' "xlrd engine is deprecated": moving the legacy .xls parsers to calamine needs a new
    dependency (python-calamine) and its own parser tests.
- No dependency change.

## Acceptance Criteria
- [x] Full backend suite passes with the same pass/skip counts as before.
- [x] Warning count near zero (was 453,705).
- [x] Warnings from `app.*` / `tests.*` fail tests.

## How To Test
- `docker compose run --rm --build --no-deps api-dev pytest` and confirm the summary shows
  `1344 passed, 27 skipped` and no warnings.

<!-- IMMUTABLE_PLAN_END -->

## Task Checklist
- [x] Implement scoped code changes
- [x] Add/update tests
- [x] Run deterministic safety gates
- [x] Verify semantic intent is achieved

## Execution Journal (Codex Mutable)
- Current Stage: `pr`
- Workflow Status: `running`
- Provider/Model: `anthropic/claude-opus-5-5`
- Last Updated: `2026-11-19`

Warning inventory before (counted per recorded warning over the full run):

| count | warning |
|---|---|
| 431,642 | DeprecationWarning: default sqlite3 **date** adapter (Python 3.12) |
| 19,160 | DeprecationWarning: default sqlite3 **datetime** adapter |
| 2,871 | jwt InsecureKeyLengthWarning: test HMAC secrets under 32 bytes (18 and 29 bytes) |
| 23 | DeprecationWarning: Starlette TestClient per-request `cookies=` |
| 6 | PydanticDeprecatedSince20: class-based `Config` in `app/schemas` |
| 1 | StarletteDeprecationWarning: use `httpx2` with the TestClient |
| 1 | Pandas4Warning: xlrd engine deprecated (`app/ingestion/parsers/uob_account_xls_v1.py`) |
| 1 | Pandas4Warning: DataFrame from ragged rows (`tests/test_uob_account_parser.py`) |

Fixes: sqlite adapters (conftest); test secret lengthened to 36 bytes, and the one test that signs
with the old 29-byte public secret on purpose silences that warning locally; per-request cookies sent
as a `Cookie` header; `model_config = ConfigDict(...)` in four schema files; the ragged test DataFrame
padded. Starlette httpx2 and pandas xlrd: narrow ignores (above).

## Deterministic Gate Results (Codex Mutable)
- `tests`: pass — `docker compose run --rm --build --no-deps api-dev pytest`: 1344 passed, 27 skipped, 0 warnings
  (before: 1344 passed, 27 skipped, 453,705 warnings).
- `lint`: pass — `ruff check app tests` (the backend part of `make lint`); no web/script files changed.
- `typecheck`: pass — `mypy app`.
- `policy-checks`: a probe test proved a warning raised from `app.*` and from a test module now fails.

## Extra Files Changed (Codex Mutable)
- `api/app/schemas/{account,currency,platform,dashboard}.py` — reason: Pydantic class-based
  `Config` warned from app code, which now fails tests. Same config, new spelling.

## Permanently Failed / Gave Up (Codex Mutable)
- n/a

## Human Action Summary (Codex Mutable)
- Next expected action: review the PR, add to a test-instance batch.
- Open questions:
  - Follow-ups: adopt httpx2 for the TestClient; move .xls parsing off xlrd (calamine);
    the UOB account/credit-card parsers never close their `pd.ExcelFile` (ResourceWarning,
    hidden by Python's default filters, not counted above).

## Automation Log (Mutable)

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
