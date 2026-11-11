"""Cross-user isolation over every GET route (#154, #130 9.2).

Every GET operation in the app's OpenAPI schema (so a new route is covered the day it is
added) is called as user B twice: before and after user A's data is written. B owns
nothing, so B's responses must not change at all: not a name, not a total, not a count.
Neither user is an admin. The few routes whose answer is the same for every user and may
legitimately change when anybody writes are an explicit allow-list (SHARED_ROUTES, with
the reason); B must still never see one of A's private strings there.

A's data goes through the real write paths where there is one (an IBKR Flex import, the
upload balance adapter, the History backfill), so the check covers the derived tables
too. It runs on SQLite in the default suite and on a migrated Postgres 16 in
`make db-schema-check` (marker `postgres`), where every route's SQL also runs against the
real schema: a route that fails there fails here.

A route with a path parameter is called with A's object (B must get what B got before:
a 404, not A's row). A new path parameter needs a value in PATH_PARAMS; a new required
query parameter one in QUERY_PARAMS. The test says so when one is missing. With the login
bypass off (#154), every GET except PUBLIC_ROUTES must also refuse an anonymous call.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.ingestion.parsers.base import ParseResult
from app.main import app
from app.portfolio.ibkr_flex import run_ibkr_flex_import_from_xml
from app.portfolio.upload_canonical import run_upload_balance_canonical_adapter
from app.valuation_cache import clear_shared_cache
from tests.auth_helpers import auth_headers, ensure_user
from tests.postgres_support import app_on, migrated_database_copy
from tests.valuation_household import FLEX_REPORTS, SGT, flex_xml, freeze_clock

USER_A = 91001
USER_B = 91002
NOW = datetime(2026, 3, 18, 10, 0, tzinfo=SGT)
MONTH = "2026-03"

A_BANK = 91101
A_CARD = 91102
A_BROKER = 91103
A_TXN = 91201
A_JOB = 91301
A_WALLET = "a1540000-0000-4000-8000-0000000000a1"
A_BROKER_ACCOUNT = "U9154001"

# Strings and numbers that exist only in A's rows. B's responses must never contain one.
A_PRIVATE = (
    "SENTINEL-A",  # account, card, wallet, merchant, rule and file names all carry it
    "0xa154a154a154a154a154a154a154a154a154a154",
    A_BROKER_ACCOUNT,
    "91543.21",  # A's bank balance (SGD, so it passes through unconverted)
)

# Values for path parameters: A's objects.
PATH_PARAMS: dict[str, str] = {
    "month": MONTH,
    "transaction_id": str(A_TXN),
    "job_id": str(A_JOB),
}
# Values for query parameters: required ones must be here; optional ones listed here are
# sent too, so the routes look at the month that holds A's data.
QUERY_PARAMS: dict[str, str] = {
    "month": MONTH,
    "base_currency": "SGD",
    # History → Compare (#398): the month before A's to A's month.
    "from": "2026-02",
    "to": MONTH,
}

# Same answer for every user (checked: A and B get identical answers), and it may change
# when anybody writes, so B's before/after comparison doesn't apply.
SHARED_ROUTES: dict[str, str] = {
    "/health": "liveness and migration state, no user data",
    "/platforms": "the shared platform catalogue",
    "/currencies": "the shared currency list",
    "/crypto/allowlist": "the shared token allowlist (admin-maintained)",
    "/market-data/runs": "shared market-data job history (prices are shared data)",
    "/auth/methods": "which sign-in methods are on (server config, no user data)",
    "/operations/backup-status": "the Mac's backup status file (#399): server state, no user data",
    "/settings/facts": "snapshot day, default upload cadence, base currencies (#399): server config",
}
# Not called, with the reason.
SKIPPED_ROUTES: dict[str, str] = {
    "/crypto/solana/blockhash": "relays a public Solana RPC call over the network; reads no stored data",
    "/auth/google/start": "redirects to Google to sign in (#358); reads no stored data",
    "/auth/google/callback": "Google's redirect back with a one-time code (#358); signs in, reads no user data",
}
# Answer without a login, with the reason. Every other GET must refuse an anonymous call.
PUBLIC_ROUTES: dict[str, str] = {
    "/health": "liveness probe for Docker and make deploy",
    "/auth/methods": "the sign-in page asks which methods are on before anyone is signed in (#358)",
    "/auth/google/start": "starts Sign in with Google, before anyone is signed in (#358)",
    "/auth/google/callback": "where Google sends the browser back to finish signing in (#358)",
}
# Positive control: A's own answer differs from B's here, so A's data reaches these routes.
A_SEES_OWN_DATA = (
    "/accounts",
    "/alerts/notifications",
    "/alerts/notifications/count",
    "/alerts/upload-reminders",
    "/alerts/upload-reminders/count",
    "/categories/resolve/{transaction_id}",
    "/categories/rules",
    "/crypto/stablecoins",
    "/crypto/summary",
    "/crypto/tokens",
    "/crypto/wallets",
    "/dashboard/bootstrap",
    "/dashboard/bridge",
    "/dashboard/cash-deposits",
    "/dashboard/data-hub-summary",
    "/dashboard/net-worth-since-update",
    "/dashboard/net-worth-timeline",
    "/dashboard/platform-allocation",
    "/dashboard/risk-summary",
    "/dashboard/source-freshness",
    "/dashboard/stock-exposure",
    "/dashboard/stock-holdings",
    "/dashboard/summary",
    "/dividends/expected/overview",
    "/ingest/jobs",
    "/ingest/jobs/{job_id}",
    "/market-data/status",
    "/portfolio/ibkr-flex/import-runs",
    "/portfolio/ibkr-flex/reconciliations",
    "/spending/cash-flow-detail",
    "/spending/cash-flow-trend",
    "/spending/credit-card-analytics",
    "/spending/credit-card-transactions",
    "/spending/credit-cards",
    "/spending/summary",
)


def _get_routes() -> list[tuple[str, list[dict[str, Any]]]]:
    paths = app.openapi()["paths"]
    return sorted((path, ops["get"].get("parameters", [])) for path, ops in paths.items() if "get" in ops)


def _url(path: str, parameters: list[dict[str, Any]]) -> str:
    url = path
    query = []
    for param in parameters:
        name, where = param["name"], param["in"]
        if where == "path":
            assert name in PATH_PARAMS, f"{path}: add a value for path parameter '{name}' to PATH_PARAMS"
            url = url.replace("{" + name + "}", PATH_PARAMS[name])
        elif where == "query":
            if name in QUERY_PARAMS:
                query.append(f"{name}={QUERY_PARAMS[name]}")
            else:
                assert not param.get("required"), f"{path}: add a value for query parameter '{name}' to QUERY_PARAMS"
    return url + ("?" + "&".join(query) if query else "")


def _call_all(client: TestClient, user_id: int) -> dict[str, tuple[int, str]]:
    responses = {}
    for path, parameters in _get_routes():
        if path in SKIPPED_ROUTES:
            continue
        clear_shared_cache()
        resp = client.get(_url(path, parameters), headers=auth_headers(user_id))
        responses[path] = (resp.status_code, resp.text)
    return responses


def _comparable(body: str) -> Any:
    try:
        return json.loads(body)
    except ValueError:
        return body


# ─── A's data ────────────────────────────────────────────────────────────────


def _seed_shared(conn) -> None:
    """Reference rows the migrations seed on Postgres; the SQLite schema starts empty."""
    for code, name, kind, country in (("DBS", "DBS Bank", "BANK", "SG"), ("IBKR", "Interactive Brokers", "BROKER", "US")):
        conn.execute(
            text(
                "INSERT INTO platforms (code, name, platform_type, country) "
                "SELECT :code, :name, :kind, :country WHERE NOT EXISTS (SELECT 1 FROM platforms WHERE code = :code)"
            ),
            {"code": code, "name": name, "kind": kind, "country": country},
        )
    conn.execute(
        text(
            "INSERT INTO category_taxonomy (code, name) "
            "SELECT 'dining', 'Dining' WHERE NOT EXISTS (SELECT 1 FROM category_taxonomy WHERE code = 'dining')"
        )
    )


def _seed_user_a_rows(conn) -> None:
    platform = {
        code: conn.execute(text("SELECT id FROM platforms WHERE code = :c"), {"c": code}).scalar_one()
        for code in ("DBS", "IBKR")
    }
    conn.execute(
        text(
            "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country, platform_id) VALUES "
            "(:bank, 'SENTINEL-A Savings', 'DBS', :a, 'BANK', 'SGD', 'SG', :dbs), "
            "(:card, 'SENTINEL-A Card', 'DBS', :a, 'CREDIT_CARD', 'SGD', 'SG', :dbs), "
            "(:broker, 'SENTINEL-A Broker', 'IBKR', :a, 'BROKER', 'USD', 'US', :ibkr)"
        ),
        {"bank": A_BANK, "card": A_CARD, "broker": A_BROKER, "a": USER_A, "dbs": platform["DBS"], "ibkr": platform["IBKR"]},
    )
    conn.execute(
        text(
            "INSERT INTO credit_card_accounts (account_id, card_name, issuer, credit_limit, available_limit, "
            "statement_day, due_day) VALUES (:card, 'SENTINEL-A Card Product', 'DBS', 8000, 6100, 20, 5)"
        ),
        {"card": A_CARD},
    )
    conn.execute(
        text(
            "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes) VALUES "
            "(:t1, '2026-03-05 12:00:00+00:00', :card, -1900, 'EXPENSE', 'SGD', 'Dining', 'SENTINEL-A Merchant', 'SENTINEL-A note'), "
            "(:t2, '2026-03-02 12:00:00+00:00', :bank, 7300, 'INCOME', 'SGD', 'Salary', 'SENTINEL-A Employer', NULL), "
            "(:t3, '2026-02-10 12:00:00+00:00', :bank, -2600, 'EXPENSE', 'SGD', 'Rent', 'SENTINEL-A Landlord', NULL)"
        ),
        {"t1": A_TXN, "t2": A_TXN + 1, "t3": A_TXN + 2, "card": A_CARD, "bank": A_BANK},
    )
    # An upload from January, so it shows as a stale-upload reminder. On SQLite the timestamps
    # stay NULL: it would hand a raw timestamp back as text where the route expects a datetime.
    uploaded_at = None if conn.dialect.name == "sqlite" else datetime(2026, 1, 10, 8, 0, tzinfo=SGT)
    conn.execute(
        text(
            "INSERT INTO import_jobs (id, account_id, platform, original_filename, stored_path, file_sha256, status, "
            "created_at, updated_at) VALUES (:job, :bank, 'DBS', 'SENTINEL-A-statement.csv', "
            "'/tmp/capitalos-test/SENTINEL-A-statement.csv', 'a154', 'IMPORTED', :at, :at)"
        ),
        {"job": A_JOB, "bank": A_BANK, "at": uploaded_at},
    )
    conn.execute(
        text(
            "INSERT INTO category_rules (name, priority, merchant_pattern, target_category_id, active, user_id) "
            "SELECT 'SENTINEL-A rule', 10, 'SENTINEL-A Merchant', id, TRUE, :a FROM category_taxonomy WHERE code = 'dining'"
        ),
        {"a": USER_A},
    )
    conn.execute(
        text(
            "INSERT INTO crypto_wallets (id, user_id, chain_type, chain, address, label, status, created_at) "
            "VALUES (:w, :a, 'evm', 'ethereum', :addr, 'SENTINEL-A wallet', 'active', '2026-01-01 00:00:00+00:00')"
        ),
        {"w": A_WALLET, "a": USER_A, "addr": A_PRIVATE[1]},
    )
    snapshot_id = conn.execute(
        text(
            "INSERT INTO crypto_wallet_snapshots (wallet_id, as_of_date, fetched_at, total_usd) "
            "VALUES (:w, '2026-03-15', '2026-03-15 12:00:00+00:00', 4321.5) RETURNING id"
        ),
        {"w": A_WALLET},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO crypto_wallet_snapshot_items (snapshot_id, chain_type, chain, asset_kind, symbol, "
            "normalized_amount, price_usd, value_usd, price_source) VALUES "
            "(:s, 'evm', 'ethereum', 'native', 'ETH', 1.2, 3001.25, 3601.5, 'synthetic'), "
            "(:s, 'evm', 'ethereum', 'erc20', 'USDC', 720, 1, 720, 'synthetic')"
        ),
        {"s": snapshot_id},
    )


def _seed_user_a(engine: Engine, client: TestClient) -> None:
    with engine.begin() as conn:
        _seed_user_a_rows(conn)
    with Session(bind=engine) as db:
        run_upload_balance_canonical_adapter(
            db,
            account_id=A_BANK,
            import_job_id=None,
            parse_result=ParseResult(
                transactions=[],
                positions=[{"asset_class": "CASH", "currency": "SGD", "quantity": 91543.21}],
                section_counts={},
                parser_meta={"statement_period_end": "2026-03-12"},
            ),
        )
        db.commit()
    with Session(bind=engine) as db:
        run_ibkr_flex_import_from_xml(
            db,
            current_user_id=USER_A,
            legacy_account_id=A_BROKER,
            xml_text=flex_xml(FLEX_REPORTS[2]).replace("U0000142", A_BROKER_ACCOUNT),
        )
        db.commit()
    # History rollups for A (the History page's stored table).
    clear_shared_cache()
    resp = client.post("/dashboard/net-worth-timeline/backfill?months=3&base_currency=SGD", headers=auth_headers(USER_A))
    assert resp.status_code == 200, resp.text


# ─── The test ────────────────────────────────────────────────────────────────


def _run_isolation_check(engine: Engine, monkeypatch) -> None:
    freeze_clock(monkeypatch, NOW)
    with engine.begin() as conn:
        _seed_shared(conn)
    ensure_user(engine, USER_A, "isolation-a")
    ensure_user(engine, USER_B, "isolation-b")
    client = TestClient(app)

    before = _call_all(client, USER_B)
    _seed_user_a(engine, client)
    after = _call_all(client, USER_B)
    as_a = _call_all(client, USER_A)

    crashed = sorted(f"{path} -> {status} as {who}" for who, calls in (("A", as_a), ("B", after))
                     for path, (status, _body) in calls.items() if status >= 500)
    assert crashed == [], "routes that fail outright:\n" + "\n".join(crashed)

    leaked = sorted(f"{path}: {token!r}" for path, (_status, body) in after.items() for token in A_PRIVATE if token in body)
    assert leaked == [], "user B sees user A's data:\n" + "\n".join(leaked)

    changed = sorted(
        path for path in after
        if path not in SHARED_ROUTES and (before[path][0], _comparable(before[path][1])) != (after[path][0], _comparable(after[path][1]))
    )
    assert changed == [], (
        "user B's answer changed when user A's data was written (a missing user scope, or a shared "
        "route that needs a reason in SHARED_ROUTES):\n"
        + "\n".join(f"{path}\n  before: {before[path][1][:300]}\n  after:  {after[path][1][:300]}" for path in changed)
    )

    not_shared = [path for path in SHARED_ROUTES if path in after and after[path] != as_a[path]]
    assert not_shared == [], f"SHARED_ROUTES answer users differently, so they are not shared: {not_shared}"

    same_for_a = [path for path in A_SEES_OWN_DATA if as_a[path] == after[path]]
    assert same_for_a == [], (
        "user A gets the same answer as user B here, so A's seeded data no longer reaches these routes "
        "and the check above proves nothing for them:\n" + "\n".join(f"{path}: {as_a[path][1][:300]}" for path in same_for_a)
    )


def test_every_get_route_is_called_or_explicitly_skipped():
    routes = {path for path, _ in _get_routes()}
    assert set(SKIPPED_ROUTES) <= routes, f"stale SKIPPED_ROUTES entries: {set(SKIPPED_ROUTES) - routes}"
    assert set(SHARED_ROUTES) <= routes, f"stale SHARED_ROUTES entries: {set(SHARED_ROUTES) - routes}"
    assert set(A_SEES_OWN_DATA) <= routes
    for path, parameters in _get_routes():
        if path not in SKIPPED_ROUTES:
            _url(path, parameters)  # fails when a parameter has no value


def test_every_get_route_needs_a_login(anon_client):
    open_routes = []
    for path, parameters in _get_routes():
        if path in PUBLIC_ROUTES:
            continue
        status = anon_client.get(_url(path, parameters)).status_code
        if status != 401:
            open_routes.append(f"{path} -> {status}")
    assert open_routes == [], "GET routes that answer without a login (add a reason to PUBLIC_ROUTES if intended):\n" + "\n".join(open_routes)


def test_user_b_never_sees_user_a_data(db_engine, monkeypatch):
    _run_isolation_check(db_engine, monkeypatch)


@pytest.mark.postgres
def test_user_b_never_sees_user_a_data_on_postgres(monkeypatch):
    with migrated_database_copy() as engine, app_on(engine):
        _run_isolation_check(engine, monkeypatch)
