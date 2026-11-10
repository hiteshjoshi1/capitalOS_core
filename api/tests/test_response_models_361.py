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
