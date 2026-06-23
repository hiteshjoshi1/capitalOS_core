from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.portfolio.ibkr_flex import (
    IbkrFlexClient,
    IbkrFlexImportError,
    IbkrFlexImportInProgress,
    IbkrFlexResponseError,
    IbkrFlexStatementNotReady,
    is_ibkr_flex_cutover_active,
    run_ibkr_flex_import_from_xml,
)


def _seed_ibkr_account(db_engine, account_id: int = 300) -> None:
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        db.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) "
                "VALUES (30, 'IBKR', 'Interactive Brokers', 'BROKER', 'US')"
            )
        )
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) "
                "VALUES (:id, 'IBKR Flex Test', 'IBKR', 'BROKER', 'SGD', 'SG', 30)"
            ),
            {"id": account_id},
        )
        db.commit()
    finally:
        db.close()


def _valid_flex_xml() -> str:
    return """
    <FlexQueryResponse>
      <FlexStatements count="1">
        <FlexStatement accountId="U1234567" fromDate="2026-02-20" toDate="2026-02-20" whenGenerated="2026-02-21;08:00:00">
          <EquitySummaryInBase>
            <EquitySummaryByReportDateInBase
              reportDate="2026-02-20"
              cash="167.50"
              stock="1350.00"
              options="0"
              funds="0"
              bonds="0"
              interestAccruals="1.00"
              dividendAccruals="2.50"
              total="1521.00" />
          </EquitySummaryInBase>
          <CashReport>
            <CashReportCurrency currency="SGD" toDate="2026-02-20" startingCash="90.00" endingCash="100.00" endingSettledCash="100.00" />
            <CashReportCurrency currency="USD" toDate="2026-02-20" startingCash="40.00" endingCash="50.00" endingSettledCash="50.00" brokerInterestPaidReceivedMTD="1.00" dividendsMTD="2.50" />
            <CashReportCurrency currency="BASE_SUMMARY" toDate="2026-02-20" endingCash="167.50" />
          </CashReport>
          <OpenPositions>
            <OpenPosition
              reportDate="2026-02-20"
              conid="265598"
              symbol="AAPL"
              description="APPLE INC"
              assetCategory="STK"
              listingExchange="NASDAQ"
              currency="USD"
              position="10"
              markPrice="100.00"
              positionValue="1000.00"
              positionValueInBase="1350.00"
              costBasisMoney="900.00"
              costBasisMoneyInBase="1215.00"
              fxRateToBase="1.35" />
          </OpenPositions>
          <ConversionRates>
            <ConversionRate reportDate="2026-02-20" fromCurrency="USD" toCurrency="SGD" rate="1.35" />
          </ConversionRates>
          <StmtFunds>
            <StmtFunds date="2026-02-20" currency="USD" amount="2.50" activityCode="Div" activityDescription="Dividend" transactionID="D1" />
          </StmtFunds>
          <Trades>
            <Trade
              tradeDate="2026-02-20"
              settleDateTarget="2026-02-22"
              conid="265598"
              symbol="AAPL"
              description="APPLE INC"
              assetCategory="STK"
              listingExchange="NASDAQ"
              currency="USD"
              buySell="BUY"
              quantity="1"
              tradePrice="100.00"
              proceeds="-100.00"
              ibCommission="-1.00"
              ibExecID="E1" />
          </Trades>
          <CorporateActions>
            <CorporateAction
              date="2026-02-20"
              conid="265598"
              symbol="AAPL"
              description="APPLE INC"
              assetCategory="STK"
              listingExchange="NASDAQ"
              currency="USD"
              type="DIVIDEND"
              quantity="0"
              amount="2.50"
              transactionID="CA1" />
          </CorporateActions>
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>
    """


def _missing_fx_xml() -> str:
    return """
    <FlexQueryResponse>
      <FlexStatements count="1">
        <FlexStatement accountId="U1234567" fromDate="2026-02-20" toDate="2026-02-20" baseCurrency="SGD">
          <EquitySummaryInBase>
            <EquitySummaryByReportDateInBase reportDate="2026-02-20" cash="10.00" stock="0" total="10.00" />
          </EquitySummaryInBase>
          <CashReport>
            <CashReportCurrency currency="USD" toDate="2026-02-20" endingCash="10.00" />
          </CashReport>
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>
    """


def _nonzero_stock_empty_positions_xml() -> str:
    return """
    <FlexQueryResponse>
      <FlexStatements count="1">
        <FlexStatement accountId="U1234567" fromDate="2026-02-20" toDate="2026-02-20">
          <EquitySummaryInBase>
            <EquitySummaryByReportDateInBase reportDate="2026-02-20" cash="0" stock="100.00" total="100.00" />
          </EquitySummaryInBase>
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>
    """


def test_ibkr_flex_client_accepts_existing_env_aliases(monkeypatch):
    monkeypatch.setenv("IBKR_FLEX_TOKEN", "token")
    monkeypatch.delenv("IBKR_TOKEN", raising=False)
    monkeypatch.delenv("IBKR_FLEX_QUERY_ID", raising=False)
    monkeypatch.setenv("IBKR_QUERY_ID", "query-id")
    monkeypatch.delenv("IBKR_FLEX_BASE_URL", raising=False)
    monkeypatch.setenv("IBKR_FLEX_BASE", "https://example.test/flex")
    monkeypatch.setenv("IBKR_USER_AGENT", "CapitalOS Test Agent")

    client = IbkrFlexClient.from_env()

    assert client._query_id == "query-id"
    assert client._base_url == "https://example.test/flex"
    assert client._request_headers() == {"User-Agent": "CapitalOS Test Agent"}


def test_ibkr_flex_client_accepts_ibkr_token_alias(monkeypatch):
    monkeypatch.delenv("IBKR_FLEX_TOKEN", raising=False)
    monkeypatch.setenv("IBKR_TOKEN", "token-alias")
    monkeypatch.delenv("IBKR_FLEX_QUERY_ID", raising=False)
    monkeypatch.setenv("IBKR_QUERY_ID", "query-id")
    monkeypatch.delenv("IBKR_FLEX_BASE_URL", raising=False)
    monkeypatch.delenv("IBKR_FLEX_BASE", raising=False)

    client = IbkrFlexClient.from_env()

    assert client._token == "token-alias"


def test_ibkr_flex_client_prefers_explicit_env_names(monkeypatch):
    monkeypatch.setenv("IBKR_FLEX_TOKEN", "token")
    monkeypatch.setenv("IBKR_TOKEN", "legacy-token")
    monkeypatch.setenv("IBKR_FLEX_QUERY_ID", "explicit-query-id")
    monkeypatch.setenv("IBKR_QUERY_ID", "legacy-query-id")
    monkeypatch.setenv("IBKR_FLEX_BASE_URL", "https://explicit.example.test/flex")
    monkeypatch.setenv("IBKR_FLEX_BASE", "https://legacy.example.test/flex")

    client = IbkrFlexClient.from_env()

    assert client._query_id == "explicit-query-id"
    assert client._token == "token"
    assert client._base_url == "https://explicit.example.test/flex"


def test_ibkr_flex_client_defaults_to_account_management_flex_web_service(monkeypatch):
    monkeypatch.setenv("IBKR_FLEX_TOKEN", "token")
    monkeypatch.setenv("IBKR_QUERY_ID", "query-id")
    monkeypatch.delenv("IBKR_FLEX_QUERY_ID", raising=False)
    monkeypatch.delenv("IBKR_FLEX_BASE_URL", raising=False)
    monkeypatch.delenv("IBKR_FLEX_BASE", raising=False)
    monkeypatch.delenv("IBKR_USER_AGENT", raising=False)

    client = IbkrFlexClient.from_env()

    assert client._base_url == "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
    assert client._request_headers() == {"User-Agent": "curl/8.0"}
    assert client._service_url("send") == "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
    assert client._service_url("get") == "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"


def test_ibkr_flex_client_uses_flex_web_service_endpoint_shape():
    client = IbkrFlexClient(
        token="token",
        query_id="query-id",
        base_url="https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService",
    )

    assert client._service_url("send") == "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
    assert client._service_url("get") == "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"


def test_ibkr_flex_client_uses_legacy_servlet_endpoint_shape():
    client = IbkrFlexClient(
        token="token",
        query_id="query-id",
        base_url="https://gdcdyn.interactivebrokers.com/Universal/servlet",
    )

    assert client._service_url("send") == "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest"
    assert client._service_url("get") == "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement"


def test_ibkr_flex_client_omits_request_headers_when_user_agent_not_configured():
    client = IbkrFlexClient(token="token", query_id="query-id")

    assert client._request_headers() is None


def test_ibkr_flex_client_parses_statement_generation_in_progress_xml():
    xml_text = """
    <FlexStatementResponse>
      <Status>Fail</Status>
      <ErrorCode>1019</ErrorCode>
      <ErrorMessage>Statement generation in progress. Please try again shortly.</ErrorMessage>
    </FlexStatementResponse>
    """

    with pytest.raises(IbkrFlexStatementNotReady):
        IbkrFlexClient._raise_if_not_ready(xml_text)


def test_ibkr_flex_client_retries_not_ready_with_bounded_exponential_backoff(monkeypatch):
    class EventuallyReadyClient(IbkrFlexClient):
        def __init__(self) -> None:
            super().__init__(token="token", query_id="query-id")
            self.get_calls = 0

        def send_request(self) -> str:
            return "reference-code"

        def get_statement(self, reference_code: str) -> str:
            self.get_calls += 1
            if self.get_calls <= 3:
                raise IbkrFlexStatementNotReady("IBKR Flex statement is still generating")
            return "<FlexQueryResponse />"

    sleeps: list[float] = []
    monkeypatch.setattr("app.portfolio.ibkr_flex.time.sleep", sleeps.append)
    client = EventuallyReadyClient()

    reference_code, xml_text = client.fetch_statement(
        max_attempts=5,
        initial_backoff_seconds=2,
        max_backoff_seconds=5,
    )

    assert reference_code == "reference-code"
    assert xml_text == "<FlexQueryResponse />"
    assert client.get_calls == 4
    assert sleeps == [2, 4, 5]


def test_ibkr_flex_client_does_not_retry_permanent_response_errors(monkeypatch):
    class FailingClient(IbkrFlexClient):
        def __init__(self) -> None:
            super().__init__(token="token", query_id="query-id")
            self.get_calls = 0

        def send_request(self) -> str:
            return "reference-code"

        def get_statement(self, reference_code: str) -> str:
            self.get_calls += 1
            raise IbkrFlexResponseError("IBKR Flex GetStatement did not return success: 1018 bad token")

    sleeps: list[float] = []
    monkeypatch.setattr("app.portfolio.ibkr_flex.time.sleep", sleeps.append)
    client = FailingClient()

    with pytest.raises(IbkrFlexResponseError):
        client.fetch_statement(max_attempts=5)

    assert client.get_calls == 1
    assert sleeps == []


def test_ibkr_flex_import_is_idempotent_and_preserves_lineage(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_ibkr_account(db_engine)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        first = run_ibkr_flex_import_from_xml(
            db,
            current_user_id=1,
            legacy_account_id=300,
            xml_text=_valid_flex_xml(),
            cutover_date=date(2026, 2, 1),
            reference_code="REF1",
        )
        second = run_ibkr_flex_import_from_xml(
            db,
            current_user_id=1,
            legacy_account_id=300,
            xml_text=_valid_flex_xml(),
            cutover_date=date(2026, 2, 1),
            reference_code="REF1",
        )

        assert first["status"] == "IMPORTED"
        assert second["status"] == "IMPORTED"
        assert is_ibkr_flex_cutover_active(db, 300, on_date=date(2026, 2, 20))
        assert db.execute(text("SELECT COUNT(*) FROM portfolio_nav_snapshots")).scalar() == 1
        assert db.execute(text("SELECT COUNT(*) FROM portfolio_position_snapshots")).scalar() == 1
        assert db.execute(text("SELECT COUNT(*) FROM portfolio_cash_balance_snapshots")).scalar() == 2
        assert db.execute(text("SELECT COUNT(*) FROM portfolio_reconciliations")).scalar() == 1
        assert db.execute(text("SELECT COUNT(*) FROM portfolio_cash_ledger_entries")).scalar() == 1
        assert db.execute(text("SELECT COUNT(*) FROM portfolio_trades")).scalar() == 1
        assert db.execute(text("SELECT COUNT(*) FROM portfolio_corporate_action_events")).scalar() == 1
        assert db.execute(text("SELECT COUNT(*) FROM raw_broker_documents")).scalar() == 2
        raw_path = db.execute(text("SELECT storage_path FROM raw_broker_documents ORDER BY id LIMIT 1")).scalar()
        assert raw_path
        assert (tmp_path / "broker_raw" / "ibkr_flex").exists()
        assert db.execute(text("SELECT COUNT(*) FROM portfolio_report_metrics WHERE metric_code = 'ending_cash'")).scalar() >= 2
    finally:
        db.close()


def test_ibkr_flex_dashboard_uses_canonical_nav_and_excludes_legacy_positions(client, db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_ibkr_account(db_engine)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        db.execute(text("INSERT INTO assets (id, symbol, name, asset_class, quote_currency) VALUES (900, 'LEGACY', 'Legacy', 'STOCK', 'SGD')"))
        db.execute(
            text(
                "INSERT INTO positions (id, account_id, asset_id, as_of, quantity, avg_cost, cost_basis_base) "
                "VALUES (900, 300, 900, '2026-02-06T00:00:00+00:00', 1, 1, 999999)"
            )
        )
        run_ibkr_flex_import_from_xml(
            db,
            current_user_id=1,
            legacy_account_id=300,
            xml_text=_valid_flex_xml(),
            cutover_date=date(2026, 2, 1),
        )
    finally:
        db.close()

    response = client.get("/dashboard/summary?month=2026-02&base_currency=SGD")
    assert response.status_code == 200
    payload = response.json()
    assert payload["net_worth"]["total"] == pytest.approx(1521.0)
    assert payload["net_worth"]["cash"] == pytest.approx(167.5)

    allocation_response = client.get("/dashboard/platform-allocation?month=2026-02&base_currency=SGD")
    assert allocation_response.status_code == 200
    allocation = allocation_response.json()
    assert allocation["total"] == pytest.approx(1521.0)
    assert allocation["items"] == [
        {
            "platform": "IBKR",
            "platform_type": "BROKER",
            "country": "US",
            "value": 1521.0,
            "percent": 100.0,
        }
    ]

    stock_response = client.get("/dashboard/stock-holdings?month=2026-02&base_currency=SGD")
    assert stock_response.status_code == 200
    stock_payload = stock_response.json()
    assert stock_payload["stock_current_total"] == pytest.approx(1353.5)
    assert stock_payload["platform_breakdown"] == [
        {
            "key": "IBKR",
            "current_value": 1353.5,
            "snapshot_value": 1353.5,
            "delta_abs": 0.0,
            "delta_pct": 0.0,
            "percent": 100.0,
        }
    ]


def test_ibkr_flex_missing_fx_fails_without_fake_valuation(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_ibkr_account(db_engine)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        with pytest.raises(IbkrFlexImportError) as exc:
            run_ibkr_flex_import_from_xml(
                db,
                current_user_id=1,
                legacy_account_id=300,
                xml_text=_missing_fx_xml(),
                cutover_date=date(2026, 2, 1),
            )
        assert exc.value.code == "missing_fx_rate"
        assert db.execute(text("SELECT status FROM broker_import_runs ORDER BY id DESC LIMIT 1")).scalar() == "failed"
        assert db.execute(text("SELECT COUNT(*) FROM portfolio_nav_snapshots")).scalar() == 0
        assert db.execute(text("SELECT event_code FROM portfolio_data_quality_events ORDER BY id DESC LIMIT 1")).scalar() == "missing_fx_rate"
    finally:
        db.close()


def test_ibkr_flex_nonzero_stock_nav_without_positions_fails_safely(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_ibkr_account(db_engine)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        with pytest.raises(IbkrFlexImportError) as exc:
            run_ibkr_flex_import_from_xml(
                db,
                current_user_id=1,
                legacy_account_id=300,
                xml_text=_nonzero_stock_empty_positions_xml(),
                cutover_date=date(2026, 2, 1),
            )
        assert exc.value.code == "empty_open_positions_with_stock_nav"
        assert db.execute(text("SELECT COUNT(*) FROM portfolio_nav_snapshots")).scalar() == 0
    finally:
        db.close()


def test_ibkr_flex_lock_prevents_overlapping_successful_imports(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_ibkr_account(db_engine)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        run_ibkr_flex_import_from_xml(
            db,
            current_user_id=1,
            legacy_account_id=300,
            xml_text=_valid_flex_xml(),
            cutover_date=date(2026, 2, 1),
        )
        broker_account_id = db.execute(text("SELECT id FROM broker_accounts LIMIT 1")).scalar()
        db.execute(
            text(
                "INSERT INTO portfolio_import_locks (broker_account_id, source_type, lock_owner, locked_at) "
                "VALUES (:broker_account_id, 'ibkr_flex_daily', 'test-lock', CURRENT_TIMESTAMP)"
            ),
            {"broker_account_id": broker_account_id},
        )
        db.commit()
        with pytest.raises(IbkrFlexImportInProgress):
            run_ibkr_flex_import_from_xml(
                db,
                current_user_id=1,
                legacy_account_id=300,
                xml_text=_valid_flex_xml(),
                cutover_date=date(2026, 2, 1),
            )
        assert db.execute(text("SELECT COUNT(*) FROM broker_import_runs WHERE status = 'completed'")).scalar() == 1
    finally:
        db.close()


def test_manual_ibkr_upload_rejected_after_flex_cutover(client, db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_ibkr_account(db_engine)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        run_ibkr_flex_import_from_xml(
            db,
            current_user_id=1,
            legacy_account_id=300,
            xml_text=_valid_flex_xml(),
            cutover_date=date(2026, 2, 1),
        )
    finally:
        db.close()

    fixture = tmp_path / "ibkr.csv"
    fixture.write_text("Symbol,Quantity\nAAPL,1\n", encoding="utf-8")
    with fixture.open("rb") as fh:
        response = client.post(
            "/ingest/ibkr?account_id=300",
            files={"file": ("ibkr.csv", fh, "text/csv")},
        )
    assert response.status_code == 409
