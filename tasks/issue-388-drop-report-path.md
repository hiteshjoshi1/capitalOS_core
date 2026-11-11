# Issue #388: drop report_path from GET /ingest/jobs/{id}

## Goal
Follow-up to #361 (D-99): `report_path`, the server path of a job's report file, leaves the job
detail response like `stored_path` did. The report itself is still returned as `report`.

## Checked
Nothing in web/ (only the TS type and test mocks), scripts, orchestration or the MCP role reads it
from the API; the database column stays (the API reads the report file through it).

## Change
- `api/app/routers/ingest.py`, `api/app/schemas/ingest.py`: field removed.
- `web/src/lib/api.ts`, `web/src/__tests__/Ingest.test.tsx`: type and mocks.
- `docs/decisions.md`: D-99 extended.

## Tests
`api/tests/test_response_models_361.py`: the model has no `report_path`, and the endpoint returns
the report without it.
