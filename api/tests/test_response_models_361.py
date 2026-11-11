"""#361 (#130 §5.5): the crypto, ingest, market-data and IBKR Flex GETs are described by
response models, without changing their JSON."""

from datetime import datetime, timezone

import pytest
from pydantic import BaseModel

from app.schemas.common import IsoDateTime

ROUTES = [
    "/crypto/wallets", "/crypto/summary", "/crypto/tokens", "/crypto/token-visibility", "/crypto/allowlist",
    "/crypto/solana/blockhash", "/crypto/price-backfill-plan", "/ingest/jobs", "/ingest/jobs/{job_id}",
    "/market-data/status", "/market-data/runs", "/market-data/unpriced", "/portfolio/ibkr-flex/import-runs",
    "/portfolio/ibkr-flex/reconciliations", "/portfolio/ibkr-flex/data-quality-events",
]


@pytest.mark.parametrize("path", ROUTES)
def test_route_has_a_response_schema(path):
    from app.main import app

    op = app.openapi()["paths"][path]["get"]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema, path  # an empty schema ({}) is what a route without response_model gets


def test_iso_datetime_keeps_isoformat():
    class M(BaseModel):
        t: IsoDateTime

    stamp = datetime(2026, 11, 10, 14, 56, 22, 843825, tzinfo=timezone.utc)
    assert M(t=stamp).model_dump_json() == '{"t":"2026-11-10T14:56:22.843825+00:00"}'


def test_job_detail_has_no_stored_path():
    from app.schemas.ingest import ImportJobDetail

    assert "stored_path" not in ImportJobDetail.model_fields


def test_job_detail_has_no_report_path_but_still_returns_the_report(client, db_engine, tmp_path):
    """#388: report_path (a server file path) leaves GET /ingest/jobs/{id}; the report itself
    is still read through it and returned."""
    import json

    from sqlalchemy import text

    from app.schemas.ingest import ImportJobDetail

    assert "report_path" not in ImportJobDetail.model_fields
    report_file = tmp_path / "93881.json"
    report_file.write_text(json.dumps({"job_id": 93881, "status": "IMPORTED", "counts": {"rows_total": 2}}))
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM import_jobs WHERE id = 93881"))
        conn.execute(text("DELETE FROM accounts WHERE id = 93881"))
        conn.execute(text(
            "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) "
            "VALUES (93881, 'Report Bank', 'DBS', 'BANK', 'SGD', 'SG', 1)"
        ))
        conn.execute(text(
            "INSERT INTO import_jobs (id, account_id, platform, original_filename, stored_path, file_sha256, status, report_path) "
            "VALUES (93881, 93881, 'DBS', 'r.csv', '/tmp/x', 'synthetic', 'IMPORTED', :p)"
        ), {"p": str(report_file)})
    resp = client.get("/ingest/jobs/93881")
    assert resp.status_code == 200
    body = resp.json()
    assert "report_path" not in body["job"]
    assert "stored_path" not in body["job"]
    assert body["report"]["counts"] == {"rows_total": 2}
