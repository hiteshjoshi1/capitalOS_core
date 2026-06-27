from __future__ import annotations

import hashlib
import os
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

PARSER_VERSION = "ibkr_flex_v1"
SOURCE_TYPE = "ibkr_flex_daily"
PLATFORM_CODE = "IBKR"
ALL_FACT_SCOPE = "all"
DEFAULT_IBKR_FLEX_BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
DEFAULT_IBKR_USER_AGENT = "curl/8.0"


class IbkrFlexError(Exception):
    """Base error for IBKR Flex ingestion."""


class IbkrFlexConfigError(IbkrFlexError):
    pass


class IbkrFlexImportInProgress(IbkrFlexError):
    pass


class IbkrFlexResponseError(IbkrFlexError):
    pass


class IbkrFlexStatementNotReady(IbkrFlexResponseError):
    pass


class IbkrFlexImportError(IbkrFlexError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _first_env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def _bounded_exponential_backoff_seconds(attempt: int, initial_seconds: float, max_seconds: float) -> float:
    initial = max(0.0, initial_seconds)
    maximum = max(0.0, max_seconds)
    return min(maximum, initial * (2 ** max(0, attempt - 1)))


@dataclass(frozen=True)
class FlexNavSnapshot:
    report_date: date
    base_currency: str
    cash_base: Decimal
    stock_base: Decimal
    options_base: Decimal
    funds_base: Decimal
    bonds_base: Decimal
    interest_accrual_base: Decimal
    dividend_accrual_base: Decimal
    total_nav_base: Decimal


@dataclass(frozen=True)
class FlexCashBalance:
    report_date: date
    currency: str
    cash_balance: Decimal
    fx_rate_to_base: Decimal

    @property
    def cash_balance_base(self) -> Decimal:
        return self.cash_balance * self.fx_rate_to_base


@dataclass(frozen=True)
class FlexPosition:
    report_date: date
    broker_instrument_id: str
    symbol: str | None
    description: str | None
    security_type: str | None
    listing_exchange: str | None
    currency: str
    quantity: Decimal
    market_price: Decimal | None
    market_value_local: Decimal
    market_value_base: Decimal
    cost_basis_local: Decimal | None
    cost_basis_base: Decimal | None
    fx_rate_to_base: Decimal


@dataclass(frozen=True)
class FlexFxRate:
    report_date: date
    from_currency: str
    to_currency: str
    rate: Decimal


@dataclass(frozen=True)
class FlexCashLedgerEntry:
    activity_date: date
    currency: str
    amount: Decimal
    activity_code: str | None
    description: str | None
    broker_activity_id: str | None


@dataclass(frozen=True)
class FlexTrade:
    trade_date: date
    settle_date: date | None
    broker_instrument_id: str | None
    symbol: str | None
    description: str | None
    security_type: str | None
    listing_exchange: str | None
    currency: str | None
    side: str | None
    quantity: Decimal | None
    price: Decimal | None
    proceeds: Decimal | None
    commission: Decimal | None
    broker_execution_id: str | None


@dataclass(frozen=True)
class FlexCorporateAction:
    action_date: date
    broker_instrument_id: str | None
    symbol: str | None
    description: str | None
    security_type: str | None
    listing_exchange: str | None
    action_type: str | None
    quantity: Decimal | None
    cash_amount: Decimal | None
    currency: str | None
    broker_action_id: str | None


@dataclass(frozen=True)
class FlexReportMetric:
    report_date: date
    report_section: str
    metric_code: str
    currency: str | None
    amount: Decimal


@dataclass(frozen=True)
class FlexStatement:
    broker_account_id: str
    report_date_from: date
    report_date_to: date
    base_currency: str
    generated_at: datetime | None
    nav_snapshots: list[FlexNavSnapshot] = field(default_factory=list)
    cash_balances: list[FlexCashBalance] = field(default_factory=list)
    positions: list[FlexPosition] = field(default_factory=list)
    fx_rates: list[FlexFxRate] = field(default_factory=list)
    cash_ledger_entries: list[FlexCashLedgerEntry] = field(default_factory=list)
    trades: list[FlexTrade] = field(default_factory=list)
    corporate_actions: list[FlexCorporateAction] = field(default_factory=list)
    report_metrics: list[FlexReportMetric] = field(default_factory=list)
    data_quality_errors: list[tuple[str, str]] = field(default_factory=list)


def _attr(element: ET.Element, *names: str) -> str | None:
    lower_map = {k.lower(): v for k, v in element.attrib.items()}
    for name in names:
        value = element.attrib.get(name)
        if value is not None:
            return value
        value = lower_map.get(name.lower())
        if value is not None:
            return value
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _iter(root: ET.Element, name: str) -> list[ET.Element]:
    return [element for element in root.iter() if _local_name(element.tag) == name]


def _first(root: ET.Element, *names: str) -> ET.Element | None:
    wanted = set(names)
    for element in root.iter():
        if _local_name(element.tag) in wanted:
            return element
    return None


def _decimal(value: str | None, default: Decimal | None = None) -> Decimal | None:
    if value is None:
        return default
    cleaned = value.strip().replace(",", "")
    if cleaned == "" or cleaned.lower() in {"null", "none", "nan"}:
        return default
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return default


def _required_decimal(value: str | None, field_name: str) -> Decimal:
    parsed = _decimal(value)
    if parsed is None:
        raise IbkrFlexImportError("parse_failed", f"Missing or invalid decimal field: {field_name}")
    return parsed


def _date(value: str | None, default: date | None = None) -> date | None:
    if value is None or not value.strip():
        return default
    cleaned = value.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%d-%b-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(cleaned).date()
    except ValueError:
        return default


def _datetime(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    for fmt in ("%Y-%m-%d;%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d;%H:%M:%S"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _currency(value: str | None) -> str | None:
    if value is None:
        return None
    cur = value.strip().upper()
    if not cur or cur == "BASE_SUMMARY":
        return None
    return cur


def _metric_code(raw: str) -> str:
    out = []
    previous_lower = False
    for ch in raw.strip():
        if ch.isupper() and previous_lower:
            out.append("_")
        if ch.isalnum():
            out.append(ch.lower())
            previous_lower = ch.islower() or ch.isdigit()
        else:
            if out and out[-1] != "_":
                out.append("_")
            previous_lower = False
    return "".join(out).strip("_")


def parse_flex_statement(xml_text: str) -> FlexStatement:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise IbkrFlexImportError("parse_failed", f"Invalid Flex XML: {exc}") from exc

    statement_element = _first(root, "FlexStatement")
    statement = statement_element if statement_element is not None else root
    account_id = _attr(statement, "accountId", "accountid", "account")
    if not account_id:
        first_account = _first(root, "AccountInformation")
        account_id = _attr(first_account, "accountId", "accountid") if first_account is not None else None
    if not account_id:
        raise IbkrFlexImportError("missing_account", "Flex statement does not include accountId")

    generated_at = _datetime(_attr(statement, "whenGenerated", "generatedAt"))
    from_date = _date(_attr(statement, "fromDate", "periodFrom"))
    to_date = _date(_attr(statement, "toDate", "periodTo"))

    nav_rows = _iter(root, "EquitySummaryByReportDateInBase")
    if not nav_rows:
        nav_rows = [row for row in _iter(root, "EquitySummaryInBase") if row.attrib]
    cash_rows = _iter(root, "CashReportCurrency")
    position_rows = _iter(root, "OpenPosition")
    fx_rows = _iter(root, "ConversionRate")
    stmt_fund_rows = _iter(root, "StmtFunds")
    trade_rows = _iter(root, "Trade")
    corporate_action_rows = _iter(root, "CorporateAction")

    report_dates = [
        parsed
        for row in [*nav_rows, *position_rows, *fx_rows]
        if (parsed := _date(_attr(row, "reportDate", "date"))) is not None
    ]
    if from_date is None:
        from_date = min(report_dates) if report_dates else date.today()
    if to_date is None:
        to_date = max(report_dates) if report_dates else from_date

    base_currency = None
    for row in fx_rows:
        base_currency = _currency(_attr(row, "toCurrency", "to"))
        if base_currency:
            break
    if base_currency is None:
        base_currency = _currency(_attr(statement, "baseCurrency")) or "USD"

    fx_by_currency: dict[str, Decimal] = {base_currency: Decimal("1")}
    fx_rates: list[FlexFxRate] = []
    data_quality_errors: list[tuple[str, str]] = []
    for row in fx_rows:
        from_currency = _currency(_attr(row, "fromCurrency", "from"))
        to_currency = _currency(_attr(row, "toCurrency", "to")) or base_currency
        rate = _decimal(_attr(row, "rate", "fxRate"))
        report_date = _date(_attr(row, "reportDate", "date"), to_date)
        if not from_currency or not to_currency or rate is None or report_date is None:
            continue
        fx_by_currency[from_currency] = rate
        fx_rates.append(FlexFxRate(report_date=report_date, from_currency=from_currency, to_currency=to_currency, rate=rate))

    nav_snapshots: list[FlexNavSnapshot] = []
    for row in nav_rows:
        report_date = _date(_attr(row, "reportDate", "date"), to_date)
        if report_date is None:
            continue
        cash = _decimal(_attr(row, "cash", "cashBase"), Decimal("0")) or Decimal("0")
        stock = _decimal(_attr(row, "stock", "stocks", "stockBase"), Decimal("0")) or Decimal("0")
        options = _decimal(_attr(row, "options", "optionBase"), Decimal("0")) or Decimal("0")
        funds = _decimal(_attr(row, "funds", "fundBase"), Decimal("0")) or Decimal("0")
        bonds = _decimal(_attr(row, "bonds", "bondBase"), Decimal("0")) or Decimal("0")
        interest_accruals = _decimal(_attr(row, "interestAccruals", "interestAccrual"), Decimal("0")) or Decimal("0")
        dividend_accruals = _decimal(_attr(row, "dividendAccruals", "dividendAccrual"), Decimal("0")) or Decimal("0")
        total = _decimal(_attr(row, "total", "totalNav", "totalEquity", "netLiquidation"))
        if total is None:
            total = cash + stock + options + funds + bonds + interest_accruals + dividend_accruals
        nav_snapshots.append(
            FlexNavSnapshot(
                report_date=report_date,
                base_currency=base_currency,
                cash_base=cash,
                stock_base=stock,
                options_base=options,
                funds_base=funds,
                bonds_base=bonds,
                interest_accrual_base=interest_accruals,
                dividend_accrual_base=dividend_accruals,
                total_nav_base=total,
            )
        )

    cash_balances: list[FlexCashBalance] = []
    report_metrics: list[FlexReportMetric] = []
    for row in cash_rows:
        currency = _currency(_attr(row, "currency"))
        report_date = _date(_attr(row, "toDate", "reportDate", "date"), to_date)
        if report_date is None:
            continue
        for attr_name in (
            "startingCash",
            "endingCash",
            "endingSettledCash",
            "brokerInterestPaidReceived",
            "brokerInterestPaidReceivedMTD",
            "brokerInterestPaidReceivedYTD",
            "depositsWithdrawals",
            "depositsWithdrawalsMTD",
            "depositsWithdrawalsYTD",
            "dividends",
            "dividendsMTD",
            "dividendsYTD",
            "brokerFees",
            "brokerFeesMTD",
            "brokerFeesYTD",
        ):
            amount = _decimal(_attr(row, attr_name))
            if amount is not None:
                report_metrics.append(
                    FlexReportMetric(
                        report_date=report_date,
                        report_section="CashReport",
                        metric_code=_metric_code(attr_name),
                        currency=currency,
                        amount=amount,
                    )
                )
        if currency is None:
            continue
        ending_cash = _decimal(_attr(row, "endingCash", "cashBalance"))
        if ending_cash is None:
            continue
        fx_rate = fx_by_currency.get(currency)
        if fx_rate is None:
            data_quality_errors.append(("missing_fx_rate", f"Missing FX rate for cash currency {currency}"))
            continue
        cash_balances.append(
            FlexCashBalance(
                report_date=report_date,
                currency=currency,
                cash_balance=ending_cash,
                fx_rate_to_base=fx_rate,
            )
        )

    positions: list[FlexPosition] = []
    for row in position_rows:
        report_date = _date(_attr(row, "reportDate", "date"), to_date)
        broker_instrument_id = _attr(row, "conid", "contractId", "figi", "isin")
        currency = _currency(_attr(row, "currency"))
        if report_date is None or not broker_instrument_id or currency is None:
            continue
        quantity = _required_decimal(_attr(row, "position", "quantity"), "position")
        market_value_local = _required_decimal(_attr(row, "positionValue", "marketValue"), "positionValue")
        fx_rate = _decimal(_attr(row, "fxRateToBase", "fxRate"))
        if fx_rate is None:
            fx_rate = fx_by_currency.get(currency)
        if fx_rate is None:
            data_quality_errors.append(("missing_fx_rate", f"Missing FX rate for position currency {currency}"))
            continue
        market_value_base = _decimal(_attr(row, "positionValueInBase", "marketValueBase"))
        if market_value_base is None:
            market_value_base = market_value_local * fx_rate
        cost_basis_local = _decimal(_attr(row, "costBasisMoney", "costBasis"))
        cost_basis_base = _decimal(_attr(row, "costBasisMoneyInBase", "costBasisBase"))
        if cost_basis_base is None and cost_basis_local is not None:
            cost_basis_base = cost_basis_local * fx_rate
        positions.append(
            FlexPosition(
                report_date=report_date,
                broker_instrument_id=broker_instrument_id.strip(),
                symbol=_attr(row, "symbol"),
                description=_attr(row, "description"),
                security_type=_attr(row, "assetCategory", "securityType"),
                listing_exchange=_attr(row, "listingExchange", "exchange"),
                currency=currency,
                quantity=quantity,
                market_price=_decimal(_attr(row, "markPrice", "marketPrice")),
                market_value_local=market_value_local,
                market_value_base=market_value_base,
                cost_basis_local=cost_basis_local,
                cost_basis_base=cost_basis_base,
                fx_rate_to_base=fx_rate,
            )
        )

    cash_ledger_entries: list[FlexCashLedgerEntry] = []
    for row in stmt_fund_rows:
        currency = _currency(_attr(row, "currency"))
        amount = _decimal(_attr(row, "amount", "netCash"))
        activity_date = _date(_attr(row, "date", "tradeDate", "reportDate"), to_date)
        if currency is None or amount is None or activity_date is None:
            continue
        cash_ledger_entries.append(
            FlexCashLedgerEntry(
                activity_date=activity_date,
                currency=currency,
                amount=amount,
                activity_code=_attr(row, "activityCode", "code"),
                description=_attr(row, "description", "activityDescription"),
                broker_activity_id=_attr(row, "transactionID", "transactionId", "id"),
            )
        )

    trades: list[FlexTrade] = []
    for row in trade_rows:
        trade_date = _date(_attr(row, "tradeDate", "date", "reportDate"), to_date)
        if trade_date is None:
            continue
        trades.append(
            FlexTrade(
                trade_date=trade_date,
                settle_date=_date(_attr(row, "settleDate", "settleDateTarget")),
                broker_instrument_id=_attr(row, "conid", "contractId"),
                symbol=_attr(row, "symbol"),
                description=_attr(row, "description"),
                security_type=_attr(row, "assetCategory", "securityType"),
                listing_exchange=_attr(row, "listingExchange", "exchange"),
                currency=_currency(_attr(row, "currency")),
                side=_attr(row, "buySell", "side"),
                quantity=_decimal(_attr(row, "quantity", "tradeQuantity")),
                price=_decimal(_attr(row, "tradePrice", "price")),
                proceeds=_decimal(_attr(row, "proceeds")),
                commission=_decimal(_attr(row, "ibCommission", "commission")),
                broker_execution_id=_attr(row, "ibExecID", "executionId", "execId", "transactionID"),
            )
        )

    corporate_actions: list[FlexCorporateAction] = []
    for row in corporate_action_rows:
        action_date = _date(_attr(row, "date", "reportDate", "tradeDate"), to_date)
        if action_date is None:
            continue
        corporate_actions.append(
            FlexCorporateAction(
                action_date=action_date,
                broker_instrument_id=_attr(row, "conid", "contractId"),
                symbol=_attr(row, "symbol"),
                description=_attr(row, "description"),
                security_type=_attr(row, "assetCategory", "securityType"),
                listing_exchange=_attr(row, "listingExchange", "exchange"),
                action_type=_attr(row, "type", "actionType", "activityCode"),
                quantity=_decimal(_attr(row, "quantity")),
                cash_amount=_decimal(_attr(row, "amount", "proceeds", "cashAmount")),
                currency=_currency(_attr(row, "currency")),
                broker_action_id=_attr(row, "transactionID", "transactionId", "id"),
            )
        )

    return FlexStatement(
        broker_account_id=account_id.strip(),
        report_date_from=from_date,
        report_date_to=to_date,
        base_currency=base_currency,
        generated_at=generated_at,
        nav_snapshots=nav_snapshots,
        cash_balances=cash_balances,
        positions=positions,
        fx_rates=fx_rates,
        cash_ledger_entries=cash_ledger_entries,
        trades=trades,
        corporate_actions=corporate_actions,
        report_metrics=report_metrics,
        data_quality_errors=data_quality_errors,
    )


class IbkrFlexClient:
    def __init__(
        self,
        token: str,
        query_id: str,
        base_url: str = DEFAULT_IBKR_FLEX_BASE_URL,
        timeout_seconds: float = 30.0,
        user_agent: str | None = None,
    ) -> None:
        if not token or not query_id:
            raise IbkrFlexConfigError("IBKR Flex token and query id are required")
        self._token = token
        self._query_id = query_id
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._user_agent = user_agent.strip() if user_agent else None

    @classmethod
    def from_env(cls) -> "IbkrFlexClient":
        token = _first_env_value("IBKR_FLEX_TOKEN", "IBKR_TOKEN")
        query_id = _first_env_value("IBKR_FLEX_QUERY_ID", "IBKR_QUERY_ID")
        base_url = _first_env_value("IBKR_FLEX_BASE_URL", "IBKR_FLEX_BASE", default=DEFAULT_IBKR_FLEX_BASE_URL)
        timeout_seconds = float(os.getenv("IBKR_FLEX_TIMEOUT_SECONDS", "30"))
        user_agent = _first_env_value("IBKR_USER_AGENT", default=DEFAULT_IBKR_USER_AGENT)
        return cls(
            token=token,
            query_id=query_id,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
        )

    def _request_headers(self) -> dict[str, str] | None:
        if not self._user_agent:
            return None
        return {"User-Agent": self._user_agent}

    def _service_url(self, operation: str) -> str:
        operation_names = {
            "send": ("SendRequest", "FlexStatementService.SendRequest"),
            "get": ("GetStatement", "FlexStatementService.GetStatement"),
        }
        modern_name, legacy_name = operation_names[operation]
        if self._base_url.endswith(f"/{modern_name}") or self._base_url.endswith(f"/{legacy_name}"):
            return self._base_url
        if self._base_url.rstrip("/").endswith("FlexWebService"):
            return f"{self._base_url}/{modern_name}"
        return f"{self._base_url}/{legacy_name}"

    def send_request(self) -> str:
        url = self._service_url("send")
        params = {"t": self._token, "q": self._query_id, "v": "3"}
        with httpx.Client(timeout=self._timeout_seconds) as client:
            response = client.get(url, params=params, headers=self._request_headers())
            response.raise_for_status()
        return self._extract_reference_code(response.text)

    def get_statement(self, reference_code: str) -> str:
        url = self._service_url("get")
        params = {"t": self._token, "q": reference_code, "v": "3"}
        with httpx.Client(timeout=self._timeout_seconds) as client:
            response = client.get(url, params=params, headers=self._request_headers())
            response.raise_for_status()
        text_body = response.text
        self._raise_if_not_ready(text_body)
        return text_body

    def fetch_statement(
        self,
        max_attempts: int = 5,
        initial_backoff_seconds: float = 2.0,
        max_backoff_seconds: float = 30.0,
    ) -> tuple[str, str]:
        reference_code = self.send_request()
        for attempt in range(1, max_attempts + 1):
            try:
                return reference_code, self.get_statement(reference_code)
            except IbkrFlexStatementNotReady:
                if attempt >= max_attempts:
                    raise
                time.sleep(
                    _bounded_exponential_backoff_seconds(
                        attempt,
                        initial_backoff_seconds,
                        max_backoff_seconds,
                    )
                )
        raise IbkrFlexResponseError("Flex statement was not ready")

    @staticmethod
    def _extract_reference_code(xml_text: str) -> str:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise IbkrFlexResponseError(f"Invalid SendRequest XML: {exc}") from exc
        status = ""
        reference_code = ""
        error_code = ""
        error_message = ""
        for element in root.iter():
            name = _local_name(element.tag)
            text_value = (element.text or "").strip()
            if name == "Status":
                status = text_value
            elif name == "ReferenceCode":
                reference_code = text_value
            elif name == "ErrorCode":
                error_code = text_value
            elif name == "ErrorMessage":
                error_message = text_value
        if status and status.lower() != "success":
            detail = "IBKR Flex SendRequest did not return success"
            if error_code or error_message:
                detail = f"{detail}: {error_code} {error_message}".strip()
            raise IbkrFlexResponseError(detail)
        if not reference_code:
            raise IbkrFlexResponseError("IBKR Flex SendRequest did not return ReferenceCode")
        return reference_code

    @staticmethod
    def _raise_if_not_ready(xml_text: str) -> None:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return
        status = ""
        error_code = ""
        error_message = ""
        for element in root.iter():
            name = _local_name(element.tag)
            text_value = (element.text or "").strip()
            if name == "Status":
                status = text_value
            elif name == "ErrorCode":
                error_code = text_value
            elif name == "ErrorMessage":
                error_message = text_value
        normalized_message = error_message.lower()
        if error_code == "1019" or "generation in progress" in normalized_message:
            raise IbkrFlexStatementNotReady("IBKR Flex statement is still generating")
        if status and status.lower() not in {"success", "ok"}:
            detail = "IBKR Flex GetStatement did not return success"
            if error_code or error_message:
                detail = f"{detail}: {error_code} {error_message}".strip()
            raise IbkrFlexResponseError(detail)


def _data_dir() -> str:
    return os.getenv("DATA_DIR", os.path.join(os.getcwd(), "data"))


def _platform_json_default(db: Session) -> str:
    return "'{}'::jsonb" if db.bind and db.bind.dialect.name == "postgresql" else "'{}'"


def _now() -> datetime:
    return datetime.now(tz=timezone.utc).replace(microsecond=0)


def _db_decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def is_ibkr_flex_cutover_active(db: Session, legacy_account_id: int, on_date: date | None = None) -> bool:
    effective_date = on_date or date.today()
    row = db.execute(
        text(
            """
            SELECT 1
            FROM portfolio_source_authority_windows aw
            JOIN broker_accounts ba ON ba.id = aw.broker_account_id
            JOIN broker_connections bc ON bc.id = ba.connection_id
            WHERE ba.legacy_account_id = :legacy_account_id
              AND bc.platform_code = 'IBKR'
              AND aw.source_kind = :source_kind
              AND aw.fact_scope = :fact_scope
              AND aw.authority_status = 'authoritative'
              AND aw.effective_from <= :effective_date
              AND (aw.effective_to IS NULL OR aw.effective_to >= :effective_date)
            LIMIT 1
            """
        ),
        {
            "legacy_account_id": legacy_account_id,
            "source_kind": SOURCE_TYPE,
            "fact_scope": ALL_FACT_SCOPE,
            "effective_date": effective_date,
        },
    ).fetchone()
    return row is not None


def _ensure_broker_account(
    db: Session,
    *,
    current_user_id: int,
    legacy_account_id: int,
    broker_account_id: str,
    base_currency: str,
) -> int:
    connection = db.execute(
        text(
            """
            SELECT id
            FROM broker_connections
            WHERE user_id = :user_id
              AND platform_code = 'IBKR'
              AND connection_type = 'flex_api'
              AND status = 'active'
            ORDER BY id
            LIMIT 1
            """
        ),
        {"user_id": current_user_id},
    ).fetchone()
    if connection:
        connection_id = int(connection[0])
    else:
        db.execute(
            text(
                f"""
                INSERT INTO broker_connections
                  (user_id, platform_code, connection_type, display_name, status, metadata_json)
                VALUES
                  (:user_id, 'IBKR', 'flex_api', 'IBKR Flex', 'active', {_platform_json_default(db)})
                """
            ),
            {"user_id": current_user_id},
        )
        row = db.execute(
            text(
                """
                SELECT id
                FROM broker_connections
                WHERE user_id = :user_id
                  AND platform_code = 'IBKR'
                  AND connection_type = 'flex_api'
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"user_id": current_user_id},
        ).fetchone()
        connection_id = int(row[0])

    account = db.execute(
        text(
            """
            SELECT id
            FROM broker_accounts
            WHERE connection_id = :connection_id
              AND broker_account_id = :broker_account_id
            LIMIT 1
            """
        ),
        {"connection_id": connection_id, "broker_account_id": broker_account_id},
    ).fetchone()
    if account:
        broker_account_pk = int(account[0])
        db.execute(
            text(
                """
                UPDATE broker_accounts
                SET legacy_account_id = :legacy_account_id,
                    base_currency = :base_currency,
                    updated_at = :updated_at
                WHERE id = :broker_account_pk
                """
            ),
            {
                "legacy_account_id": legacy_account_id,
                "base_currency": base_currency,
                "updated_at": _now(),
                "broker_account_pk": broker_account_pk,
            },
        )
        return broker_account_pk

    db.execute(
        text(
            f"""
            INSERT INTO broker_accounts
              (connection_id, legacy_account_id, broker_account_id, base_currency, status, metadata_json)
            VALUES
              (:connection_id, :legacy_account_id, :broker_account_id, :base_currency, 'active', {_platform_json_default(db)})
            """
        ),
        {
            "connection_id": connection_id,
            "legacy_account_id": legacy_account_id,
            "broker_account_id": broker_account_id,
            "base_currency": base_currency,
        },
    )
    row = db.execute(
        text(
            """
            SELECT id
            FROM broker_accounts
            WHERE connection_id = :connection_id
              AND broker_account_id = :broker_account_id
            LIMIT 1
            """
        ),
        {"connection_id": connection_id, "broker_account_id": broker_account_id},
    ).fetchone()
    return int(row[0])


def _ensure_authority_window(db: Session, broker_account_id: int, cutover_date: date) -> None:
    exists = db.execute(
        text(
            """
            SELECT 1
            FROM portfolio_source_authority_windows
            WHERE broker_account_id = :broker_account_id
              AND source_kind = :source_kind
              AND fact_scope = :fact_scope
              AND effective_from = :effective_from
            LIMIT 1
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "source_kind": SOURCE_TYPE,
            "fact_scope": ALL_FACT_SCOPE,
            "effective_from": cutover_date,
        },
    ).fetchone()
    if exists:
        return
    db.execute(
        text(
            """
            INSERT INTO portfolio_source_authority_windows
              (broker_account_id, source_kind, fact_scope, effective_from, authority_status)
            VALUES
              (:broker_account_id, :source_kind, :fact_scope, :effective_from, 'authoritative')
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "source_kind": SOURCE_TYPE,
            "fact_scope": ALL_FACT_SCOPE,
            "effective_from": cutover_date,
        },
    )


def _create_import_run(
    db: Session,
    *,
    broker_account_id: int,
    legacy_account_id: int,
    statement: FlexStatement,
    reference_code: str | None,
) -> int:
    db.execute(
        text(
            f"""
            INSERT INTO broker_import_runs
              (broker_account_id, legacy_account_id, platform_code, source_type, import_scope, status,
               started_at, report_date_from, report_date_to, flex_reference_code, parser_version, metadata_json)
            VALUES
              (:broker_account_id, :legacy_account_id, 'IBKR', :source_type, 'daily', 'started',
               :started_at, :report_date_from, :report_date_to, :reference_code, :parser_version, {_platform_json_default(db)})
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "legacy_account_id": legacy_account_id,
            "source_type": SOURCE_TYPE,
            "started_at": _now(),
            "report_date_from": statement.report_date_from,
            "report_date_to": statement.report_date_to,
            "reference_code": reference_code,
            "parser_version": PARSER_VERSION,
        },
    )
    row = db.execute(
        text(
            """
            SELECT id
            FROM broker_import_runs
            WHERE broker_account_id = :broker_account_id
              AND source_type = :source_type
              AND status = 'started'
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {"broker_account_id": broker_account_id, "source_type": SOURCE_TYPE},
    ).fetchone()
    return int(row[0])


def _try_acquire_lock(db: Session, broker_account_id: int, source_type: str) -> str:
    owner = str(uuid.uuid4())
    try:
        db.execute(
            text(
                """
                INSERT INTO portfolio_import_locks (broker_account_id, source_type, lock_owner, locked_at)
                VALUES (:broker_account_id, :source_type, :lock_owner, :locked_at)
                """
            ),
            {
                "broker_account_id": broker_account_id,
                "source_type": source_type,
                "lock_owner": owner,
                "locked_at": _now(),
            },
        )
        db.flush()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise IbkrFlexImportInProgress("IBKR Flex import already in progress for this account") from exc
    return owner


def _release_lock(db: Session, broker_account_id: int, owner: str) -> None:
    db.execute(
        text(
            """
            DELETE FROM portfolio_import_locks
            WHERE broker_account_id = :broker_account_id
              AND lock_owner = :lock_owner
            """
        ),
        {"broker_account_id": broker_account_id, "lock_owner": owner},
    )


def _store_raw_xml(
    db: Session,
    *,
    import_run_id: int,
    broker_account_id: int,
    xml_text: str,
    statement: FlexStatement,
) -> int:
    content_hash = hashlib.sha256(xml_text.encode("utf-8")).hexdigest()
    raw_dir = Path(_data_dir()) / "broker_raw" / "ibkr_flex"
    raw_dir.mkdir(parents=True, exist_ok=True)
    storage_path = raw_dir / f"{content_hash}.xml"
    if not storage_path.exists():
        storage_path.write_text(xml_text, encoding="utf-8")
    db.execute(
        text(
            f"""
            INSERT INTO raw_broker_documents
              (import_run_id, broker_account_id, source_type, content_hash, storage_path,
               content_type, report_date_from, report_date_to, parser_version, metadata_json)
            VALUES
              (:import_run_id, :broker_account_id, :source_type, :content_hash, :storage_path,
               'application/xml', :report_date_from, :report_date_to, :parser_version, {_platform_json_default(db)})
            """
        ),
        {
            "import_run_id": import_run_id,
            "broker_account_id": broker_account_id,
            "source_type": SOURCE_TYPE,
            "content_hash": content_hash,
            "storage_path": str(storage_path),
            "report_date_from": statement.report_date_from,
            "report_date_to": statement.report_date_to,
            "parser_version": PARSER_VERSION,
        },
    )
    row = db.execute(
        text(
            """
            SELECT id
            FROM raw_broker_documents
            WHERE import_run_id = :import_run_id
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {"import_run_id": import_run_id},
    ).fetchone()
    raw_document_id = int(row[0])
    db.execute(
        text(
            """
            UPDATE broker_import_runs
            SET raw_document_id = :raw_document_id,
                fetched_at = :fetched_at,
                updated_at = :updated_at
            WHERE id = :import_run_id
            """
        ),
        {"raw_document_id": raw_document_id, "fetched_at": _now(), "updated_at": _now(), "import_run_id": import_run_id},
    )
    return raw_document_id


def _record_data_quality_event(
    db: Session,
    *,
    broker_account_id: int | None,
    import_run_id: int | None,
    raw_document_id: int | None,
    report_date: date | None,
    severity: str,
    event_code: str,
    message: str,
) -> None:
    db.execute(
        text(
            f"""
            INSERT INTO portfolio_data_quality_events
              (broker_account_id, import_run_id, raw_document_id, report_date, severity, event_code, message, metadata_json)
            VALUES
              (:broker_account_id, :import_run_id, :raw_document_id, :report_date, :severity, :event_code, :message, {_platform_json_default(db)})
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "import_run_id": import_run_id,
            "raw_document_id": raw_document_id,
            "report_date": report_date,
            "severity": severity,
            "event_code": event_code,
            "message": message,
        },
    )


def _mark_import_failed(db: Session, import_run_id: int, code: str, message: str) -> None:
    db.execute(
        text(
            """
            UPDATE broker_import_runs
            SET status = 'failed',
                error_code = :error_code,
                error_message = :error_message,
                finished_at = :finished_at,
                updated_at = :updated_at
            WHERE id = :import_run_id
            """
        ),
        {
            "error_code": code,
            "error_message": message,
            "finished_at": _now(),
            "updated_at": _now(),
            "import_run_id": import_run_id,
        },
    )


def _mark_import_completed(db: Session, import_run_id: int, status: str = "completed") -> None:
    db.execute(
        text(
            """
            UPDATE broker_import_runs
            SET status = :status,
                parsed_at = COALESCE(parsed_at, :parsed_at),
                finished_at = :finished_at,
                updated_at = :updated_at
            WHERE id = :import_run_id
            """
        ),
        {"status": status, "parsed_at": _now(), "finished_at": _now(), "updated_at": _now(), "import_run_id": import_run_id},
    )


def _validate_statement(statement: FlexStatement) -> None:
    if statement.data_quality_errors:
        code, message = statement.data_quality_errors[0]
        raise IbkrFlexImportError(code, message)
    latest_nav = max(statement.nav_snapshots, key=lambda nav: nav.report_date, default=None)
    if latest_nav and latest_nav.stock_base != Decimal("0") and not statement.positions:
        raise IbkrFlexImportError(
            "empty_open_positions_with_stock_nav",
            "Flex statement has non-zero stock NAV but no OpenPositions rows",
        )
    if not statement.nav_snapshots:
        raise IbkrFlexImportError("missing_nav", "Flex statement does not include EquitySummaryInBase")


def _report_dates(statement: FlexStatement) -> set[date]:
    dates = {nav.report_date for nav in statement.nav_snapshots}
    dates.update(cash.report_date for cash in statement.cash_balances)
    dates.update(position.report_date for position in statement.positions)
    if not dates:
        dates.add(statement.report_date_to)
    return dates


def _authority_status(report_date: date, cutover_date: date) -> str:
    return "authoritative" if report_date >= cutover_date else "reference"


def _resolve_cutover_date(statement: FlexStatement, cutover_date: date | None) -> date:
    return cutover_date or statement.report_date_from


def _clear_existing_authoritative_facts(db: Session, broker_account_id: int, report_dates: set[date]) -> None:
    for report_date in report_dates:
        for table_name in (
            "portfolio_position_snapshots",
            "portfolio_cash_balance_snapshots",
            "portfolio_nav_snapshots",
            "portfolio_report_metrics",
            "portfolio_reconciliations",
            "portfolio_data_completeness",
        ):
            db.execute(
                text(f"DELETE FROM {table_name} WHERE broker_account_id = :broker_account_id AND report_date = :report_date"),
                {"broker_account_id": broker_account_id, "report_date": report_date},
            )


def _ensure_broker_instrument_values(
    db: Session,
    *,
    broker_instrument_id: str,
    symbol: str | None,
    description: str | None,
    security_type: str | None,
    listing_exchange: str | None,
    currency: str | None,
) -> int:
    row = db.execute(
        text(
            """
            SELECT id
            FROM broker_instruments
            WHERE platform_code = 'IBKR'
              AND broker_instrument_id = :broker_instrument_id
              AND COALESCE(listing_exchange, '') = COALESCE(:listing_exchange, '')
              AND COALESCE(currency, '') = COALESCE(:currency, '')
            LIMIT 1
            """
        ),
        {
            "broker_instrument_id": broker_instrument_id,
            "listing_exchange": listing_exchange,
            "currency": currency,
        },
    ).fetchone()
    if row:
        instrument_id = int(row[0])
        db.execute(
            text(
                """
                UPDATE broker_instruments
                SET symbol = COALESCE(:symbol, symbol),
                    description = COALESCE(:description, description),
                    security_type = COALESCE(:security_type, security_type),
                    updated_at = :updated_at
                WHERE id = :instrument_id
                """
            ),
            {
                "symbol": symbol,
                "description": description,
                "security_type": security_type,
                "updated_at": _now(),
                "instrument_id": instrument_id,
            },
        )
        return instrument_id

    db.execute(
        text(
            f"""
            INSERT INTO broker_instruments
              (platform_code, broker_instrument_id, symbol, description, security_type,
               listing_exchange, currency, metadata_json)
            VALUES
              ('IBKR', :broker_instrument_id, :symbol, :description, :security_type,
               :listing_exchange, :currency, {_platform_json_default(db)})
            """
        ),
        {
            "broker_instrument_id": broker_instrument_id,
            "symbol": symbol,
            "description": description,
            "security_type": security_type,
            "listing_exchange": listing_exchange,
            "currency": currency,
        },
    )
    row = db.execute(
        text(
            """
            SELECT id
            FROM broker_instruments
            WHERE platform_code = 'IBKR'
              AND broker_instrument_id = :broker_instrument_id
              AND COALESCE(listing_exchange, '') = COALESCE(:listing_exchange, '')
              AND COALESCE(currency, '') = COALESCE(:currency, '')
            LIMIT 1
            """
        ),
        {
            "broker_instrument_id": broker_instrument_id,
            "listing_exchange": listing_exchange,
            "currency": currency,
        },
    ).fetchone()
    return int(row[0])


def _ensure_broker_instrument(db: Session, position: FlexPosition) -> int:
    return _ensure_broker_instrument_values(
        db,
        broker_instrument_id=position.broker_instrument_id,
        symbol=position.symbol,
        description=position.description,
        security_type=position.security_type,
        listing_exchange=position.listing_exchange,
        currency=position.currency,
    )


def _insert_statement_facts(
    db: Session,
    *,
    broker_account_id: int,
    legacy_account_id: int,
    import_run_id: int,
    raw_document_id: int,
    statement: FlexStatement,
    cutover_date: date,
) -> None:
    report_dates = _report_dates(statement)
    _clear_existing_authoritative_facts(db, broker_account_id, report_dates)

    for fx_rate in statement.fx_rates:
        db.execute(
            text(
                """
                DELETE FROM portfolio_fx_rates
                WHERE report_date = :report_date
                  AND from_currency = :from_currency
                  AND to_currency = :to_currency
                  AND source_platform = 'IBKR'
                """
            ),
            {
                "report_date": fx_rate.report_date,
                "from_currency": fx_rate.from_currency,
                "to_currency": fx_rate.to_currency,
            },
        )
        db.execute(
            text(
                f"""
                INSERT INTO portfolio_fx_rates
                  (import_run_id, raw_document_id, report_date, from_currency, to_currency,
                   rate, source_platform, metadata_json)
                VALUES
                  (:import_run_id, :raw_document_id, :report_date, :from_currency, :to_currency,
                   :rate, 'IBKR', {_platform_json_default(db)})
                """
            ),
            {
                "import_run_id": import_run_id,
                "raw_document_id": raw_document_id,
                "report_date": fx_rate.report_date,
                "from_currency": fx_rate.from_currency,
                "to_currency": fx_rate.to_currency,
                "rate": _db_decimal(fx_rate.rate),
            },
        )

    for position in statement.positions:
        instrument_id = _ensure_broker_instrument(db, position)
        db.execute(
            text(
                f"""
                INSERT INTO portfolio_position_snapshots
                  (broker_account_id, legacy_account_id, broker_instrument_id, import_run_id, raw_document_id,
                   report_date, quantity, currency, market_price, market_value_local, market_value_base,
                   cost_basis_local, cost_basis_base, fx_rate_to_base, authority_status, metadata_json)
                VALUES
                  (:broker_account_id, :legacy_account_id, :broker_instrument_id, :import_run_id, :raw_document_id,
                   :report_date, :quantity, :currency, :market_price, :market_value_local, :market_value_base,
                   :cost_basis_local, :cost_basis_base, :fx_rate_to_base, :authority_status, {_platform_json_default(db)})
                """
            ),
            {
                "broker_account_id": broker_account_id,
                "legacy_account_id": legacy_account_id,
                "broker_instrument_id": instrument_id,
                "import_run_id": import_run_id,
                "raw_document_id": raw_document_id,
                "report_date": position.report_date,
                "quantity": _db_decimal(position.quantity),
                "currency": position.currency,
                "market_price": _db_decimal(position.market_price),
                "market_value_local": _db_decimal(position.market_value_local),
                "market_value_base": _db_decimal(position.market_value_base),
                "cost_basis_local": _db_decimal(position.cost_basis_local),
                "cost_basis_base": _db_decimal(position.cost_basis_base),
                "fx_rate_to_base": _db_decimal(position.fx_rate_to_base),
                "authority_status": _authority_status(position.report_date, cutover_date),
            },
        )

    for cash in statement.cash_balances:
        db.execute(
            text(
                f"""
                INSERT INTO portfolio_cash_balance_snapshots
                  (broker_account_id, legacy_account_id, import_run_id, raw_document_id, report_date,
                   currency, cash_balance, cash_balance_base, fx_rate_to_base, authority_status, metadata_json)
                VALUES
                  (:broker_account_id, :legacy_account_id, :import_run_id, :raw_document_id, :report_date,
                   :currency, :cash_balance, :cash_balance_base, :fx_rate_to_base, :authority_status, {_platform_json_default(db)})
                """
            ),
            {
                "broker_account_id": broker_account_id,
                "legacy_account_id": legacy_account_id,
                "import_run_id": import_run_id,
                "raw_document_id": raw_document_id,
                "report_date": cash.report_date,
                "currency": cash.currency,
                "cash_balance": _db_decimal(cash.cash_balance),
                "cash_balance_base": _db_decimal(cash.cash_balance_base),
                "fx_rate_to_base": _db_decimal(cash.fx_rate_to_base),
                "authority_status": _authority_status(cash.report_date, cutover_date),
            },
        )

    for nav in statement.nav_snapshots:
        db.execute(
            text(
                f"""
                INSERT INTO portfolio_nav_snapshots
                  (broker_account_id, legacy_account_id, import_run_id, raw_document_id, report_date,
                   base_currency, cash_base, stock_base, options_base, funds_base, bonds_base,
                   interest_accrual_base, dividend_accrual_base, total_nav_base, authority_status, metadata_json)
                VALUES
                  (:broker_account_id, :legacy_account_id, :import_run_id, :raw_document_id, :report_date,
                   :base_currency, :cash_base, :stock_base, :options_base, :funds_base, :bonds_base,
                   :interest_accrual_base, :dividend_accrual_base, :total_nav_base, :authority_status, {_platform_json_default(db)})
                """
            ),
            {
                "broker_account_id": broker_account_id,
                "legacy_account_id": legacy_account_id,
                "import_run_id": import_run_id,
                "raw_document_id": raw_document_id,
                "report_date": nav.report_date,
                "base_currency": nav.base_currency,
                "cash_base": _db_decimal(nav.cash_base),
                "stock_base": _db_decimal(nav.stock_base),
                "options_base": _db_decimal(nav.options_base),
                "funds_base": _db_decimal(nav.funds_base),
                "bonds_base": _db_decimal(nav.bonds_base),
                "interest_accrual_base": _db_decimal(nav.interest_accrual_base),
                "dividend_accrual_base": _db_decimal(nav.dividend_accrual_base),
                "total_nav_base": _db_decimal(nav.total_nav_base),
                "authority_status": _authority_status(nav.report_date, cutover_date),
            },
        )

    for metric in statement.report_metrics:
        db.execute(
            text(
                f"""
                INSERT INTO portfolio_report_metrics
                  (broker_account_id, import_run_id, raw_document_id, report_date, report_section,
                   metric_code, currency, amount, metadata_json)
                VALUES
                  (:broker_account_id, :import_run_id, :raw_document_id, :report_date, :report_section,
                   :metric_code, :currency, :amount, {_platform_json_default(db)})
                """
            ),
            {
                "broker_account_id": broker_account_id,
                "import_run_id": import_run_id,
                "raw_document_id": raw_document_id,
                "report_date": metric.report_date,
                "report_section": metric.report_section,
                "metric_code": metric.metric_code,
                "currency": metric.currency,
                "amount": _db_decimal(metric.amount),
            },
        )

    _insert_cash_ledger_entries(
        db,
        broker_account_id=broker_account_id,
        import_run_id=import_run_id,
        raw_document_id=raw_document_id,
        entries=statement.cash_ledger_entries,
    )
    _insert_trades(
        db,
        broker_account_id=broker_account_id,
        import_run_id=import_run_id,
        raw_document_id=raw_document_id,
        trades=statement.trades,
    )
    _insert_corporate_actions(
        db,
        broker_account_id=broker_account_id,
        import_run_id=import_run_id,
        raw_document_id=raw_document_id,
        corporate_actions=statement.corporate_actions,
    )

    _insert_reconciliations(
        db,
        broker_account_id=broker_account_id,
        import_run_id=import_run_id,
        raw_document_id=raw_document_id,
        statement=statement,
    )
    for report_date in report_dates:
        _insert_completeness(
            db,
            broker_account_id=broker_account_id,
            import_run_id=import_run_id,
            raw_document_id=raw_document_id,
            report_date=report_date,
            fact_scope="holdings_cash_nav_fx",
            completeness_status="complete",
            missing_reason=None,
        )


def _insert_cash_ledger_entries(
    db: Session,
    *,
    broker_account_id: int,
    import_run_id: int,
    raw_document_id: int,
    entries: list[FlexCashLedgerEntry],
) -> None:
    for entry in entries:
        db.execute(
            text(
                """
                DELETE FROM portfolio_cash_ledger_entries
                WHERE broker_account_id = :broker_account_id
                  AND activity_date = :activity_date
                  AND currency = :currency
                  AND amount = :amount
                  AND COALESCE(activity_code, '') = COALESCE(:activity_code, '')
                  AND COALESCE(broker_activity_id, '') = COALESCE(:broker_activity_id, '')
                  AND COALESCE(description, '') = COALESCE(:description, '')
                """
            ),
            {
                "broker_account_id": broker_account_id,
                "activity_date": entry.activity_date,
                "currency": entry.currency,
                "amount": _db_decimal(entry.amount),
                "activity_code": entry.activity_code,
                "broker_activity_id": entry.broker_activity_id,
                "description": entry.description,
            },
        )
        db.execute(
            text(
                f"""
                INSERT INTO portfolio_cash_ledger_entries
                  (broker_account_id, import_run_id, raw_document_id, activity_date, currency, amount,
                   activity_code, description, broker_activity_id, metadata_json)
                VALUES
                  (:broker_account_id, :import_run_id, :raw_document_id, :activity_date, :currency, :amount,
                   :activity_code, :description, :broker_activity_id, {_platform_json_default(db)})
                """
            ),
            {
                "broker_account_id": broker_account_id,
                "import_run_id": import_run_id,
                "raw_document_id": raw_document_id,
                "activity_date": entry.activity_date,
                "currency": entry.currency,
                "amount": _db_decimal(entry.amount),
                "activity_code": entry.activity_code,
                "description": entry.description,
                "broker_activity_id": entry.broker_activity_id,
            },
        )


def _optional_instrument_for_trade(db: Session, trade: FlexTrade) -> int | None:
    if not trade.broker_instrument_id:
        return None
    return _ensure_broker_instrument_values(
        db,
        broker_instrument_id=trade.broker_instrument_id,
        symbol=trade.symbol,
        description=trade.description,
        security_type=trade.security_type,
        listing_exchange=trade.listing_exchange,
        currency=trade.currency,
    )


def _optional_instrument_for_corporate_action(db: Session, action: FlexCorporateAction) -> int | None:
    if not action.broker_instrument_id:
        return None
    return _ensure_broker_instrument_values(
        db,
        broker_instrument_id=action.broker_instrument_id,
        symbol=action.symbol,
        description=action.description,
        security_type=action.security_type,
        listing_exchange=action.listing_exchange,
        currency=action.currency,
    )


def _insert_trades(
    db: Session,
    *,
    broker_account_id: int,
    import_run_id: int,
    raw_document_id: int,
    trades: list[FlexTrade],
) -> None:
    for trade in trades:
        instrument_id = _optional_instrument_for_trade(db, trade)
        if trade.broker_execution_id:
            db.execute(
                text(
                    """
                    DELETE FROM portfolio_trades
                    WHERE broker_account_id = :broker_account_id
                      AND broker_execution_id = :broker_execution_id
                    """
                ),
                {"broker_account_id": broker_account_id, "broker_execution_id": trade.broker_execution_id},
            )
        else:
            db.execute(
                text(
                    """
                    DELETE FROM portfolio_trades
                    WHERE broker_account_id = :broker_account_id
                      AND trade_date = :trade_date
                      AND COALESCE(broker_instrument_id, 0) = COALESCE(:broker_instrument_id, 0)
                      AND COALESCE(currency, '') = COALESCE(:currency, '')
                      AND COALESCE(side, '') = COALESCE(:side, '')
                      AND COALESCE(quantity, 0) = COALESCE(CAST(:quantity AS NUMERIC), 0)
                      AND COALESCE(price, 0) = COALESCE(CAST(:price AS NUMERIC), 0)
                      AND COALESCE(proceeds, 0) = COALESCE(CAST(:proceeds AS NUMERIC), 0)
                    """
                ),
                {
                    "broker_account_id": broker_account_id,
                    "trade_date": trade.trade_date,
                    "broker_instrument_id": instrument_id,
                    "currency": trade.currency,
                    "side": trade.side,
                    "quantity": _db_decimal(trade.quantity),
                    "price": _db_decimal(trade.price),
                    "proceeds": _db_decimal(trade.proceeds),
                },
            )
        db.execute(
            text(
                f"""
                INSERT INTO portfolio_trades
                  (broker_account_id, broker_instrument_id, import_run_id, raw_document_id,
                   trade_date, settle_date, side, quantity, price, proceeds, commission,
                   currency, broker_execution_id, metadata_json)
                VALUES
                  (:broker_account_id, :broker_instrument_id, :import_run_id, :raw_document_id,
                   :trade_date, :settle_date, :side, :quantity, :price, :proceeds, :commission,
                   :currency, :broker_execution_id, {_platform_json_default(db)})
                """
            ),
            {
                "broker_account_id": broker_account_id,
                "broker_instrument_id": instrument_id,
                "import_run_id": import_run_id,
                "raw_document_id": raw_document_id,
                "trade_date": trade.trade_date,
                "settle_date": trade.settle_date,
                "side": trade.side,
                "quantity": _db_decimal(trade.quantity),
                "price": _db_decimal(trade.price),
                "proceeds": _db_decimal(trade.proceeds),
                "commission": _db_decimal(trade.commission),
                "currency": trade.currency,
                "broker_execution_id": trade.broker_execution_id,
            },
        )


def _insert_corporate_actions(
    db: Session,
    *,
    broker_account_id: int,
    import_run_id: int,
    raw_document_id: int,
    corporate_actions: list[FlexCorporateAction],
) -> None:
    for action in corporate_actions:
        instrument_id = _optional_instrument_for_corporate_action(db, action)
        if action.broker_action_id:
            db.execute(
                text(
                    """
                    DELETE FROM portfolio_corporate_action_events
                    WHERE broker_account_id = :broker_account_id
                      AND broker_action_id = :broker_action_id
                    """
                ),
                {"broker_account_id": broker_account_id, "broker_action_id": action.broker_action_id},
            )
        else:
            db.execute(
                text(
                    """
                    DELETE FROM portfolio_corporate_action_events
                    WHERE broker_account_id = :broker_account_id
                      AND action_date = :action_date
                      AND COALESCE(broker_instrument_id, 0) = COALESCE(:broker_instrument_id, 0)
                      AND COALESCE(action_type, '') = COALESCE(:action_type, '')
                      AND COALESCE(currency, '') = COALESCE(:currency, '')
                      AND COALESCE(quantity, 0) = COALESCE(CAST(:quantity AS NUMERIC), 0)
                      AND COALESCE(cash_amount, 0) = COALESCE(CAST(:cash_amount AS NUMERIC), 0)
                    """
                ),
                {
                    "broker_account_id": broker_account_id,
                    "action_date": action.action_date,
                    "broker_instrument_id": instrument_id,
                    "action_type": action.action_type,
                    "currency": action.currency,
                    "quantity": _db_decimal(action.quantity),
                    "cash_amount": _db_decimal(action.cash_amount),
                },
            )
        db.execute(
            text(
                f"""
                INSERT INTO portfolio_corporate_action_events
                  (broker_account_id, broker_instrument_id, import_run_id, raw_document_id,
                   action_date, action_type, quantity, cash_amount, currency, broker_action_id, metadata_json)
                VALUES
                  (:broker_account_id, :broker_instrument_id, :import_run_id, :raw_document_id,
                   :action_date, :action_type, :quantity, :cash_amount, :currency, :broker_action_id, {_platform_json_default(db)})
                """
            ),
            {
                "broker_account_id": broker_account_id,
                "broker_instrument_id": instrument_id,
                "import_run_id": import_run_id,
                "raw_document_id": raw_document_id,
                "action_date": action.action_date,
                "action_type": action.action_type,
                "quantity": _db_decimal(action.quantity),
                "cash_amount": _db_decimal(action.cash_amount),
                "currency": action.currency,
                "broker_action_id": action.broker_action_id,
            },
        )


def _insert_reconciliations(
    db: Session,
    *,
    broker_account_id: int,
    import_run_id: int,
    raw_document_id: int,
    statement: FlexStatement,
) -> None:
    positions_by_date: dict[date, Decimal] = {}
    for position in statement.positions:
        positions_by_date[position.report_date] = positions_by_date.get(position.report_date, Decimal("0")) + position.market_value_base
    cash_by_date: dict[date, Decimal] = {}
    for cash in statement.cash_balances:
        cash_by_date[cash.report_date] = cash_by_date.get(cash.report_date, Decimal("0")) + cash.cash_balance_base
    tolerance = Decimal("0.05")
    for nav in statement.nav_snapshots:
        expected = (
            positions_by_date.get(nav.report_date, Decimal("0"))
            + cash_by_date.get(nav.report_date, Decimal("0"))
            + nav.interest_accrual_base
            + nav.dividend_accrual_base
            + nav.options_base
            + nav.funds_base
            + nav.bonds_base
        )
        actual = nav.total_nav_base
        difference = actual - expected
        status = "passed" if abs(difference) <= tolerance else "warning"
        db.execute(
            text(
                f"""
                INSERT INTO portfolio_reconciliations
                  (broker_account_id, import_run_id, raw_document_id, report_date, reconciliation_type,
                   expected_amount, actual_amount, difference_amount, tolerance_amount, status, metadata_json)
                VALUES
                  (:broker_account_id, :import_run_id, :raw_document_id, :report_date, 'nav_vs_components',
                   :expected_amount, :actual_amount, :difference_amount, :tolerance_amount, :status, {_platform_json_default(db)})
                """
            ),
            {
                "broker_account_id": broker_account_id,
                "import_run_id": import_run_id,
                "raw_document_id": raw_document_id,
                "report_date": nav.report_date,
                "expected_amount": _db_decimal(expected),
                "actual_amount": _db_decimal(actual),
                "difference_amount": _db_decimal(difference),
                "tolerance_amount": _db_decimal(tolerance),
                "status": status,
            },
        )


def _insert_completeness(
    db: Session,
    *,
    broker_account_id: int,
    import_run_id: int,
    raw_document_id: int,
    report_date: date,
    fact_scope: str,
    completeness_status: str,
    missing_reason: str | None,
) -> None:
    db.execute(
        text(
            f"""
            INSERT INTO portfolio_data_completeness
              (broker_account_id, import_run_id, raw_document_id, report_date, fact_scope,
               completeness_status, missing_reason, metadata_json)
            VALUES
              (:broker_account_id, :import_run_id, :raw_document_id, :report_date, :fact_scope,
               :completeness_status, :missing_reason, {_platform_json_default(db)})
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "import_run_id": import_run_id,
            "raw_document_id": raw_document_id,
            "report_date": report_date,
            "fact_scope": fact_scope,
            "completeness_status": completeness_status,
            "missing_reason": missing_reason,
        },
    )


def run_ibkr_flex_import_from_xml(
    db: Session,
    *,
    current_user_id: int,
    legacy_account_id: int,
    xml_text: str,
    cutover_date: date | None = None,
    reference_code: str | None = None,
) -> dict[str, Any]:
    statement = parse_flex_statement(xml_text)
    effective_cutover_date = _resolve_cutover_date(statement, cutover_date)
    broker_account_id = _ensure_broker_account(
        db,
        current_user_id=current_user_id,
        legacy_account_id=legacy_account_id,
        broker_account_id=statement.broker_account_id,
        base_currency=statement.base_currency,
    )
    _ensure_authority_window(db, broker_account_id, effective_cutover_date)
    lock_owner = _try_acquire_lock(db, broker_account_id, SOURCE_TYPE)
    db.commit()

    import_run_id: int | None = None
    raw_document_id: int | None = None
    try:
        import_run_id = _create_import_run(
            db,
            broker_account_id=broker_account_id,
            legacy_account_id=legacy_account_id,
            statement=statement,
            reference_code=reference_code,
        )
        raw_document_id = _store_raw_xml(
            db,
            import_run_id=import_run_id,
            broker_account_id=broker_account_id,
            xml_text=xml_text,
            statement=statement,
        )
        _validate_statement(statement)
        _insert_statement_facts(
            db,
            broker_account_id=broker_account_id,
            legacy_account_id=legacy_account_id,
            import_run_id=import_run_id,
            raw_document_id=raw_document_id,
            statement=statement,
            cutover_date=effective_cutover_date,
        )
        _mark_import_completed(db, import_run_id)
        _release_lock(db, broker_account_id, lock_owner)
        db.commit()
    except IbkrFlexImportError as exc:
        _record_data_quality_event(
            db,
            broker_account_id=broker_account_id,
            import_run_id=import_run_id,
            raw_document_id=raw_document_id,
            report_date=statement.report_date_to,
            severity="error",
            event_code=exc.code,
            message=exc.message,
        )
        if raw_document_id is not None:
            _insert_completeness(
                db,
                broker_account_id=broker_account_id,
                import_run_id=import_run_id,
                raw_document_id=raw_document_id,
                report_date=statement.report_date_to,
                fact_scope="holdings_cash_nav_fx",
                completeness_status="failed",
                missing_reason=exc.code,
            )
        if import_run_id is not None:
            _mark_import_failed(db, import_run_id, exc.code, exc.message)
        _release_lock(db, broker_account_id, lock_owner)
        db.commit()
        raise
    except Exception:
        db.rollback()
        try:
            if import_run_id is not None:
                _mark_import_failed(db, import_run_id, "import_failed", "IBKR Flex import failed")
            _release_lock(db, broker_account_id, lock_owner)
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        raise

    return {
        "status": "IMPORTED",
        "platform": PLATFORM_CODE,
        "source_type": SOURCE_TYPE,
        "broker_account_id": broker_account_id,
        "import_run_id": import_run_id,
        "raw_document_id": raw_document_id,
        "report_date_from": statement.report_date_from.isoformat(),
        "report_date_to": statement.report_date_to.isoformat(),
        "counts": {
            "nav_snapshots": len(statement.nav_snapshots),
            "cash_balances": len(statement.cash_balances),
            "positions": len(statement.positions),
            "fx_rates": len(statement.fx_rates),
            "cash_ledger_entries": len(statement.cash_ledger_entries),
            "trades": len(statement.trades),
            "corporate_actions": len(statement.corporate_actions),
            "report_metrics": len(statement.report_metrics),
        },
    }


def run_ibkr_flex_import_from_config(
    db: Session,
    *,
    current_user_id: int,
    legacy_account_id: int,
    cutover_date: date | None = None,
) -> dict[str, Any]:
    max_attempts = int(os.getenv("IBKR_FLEX_MAX_ATTEMPTS", "5"))
    initial_backoff_seconds = float(
        _first_env_value("IBKR_FLEX_INITIAL_BACKOFF_SECONDS", "IBKR_FLEX_BACKOFF_SECONDS", default="2")
    )
    max_backoff_seconds = float(os.getenv("IBKR_FLEX_MAX_BACKOFF_SECONDS", "30"))
    reference_code, xml_text = IbkrFlexClient.from_env().fetch_statement(
        max_attempts=max_attempts,
        initial_backoff_seconds=initial_backoff_seconds,
        max_backoff_seconds=max_backoff_seconds,
    )
    return run_ibkr_flex_import_from_xml(
        db,
        current_user_id=current_user_id,
        legacy_account_id=legacy_account_id,
        xml_text=xml_text,
        cutover_date=cutover_date,
        reference_code=reference_code,
    )


def latest_authoritative_nav_by_legacy_account(
    db: Session,
    *,
    current_user_id: int,
    anchor_date: date,
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            WITH latest AS (
              SELECT ns.broker_account_id, MAX(ns.report_date) AS report_date
              FROM portfolio_nav_snapshots ns
              JOIN broker_accounts ba ON ba.id = ns.broker_account_id
              JOIN accounts acc ON acc.id = ba.legacy_account_id
              WHERE ns.report_date <= :anchor_date
                AND (
                  ns.authority_status = 'authoritative'
                  OR EXISTS (
                    SELECT 1
                    FROM portfolio_source_authority_windows aw
                    WHERE aw.broker_account_id = ns.broker_account_id
                      AND aw.source_kind = :source_kind
                      AND aw.fact_scope = 'all'
                      AND aw.authority_status = 'authoritative'
                      AND aw.effective_from <= ns.report_date
                      AND (aw.effective_to IS NULL OR aw.effective_to >= ns.report_date)
                  )
                )
                AND ba.legacy_account_id IS NOT NULL
                AND (acc.user_id = :current_user_id OR acc.user_id IS NULL)
              GROUP BY ns.broker_account_id
            )
            SELECT
              ba.legacy_account_id,
              ns.broker_account_id,
              ns.report_date,
              ns.base_currency,
              ns.cash_base,
              ns.stock_base,
              ns.total_nav_base,
              COALESCE(pl.code, acc.platform) AS platform,
              pl.platform_type AS platform_type,
              COALESCE(pl.country, acc.country) AS country
            FROM portfolio_nav_snapshots ns
            JOIN latest l ON l.broker_account_id = ns.broker_account_id AND l.report_date = ns.report_date
            JOIN broker_accounts ba ON ba.id = ns.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            LEFT JOIN platforms pl ON pl.id = acc.platform_id
            """
        ),
        {"anchor_date": anchor_date, "current_user_id": current_user_id, "source_kind": SOURCE_TYPE},
    ).mappings().all()
    return [dict(row) for row in rows]
