from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.valuation_cache import valuation_cached
from app.wealth_rollup_dirty import mark_rollups_dirty

PARSER_VERSION = "ibkr_flex_v1"
SOURCE_TYPE = "ibkr_flex_daily"
PLATFORM_CODE = "IBKR"
ALL_FACT_SCOPE = "all"
DEFAULT_IBKR_FLEX_BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
DEFAULT_IBKR_USER_AGENT = "curl/8.0"
DEFAULT_IMPORT_LOCK_STALE_MINUTES = 30.0

logger = logging.getLogger("capitalos.portfolio.ibkr_flex")


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
    # The security the cash line is about (dividend, withholding, trade), when any:
    # conid, symbol, security_description, asset_category, listing_exchange.
    security: dict[str, str] = field(default_factory=dict, compare=False, hash=False)


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
    # Rows or attributes the parser had to drop or could not read; recorded as
    # data-quality warnings by the import, never silently lost (#136).
    data_quality_warnings: list[tuple[str, str]] = field(default_factory=list)


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
    # Real Flex XML nests <StatementOfFundsLine> rows in one <StmtFunds> section
    # (#113: selecting "StmtFunds" itself matched only the empty container, so
    # every cash line was dropped). Older fixtures used <StmtFunds ... amount=>.
    stmt_fund_rows = [
        *_iter(root, "StatementOfFundsLine"),
        *[row for row in _iter(root, "StmtFunds") if _attr(row, "amount", "netCash") is not None],
    ]
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

    data_quality_warnings: list[tuple[str, str]] = []
    nav_missing_components: dict[str, int] = {}
    nav_missing_total_dates: list[date] = []
    nav_snapshots: list[FlexNavSnapshot] = []
    for row in nav_rows:
        report_date = _date(_attr(row, "reportDate", "date"), to_date)
        if report_date is None:
            continue
        # IBKR always sends cash and stock on an equity-summary row; a missing one
        # means the attribute was renamed, so the 0 used below is a guess (#136).
        for component, names in (("cash", ("cash", "cashBase")), ("stock", ("stock", "stocks", "stockBase"))):
            if _decimal(_attr(row, *names)) is None:
                nav_missing_components[component] = nav_missing_components.get(component, 0) + 1
        cash = _decimal(_attr(row, "cash", "cashBase"), Decimal("0")) or Decimal("0")
        stock = _decimal(_attr(row, "stock", "stocks", "stockBase"), Decimal("0")) or Decimal("0")
        options = _decimal(_attr(row, "options", "optionBase"), Decimal("0")) or Decimal("0")
        funds = _decimal(_attr(row, "funds", "fundBase"), Decimal("0")) or Decimal("0")
        bonds = _decimal(_attr(row, "bonds", "bondBase"), Decimal("0")) or Decimal("0")
        interest_accruals = _decimal(_attr(row, "interestAccruals", "interestAccrual"), Decimal("0")) or Decimal("0")
        dividend_accruals = _decimal(_attr(row, "dividendAccruals", "dividendAccrual"), Decimal("0")) or Decimal("0")
        total = _decimal(_attr(row, "total", "totalNav", "totalEquity", "netLiquidation"))
        if total is None:
            # The total is the account's net worth. Summing components that may
            # themselves have defaulted to 0 would fabricate it, so the import
            # fails instead (#136).
            nav_missing_total_dates.append(report_date)
            continue
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

    if nav_missing_total_dates:
        data_quality_errors.append(
            (
                "missing_nav_total",
                f"{len(nav_missing_total_dates)} equity summary row(s) have no total NAV attribute "
                f"(first {min(nav_missing_total_dates).isoformat()})",
            )
        )
    for component, count in sorted(nav_missing_components.items()):
        data_quality_warnings.append(
            (
                "missing_nav_component",
                f"{count} equity summary row(s) have no {component} attribute; read as 0",
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
    skipped_positions: dict[str, list[str]] = {}
    for row in position_rows:
        report_date = _date(_attr(row, "reportDate", "date"), to_date)
        broker_instrument_id = _attr(row, "conid", "contractId", "figi", "isin")
        currency = _currency(_attr(row, "currency"))
        if report_date is None or not broker_instrument_id or currency is None:
            missing = "report date" if report_date is None else "conid" if not broker_instrument_id else "currency"
            skipped_positions.setdefault(missing, []).append(_attr(row, "symbol") or "?")
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

    for missing, symbols in sorted(skipped_positions.items()):
        shown = ", ".join(symbols[:5]) + (", ..." if len(symbols) > 5 else "")
        data_quality_warnings.append(
            (
                "skipped_position_row",
                f"{len(symbols)} OpenPosition row(s) skipped: no {missing} ({shown})",
            )
        )

    cash_ledger_entries: list[FlexCashLedgerEntry] = []
    for row in stmt_fund_rows:
        currency = _currency(_attr(row, "currency"))
        amount = _decimal(_attr(row, "amount", "netCash"))
        activity_date = _date(_attr(row, "date", "tradeDate", "reportDate"), to_date)
        if currency is None or amount is None or activity_date is None:
            continue
        has_activity_text = _attr(row, "activityDescription") is not None
        security = {
            key: value
            for key, value in (
                ("conid", _attr(row, "conid")),
                ("symbol", _attr(row, "symbol")),
                # On a StatementOfFundsLine `description` is the security's name and
                # `activityDescription` the cash event's own text.
                ("security_description", _attr(row, "description") if has_activity_text else None),
                ("asset_category", _attr(row, "assetCategory")),
                ("listing_exchange", _attr(row, "listingExchange")),
            )
            if value
        }
        cash_ledger_entries.append(
            FlexCashLedgerEntry(
                activity_date=activity_date,
                currency=currency,
                amount=amount,
                activity_code=_attr(row, "activityCode", "code"),
                description=_attr(row, "activityDescription", "description"),
                broker_activity_id=_attr(row, "transactionID", "transactionId", "id") or None,
                security=security,
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
        data_quality_warnings=data_quality_warnings,
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
        missing = [name for name, value in (("IBKR_FLEX_TOKEN", token), ("IBKR_FLEX_QUERY_ID", query_id)) if not value]
        if missing:
            raise IbkrFlexConfigError(f"IBKR Flex isn't set up: {' and '.join(missing)} missing in .env.")
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


def _ensure_authority_window(db: Session, broker_account_id: int, cutover_date: date) -> bool:
    """Create the Flex authority window if missing. True when it was created."""
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
        return False
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
    return True


def _create_import_run(
    db: Session,
    *,
    broker_account_id: int | None,
    legacy_account_id: int,
    reference_code: str | None,
) -> int:
    """Open a run row before the XML is parsed (#136).

    The broker account and report dates come from the statement, so they may be
    unknown here; ``_attach_statement_to_run`` fills them in after parsing.
    """
    row = db.execute(
        text(
            f"""
            INSERT INTO broker_import_runs
              (broker_account_id, legacy_account_id, platform_code, source_type, import_scope, status,
               started_at, flex_reference_code, parser_version, metadata_json)
            VALUES
              (:broker_account_id, :legacy_account_id, 'IBKR', :source_type, 'daily', 'started',
               :started_at, :reference_code, :parser_version, {_platform_json_default(db)})
            RETURNING id
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "legacy_account_id": legacy_account_id,
            "source_type": SOURCE_TYPE,
            "started_at": _now(),
            "reference_code": reference_code,
            "parser_version": PARSER_VERSION,
        },
    ).fetchone()
    return int(row[0])


def _known_broker_account(db: Session, *, current_user_id: int, legacy_account_id: int) -> int | None:
    """The Flex broker account already linked to this legacy account, if any.

    Used before parsing so a run whose XML can't be read still shows under the
    account in the import-run list (which joins on broker_account_id).
    """
    row = db.execute(
        text(
            """
            SELECT ba.id
            FROM broker_accounts ba
            JOIN broker_connections bc ON bc.id = ba.connection_id
            WHERE bc.user_id = :user_id
              AND bc.platform_code = 'IBKR'
              AND bc.connection_type = 'flex_api'
              AND ba.legacy_account_id = :legacy_account_id
            ORDER BY ba.id
            LIMIT 1
            """
        ),
        {"user_id": current_user_id, "legacy_account_id": legacy_account_id},
    ).fetchone()
    return int(row[0]) if row else None


def _attach_statement_to_run(
    db: Session,
    *,
    import_run_id: int,
    raw_document_id: int,
    broker_account_id: int,
    statement: FlexStatement,
) -> None:
    params = {
        "broker_account_id": broker_account_id,
        "report_date_from": statement.report_date_from,
        "report_date_to": statement.report_date_to,
    }
    db.execute(
        text(
            """
            UPDATE broker_import_runs
            SET broker_account_id = :broker_account_id,
                report_date_from = :report_date_from,
                report_date_to = :report_date_to,
                parsed_at = :parsed_at,
                updated_at = :parsed_at
            WHERE id = :import_run_id
            """
        ),
        {**params, "parsed_at": _now(), "import_run_id": import_run_id},
    )
    db.execute(
        text(
            """
            UPDATE raw_broker_documents
            SET broker_account_id = :broker_account_id,
                report_date_from = :report_date_from,
                report_date_to = :report_date_to
            WHERE id = :raw_document_id
            """
        ),
        {**params, "raw_document_id": raw_document_id},
    )


def _failure_message(exc: BaseException) -> tuple[str, str]:
    """(error_code, message) for a failed run: the error class and its text.

    Parser messages name attributes and XML positions, not values; the Flex
    token never reaches the parser. Capped so a pathological message can't
    flood the run row.
    """
    if isinstance(exc, IbkrFlexImportError):
        return exc.code, exc.message[:500]
    detail = str(exc).strip()
    message = f"{exc.__class__.__name__}: {detail}" if detail else exc.__class__.__name__
    return "parse_failed", message[:500]


def import_lock_stale_after() -> timedelta:
    """How old an import lock may get before a new import takes it over (#135).

    A process killed mid-import (``uvicorn --reload``, a deploy, a crash) never
    deletes its row; without a limit every later import would 409 forever.
    """
    raw = os.getenv("IBKR_IMPORT_LOCK_STALE_MINUTES", "").strip()
    try:
        minutes = float(raw) if raw else DEFAULT_IMPORT_LOCK_STALE_MINUTES
    except ValueError:
        minutes = DEFAULT_IMPORT_LOCK_STALE_MINUTES
    if minutes <= 0:
        minutes = DEFAULT_IMPORT_LOCK_STALE_MINUTES
    return timedelta(minutes=minutes)


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _try_acquire_lock(db: Session, broker_account_id: int, source_type: str) -> str:
    owner = str(uuid.uuid4())
    now = _now()
    inserted = db.execute(
        text(
            """
            INSERT INTO portfolio_import_locks (broker_account_id, source_type, lock_owner, locked_at)
            VALUES (:broker_account_id, :source_type, :lock_owner, :locked_at)
            ON CONFLICT (broker_account_id) DO NOTHING
            """
        ),
        {
            "broker_account_id": broker_account_id,
            "source_type": source_type,
            "lock_owner": owner,
            "locked_at": now,
        },
    )
    if inserted.rowcount == 1:
        db.flush()
        return owner

    existing = db.execute(
        text(
            """
            SELECT lock_owner, locked_at
            FROM portfolio_import_locks
            WHERE broker_account_id = :broker_account_id
            """
        ),
        {"broker_account_id": broker_account_id},
    ).fetchone()
    locked_at = _as_utc(existing[1]) if existing is not None else None
    stale_after = import_lock_stale_after()
    # A row with an unreadable timestamp can't be proven live, so it counts as stale.
    if existing is not None and (locked_at is None or now - locked_at > stale_after):
        # Compare-and-swap on the previous owner: if two imports race for the same
        # stale row, exactly one UPDATE matches and the other is refused below.
        taken = db.execute(
            text(
                """
                UPDATE portfolio_import_locks
                SET lock_owner = :lock_owner, source_type = :source_type, locked_at = :locked_at
                WHERE broker_account_id = :broker_account_id
                  AND lock_owner = :previous_owner
                """
            ),
            {
                "broker_account_id": broker_account_id,
                "source_type": source_type,
                "lock_owner": owner,
                "locked_at": now,
                "previous_owner": existing[0],
            },
        )
        if taken.rowcount == 1:
            db.flush()
            logger.warning(
                "ibkr_flex_stale_import_lock_taken_over",
                extra={
                    "event": "ibkr_flex_stale_import_lock_taken_over",
                    "provider": "ibkr_flex",
                    "platform": PLATFORM_CODE,
                    "broker_account_id": broker_account_id,
                    "lock_age_seconds": int((now - locked_at).total_seconds()) if locked_at else None,
                    "stale_after_seconds": int(stale_after.total_seconds()),
                },
            )
            return owner

    db.rollback()
    raise IbkrFlexImportInProgress("IBKR Flex import already in progress for this account")


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
    broker_account_id: int | None,
    xml_text: str,
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
               'application/xml', NULL, NULL, :parser_version, {_platform_json_default(db)})
            """
        ),
        {
            "import_run_id": import_run_id,
            "broker_account_id": broker_account_id,
            "source_type": SOURCE_TYPE,
            "content_hash": content_hash,
            "storage_path": str(storage_path),
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


@dataclass(frozen=True)
class FactScopes:
    """Per-table report dates one Flex statement actually speaks for (#134).

    A multi-day Flex report carries EquitySummaryByReportDateInBase (NAV) for every
    day, but OpenPosition and CashReportCurrency rows only for the period end. Each
    table is cleared and rewritten only on the dates the report carries for it, so
    a 365-day backfill no longer wipes the positions and cash of earlier daily
    imports. The period end (``toDate``) counts as carried for positions and cash
    whenever the report has NAV for it: an empty OpenPositions section there means
    "no positions", and a stale holding must not survive a re-import of that date.
    """

    nav: frozenset[date]
    positions: frozenset[date]
    cash: frozenset[date]
    metrics: frozenset[date]

    @property
    def holdings(self) -> frozenset[date]:
        """Dates on which the report carries positions or cash."""
        return self.positions | self.cash

    @property
    def reconciled(self) -> frozenset[date]:
        """Dates with NAV, positions and cash all in the report: NAV vs components is checked there."""
        return self.nav & self.positions & self.cash

    @property
    def nav_only(self) -> frozenset[date]:
        """Dates on which the report carries NAV but neither positions nor cash."""
        return self.nav - self.holdings


def _fact_scopes(statement: FlexStatement) -> FactScopes:
    nav_dates = {nav.report_date for nav in statement.nav_snapshots}
    position_dates = {position.report_date for position in statement.positions}
    cash_dates = {cash.report_date for cash in statement.cash_balances}
    if statement.report_date_to in nav_dates:
        position_dates.add(statement.report_date_to)
        cash_dates.add(statement.report_date_to)
    metric_dates = {metric.report_date for metric in statement.report_metrics} | cash_dates
    return FactScopes(
        nav=frozenset(nav_dates),
        positions=frozenset(position_dates),
        cash=frozenset(cash_dates),
        metrics=frozenset(metric_dates),
    )


def _authority_status(report_date: date, cutover_date: date) -> str:
    return "authoritative" if report_date >= cutover_date else "reference"


def _resolve_cutover_date(statement: FlexStatement, cutover_date: date | None) -> date:
    return cutover_date or statement.report_date_from


def _clear_existing_authoritative_facts(db: Session, broker_account_id: int, scopes: FactScopes) -> None:
    # Each table only on the dates this report rewrites it (#134). The cash ledger,
    # trades and corporate actions are replaced row by row in their own inserts.
    dates_by_table: tuple[tuple[str, frozenset[date]], ...] = (
        ("portfolio_position_snapshots", scopes.positions),
        ("portfolio_cash_balance_snapshots", scopes.cash),
        ("portfolio_nav_snapshots", scopes.nav),
        ("portfolio_report_metrics", scopes.metrics),
        ("portfolio_reconciliations", scopes.reconciled),
        ("portfolio_data_completeness", scopes.nav | scopes.holdings),
    )
    for table_name, report_dates in dates_by_table:
        for report_date in sorted(report_dates):
            db.execute(
                text(f"DELETE FROM {table_name} WHERE broker_account_id = :broker_account_id AND report_date = :report_date"),
                {"broker_account_id": broker_account_id, "report_date": report_date},
            )


HOLDINGS_FACT_SCOPE = "holdings_cash_nav_fx"
NAV_ONLY_STATUS = "nav_only"
NAV_ONLY_REASON = "holdings_not_in_report"


def _holdings_completeness_status(
    db: Session, broker_account_id: int, report_date: date, stock_base: Decimal | None
) -> tuple[str, str | None]:
    """Completeness of a date the latest report carried only NAV for (#134).

    'complete' when the stored facts still hold cash for the date and positions (or
    the NAV says there is no stock); otherwise 'nav_only': NAV is known, holdings are not.
    """
    params = {"broker_account_id": broker_account_id, "report_date": report_date}
    has_cash = db.execute(
        text(
            "SELECT 1 FROM portfolio_cash_balance_snapshots "
            "WHERE broker_account_id = :broker_account_id AND report_date = :report_date LIMIT 1"
        ),
        params,
    ).fetchone()
    has_positions = db.execute(
        text(
            "SELECT 1 FROM portfolio_position_snapshots "
            "WHERE broker_account_id = :broker_account_id AND report_date = :report_date LIMIT 1"
        ),
        params,
    ).fetchone()
    positions_known = has_positions is not None or (stock_base is not None and stock_base == Decimal("0"))
    if has_cash is not None and positions_known:
        return "complete", None
    return NAV_ONLY_STATUS, NAV_ONLY_REASON


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
    instrument_id = _ensure_broker_instrument_values(
        db,
        broker_instrument_id=position.broker_instrument_id,
        symbol=position.symbol,
        description=position.description,
        security_type=position.security_type,
        listing_exchange=position.listing_exchange,
        currency=position.currency,
    )
    _link_priced_asset(db, instrument_id, position)
    return instrument_id


# IBKR listing exchange -> (market_symbol_map exchange code, home country) (#124).
_PRICE_JOB_EXCHANGES = {
    "NYSE": ("US", "US"),
    "NASDAQ": ("US", "US"),
    "ARCA": ("US", "US"),
    "NYSEARCA": ("US", "US"),
    "AMEX": ("US", "US"),
    "BATS": ("US", "US"),
    "IEX": ("US", "US"),
    "PINK": ("US", "US"),
    "SEHK": ("HKEX", "HK"),
    "SGX": ("SGX", "SG"),
    "NSE": ("NSE", "IN"),
}
_PRICED_SECURITY_TYPES = {"STK": "STOCK", "ETF": "FUND", "FUND": "FUND"}


def _asset_symbol_candidates(symbol: str, exchange_code: str) -> list[str]:
    """IBKR spellings vs the app's: "BRK B" is "BRK-B"; HK "700" may be "0700"."""
    base = symbol.strip().upper()
    candidates = [base, base.replace(" ", "-"), base.replace(" ", ".")]
    if exchange_code == "HKEX" and base.isdigit():
        candidates += [base.zfill(4), base.lstrip("0") or base]
    return list(dict.fromkeys(candidates))


def _link_priced_asset(db: Session, instrument_id: int, position: FlexPosition) -> None:
    """Every IBKR stock/ETF holding gets an `assets` row (linked from its broker
    instrument) and a `market_symbol_map` entry, so the price job fetches its quote.
    Before this only holdings that happened to have a seeded asset were priced (#124)."""
    asset_class = _PRICED_SECURITY_TYPES.get(str(position.security_type or "").upper())
    exchange = _PRICE_JOB_EXCHANGES.get(str(position.listing_exchange or "").upper())
    if asset_class is None or exchange is None or not position.symbol or not position.currency:
        return
    exchange_code, home_country = exchange
    currency = position.currency.upper()
    linked = db.execute(
        text("SELECT asset_id FROM broker_instruments WHERE id = :id"), {"id": instrument_id}
    ).scalar()
    asset_id = int(linked) if linked is not None else None
    candidates = _asset_symbol_candidates(position.symbol, exchange_code)
    if asset_id is None:
        for candidate in candidates:
            row = db.execute(
                text("SELECT id FROM assets WHERE UPPER(symbol) = :symbol AND UPPER(quote_currency) = :currency LIMIT 1"),
                {"symbol": candidate, "currency": currency},
            ).fetchone()
            if row:
                asset_id = int(row[0])
                break
    if asset_id is None:
        from app.portfolio.upload_canonical import _get_or_create_asset

        asset_id = _get_or_create_asset(
            db,
            symbol=position.symbol.strip().upper().replace(" ", "-"),
            currency=currency,
            name=position.description,
            asset_class=asset_class,
            home_country=home_country,
        )
        if asset_id is None:
            return
    db.execute(
        text("UPDATE broker_instruments SET asset_id = :asset_id WHERE id = :id AND asset_id IS NULL"),
        {"asset_id": asset_id, "id": instrument_id},
    )
    has_map = db.execute(
        text("SELECT 1 FROM market_symbol_map WHERE asset_id = :asset_id AND exchange_code = :exchange_code"),
        {"asset_id": asset_id, "exchange_code": exchange_code},
    ).fetchone()
    if has_map:
        return
    asset_symbol = db.execute(text("SELECT symbol FROM assets WHERE id = :id"), {"id": asset_id}).scalar()
    db.execute(
        text(
            """
            INSERT INTO market_symbol_map
              (asset_id, exchange_code, exchange_symbol, quote_currency, is_active, created_at, updated_at)
            VALUES
              (:asset_id, :exchange_code, :exchange_symbol, :quote_currency, TRUE, :now, :now)
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "asset_id": asset_id,
            "exchange_code": exchange_code,
            "exchange_symbol": str(asset_symbol or candidates[0]).upper(),
            "quote_currency": currency,
            "now": _now(),
        },
    )


def _insert_position_snapshot(
    db: Session,
    *,
    broker_account_id: int,
    legacy_account_id: int | None,
    import_run_id: int,
    raw_document_id: int,
    position: FlexPosition,
    authority_status: str,
) -> None:
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
            "authority_status": authority_status,
        },
    )


def _insert_cash_balance_snapshot(
    db: Session,
    *,
    broker_account_id: int,
    legacy_account_id: int | None,
    import_run_id: int,
    raw_document_id: int,
    cash: FlexCashBalance,
    authority_status: str,
) -> None:
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
            "authority_status": authority_status,
        },
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
    scopes = _fact_scopes(statement)
    _clear_existing_authoritative_facts(db, broker_account_id, scopes)

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
        _insert_position_snapshot(
            db,
            broker_account_id=broker_account_id,
            legacy_account_id=legacy_account_id,
            import_run_id=import_run_id,
            raw_document_id=raw_document_id,
            position=position,
            authority_status=_authority_status(position.report_date, cutover_date),
        )

    for cash in statement.cash_balances:
        _insert_cash_balance_snapshot(
            db,
            broker_account_id=broker_account_id,
            legacy_account_id=legacy_account_id,
            import_run_id=import_run_id,
            raw_document_id=raw_document_id,
            cash=cash,
            authority_status=_authority_status(cash.report_date, cutover_date),
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
        report_dates=scopes.reconciled,
    )
    stock_by_date = {nav.report_date: nav.stock_base for nav in statement.nav_snapshots}
    for report_date in sorted(scopes.nav | scopes.holdings):
        if report_date in scopes.holdings:
            completeness_status, missing_reason = "complete", None
        else:
            completeness_status, missing_reason = _holdings_completeness_status(
                db, broker_account_id, report_date, stock_by_date.get(report_date)
            )
        _insert_completeness(
            db,
            broker_account_id=broker_account_id,
            import_run_id=import_run_id,
            raw_document_id=raw_document_id,
            report_date=report_date,
            fact_scope=HOLDINGS_FACT_SCOPE,
            completeness_status=completeness_status,
            missing_reason=missing_reason,
        )


def _insert_cash_ledger_entries(
    db: Session,
    *,
    broker_account_id: int,
    import_run_id: int,
    raw_document_id: int,
    entries: list[FlexCashLedgerEntry],
) -> None:
    is_postgres = bool(db.bind and db.bind.dialect.name == "postgresql")
    json_value = "CAST(:metadata_json AS JSONB)" if is_postgres else ":metadata_json"
    # Replace rules (#157):
    # - A line with an IBKR transaction id is that transaction: every stored line
    #   with the id is replaced by this report's lines with it, whatever their date,
    #   amount or text (a re-issued line with edited text replaces, never doubles;
    #   D-20 reads dividends from here). The same line listed twice in one report
    #   is stored once (uq_portfolio_cash_ledger_activity_id).
    # - Lines without an id can't be told apart from their values, so they are
    #   counted: on a date the report covers, the stored lines with a key are
    #   replaced by the report's lines with that key, as many as the report has
    #   (two identical FX adjustments on one day are both kept).
    replaced_ids: set[str] = set()
    seen_id_lines: set[tuple[Any, ...]] = set()
    replaced_idless_keys: set[tuple[Any, ...]] = set()
    for entry in entries:
        activity_id = (entry.broker_activity_id or "").strip() or None
        if activity_id is not None:
            line = (
                activity_id,
                entry.activity_date,
                entry.currency,
                entry.amount,
                entry.activity_code or "",
                entry.description or "",
            )
            if line in seen_id_lines:
                continue
            seen_id_lines.add(line)
            if activity_id not in replaced_ids:
                replaced_ids.add(activity_id)
                db.execute(
                    text(
                        """
                        DELETE FROM portfolio_cash_ledger_entries
                        WHERE broker_account_id = :broker_account_id
                          AND broker_activity_id = :broker_activity_id
                        """
                    ),
                    {"broker_account_id": broker_account_id, "broker_activity_id": activity_id},
                )
        else:
            key = (
                entry.activity_date,
                entry.currency,
                entry.amount,
                entry.activity_code or "",
                entry.description or "",
            )
            if key not in replaced_idless_keys:
                replaced_idless_keys.add(key)
                db.execute(
                    text(
                        """
                        DELETE FROM portfolio_cash_ledger_entries
                        WHERE broker_account_id = :broker_account_id
                          AND activity_date = :activity_date
                          AND currency = :currency
                          AND amount = :amount
                          AND COALESCE(activity_code, '') = COALESCE(:activity_code, '')
                          AND COALESCE(broker_activity_id, '') = ''
                          AND COALESCE(description, '') = COALESCE(:description, '')
                        """
                    ),
                    {
                        "broker_account_id": broker_account_id,
                        "activity_date": entry.activity_date,
                        "currency": entry.currency,
                        "amount": _db_decimal(entry.amount),
                        "activity_code": entry.activity_code,
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
                   :activity_code, :description, :broker_activity_id, {json_value})
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
                "broker_activity_id": activity_id,
                "metadata_json": json.dumps({"security": entry.security} if entry.security else {}),
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
    # A trade with an execution id is replaced by that id alone. Trades without one
    # are counted (#157): the stored trades with the same values on that date are
    # replaced once by all of this report's trades with them, so two identical
    # fills both stay and a re-import doesn't double them.
    replaced_idless_keys: set[tuple[Any, ...]] = set()
    for trade in trades:
        instrument_id = _optional_instrument_for_trade(db, trade)
        idless_key = (
            trade.trade_date,
            instrument_id,
            trade.currency,
            trade.side,
            trade.quantity,
            trade.price,
            trade.proceeds,
        )
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
        elif idless_key not in replaced_idless_keys:
            replaced_idless_keys.add(idless_key)
            db.execute(
                text(
                    """
                    DELETE FROM portfolio_trades
                    WHERE broker_account_id = :broker_account_id
                      AND COALESCE(broker_execution_id, '') = ''
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
                # An empty ibExecID is no id: stored NULL so uq_portfolio_trades_execution
                # doesn't treat two id-less fills as the same execution.
                "broker_execution_id": trade.broker_execution_id or None,
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
    report_dates: frozenset[date],
) -> None:
    # Only dates whose positions and cash are in this report: on a NAV-only date the
    # components are unknown, and comparing NAV to zero would fabricate a warning (#134).
    positions_by_date: dict[date, Decimal] = {}
    for position in statement.positions:
        positions_by_date[position.report_date] = positions_by_date.get(position.report_date, Decimal("0")) + position.market_value_base
    cash_by_date: dict[date, Decimal] = {}
    for cash in statement.cash_balances:
        cash_by_date[cash.report_date] = cash_by_date.get(cash.report_date, Decimal("0")) + cash.cash_balance_base
    tolerance = Decimal("0.05")
    for nav in statement.nav_snapshots:
        if nav.report_date not in report_dates:
            continue
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
    # Evidence first (#136): the run row and the raw XML are committed before the
    # XML is parsed, so a statement that can't be read still leaves both behind,
    # plus a data-quality event naming the error.
    import_run_id = _create_import_run(
        db,
        broker_account_id=_known_broker_account(db, current_user_id=current_user_id, legacy_account_id=legacy_account_id),
        legacy_account_id=legacy_account_id,
        reference_code=reference_code,
    )
    raw_document_id = _store_raw_xml(
        db,
        import_run_id=import_run_id,
        broker_account_id=None,
        xml_text=xml_text,
    )
    db.commit()

    parsed = False
    try:
        statement = parse_flex_statement(xml_text)
        parsed = True
        effective_cutover_date = _resolve_cutover_date(statement, cutover_date)
        broker_account_id = _ensure_broker_account(
            db,
            current_user_id=current_user_id,
            legacy_account_id=legacy_account_id,
            broker_account_id=statement.broker_account_id,
            base_currency=statement.base_currency,
        )
        _attach_statement_to_run(
            db,
            import_run_id=import_run_id,
            raw_document_id=raw_document_id,
            broker_account_id=broker_account_id,
            statement=statement,
        )
        if _ensure_authority_window(db, broker_account_id, effective_cutover_date):
            # A new authority window changes which source counts from its date on (#138).
            mark_rollups_dirty(db, effective_cutover_date, account_id=legacy_account_id, reason="ibkr_flex_authority")
        # The stale-lock takeover rules (#135) live in _try_acquire_lock; on a live
        # lock it rolls back and raises IbkrFlexImportInProgress.
        lock_owner = _try_acquire_lock(db, broker_account_id, SOURCE_TYPE)
        db.commit()
    except Exception as exc:
        db.rollback()
        if isinstance(exc, IbkrFlexImportInProgress):
            code, message = "import_in_progress", str(exc)
        elif parsed and not isinstance(exc, IbkrFlexImportError):
            # A database error's text carries SQL and bound values: name the class only.
            code, message = "import_failed", f"IBKR Flex import failed ({exc.__class__.__name__})"
        else:
            code, message = _failure_message(exc)
        try:
            run_broker_account_id = db.execute(
                text("SELECT broker_account_id FROM broker_import_runs WHERE id = :id"),
                {"id": import_run_id},
            ).scalar()
            _record_data_quality_event(
                db,
                broker_account_id=run_broker_account_id,
                import_run_id=import_run_id,
                raw_document_id=raw_document_id,
                report_date=None,
                severity="error",
                event_code=code,
                message=message,
            )
            _mark_import_failed(db, import_run_id, code, message)
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("ibkr_flex_failed_run_not_recorded", extra={"event": "ibkr_flex_failed_run_not_recorded"})
        raise

    def _record_parser_warnings() -> None:
        for code, message in statement.data_quality_warnings:
            _record_data_quality_event(
                db,
                broker_account_id=broker_account_id,
                import_run_id=import_run_id,
                raw_document_id=raw_document_id,
                report_date=statement.report_date_to,
                severity="warning",
                event_code=code,
                message=message,
            )

    try:
        _record_parser_warnings()
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
        # NAV, cash and positions were (re)written for these report dates: History
        # rows anchored on or after the earliest are recomputed (#138).
        _scopes = _fact_scopes(statement)
        mark_rollups_dirty(
            db,
            min(_scopes.nav | _scopes.holdings | _scopes.metrics, default=statement.report_date_to),
            account_id=legacy_account_id,
            reason="ibkr_flex",
        )
        _release_lock(db, broker_account_id, lock_owner)
        db.commit()
    except IbkrFlexImportError as exc:
        # Nothing written for this statement survives a failed import (#136);
        # the warnings and the error are recorded afresh.
        db.rollback()
        _record_parser_warnings()
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


def _authorized_flex_user_id(db: Session) -> int:
    """Resolve which single user is allowed to trigger/receive IBKR Flex imports.

    IBKR_FLEX_TOKEN/IBKR_FLEX_QUERY_ID are one global set of credentials for
    one real IBKR account, shared by every user in this deployment — there is
    no per-user IBKR key. Without this check, any authenticated user with an
    accounts row on platform 'IBKR' (including the seeded demo user) could
    trigger a real import of that one shared account's data into their own
    records. Require an explicit owner instead of trusting the caller.
    """
    username = os.getenv("IBKR_FLEX_USERNAME", "").strip()
    if username:
        row = db.execute(
            text(
                """
                SELECT id
                FROM users
                WHERE LOWER(username) = LOWER(:username)
                  AND COALESCE(is_active, TRUE) = TRUE
                LIMIT 1
                """
            ),
            {"username": username},
        ).fetchone()
        if row is None:
            raise IbkrFlexConfigError(f"IBKR_FLEX_USERNAME={username!r} does not match an active user.")
        return int(row[0])

    raw = os.getenv("IBKR_FLEX_USER_ID", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError as exc:
            raise IbkrFlexConfigError(f"IBKR_FLEX_USER_ID={raw!r} is not a valid integer.") from exc

    raise IbkrFlexConfigError(
        "IBKR Flex isn't set up: IBKR_FLEX_USERNAME missing in .env (the user who owns the IBKR account)."
    )


def run_ibkr_flex_import_from_config(
    db: Session,
    *,
    current_user_id: int,
    legacy_account_id: int,
    cutover_date: date | None = None,
) -> dict[str, Any]:
    # Credentials first, so a missing token is reported as that (#121), not as a
    # missing owner.
    client = IbkrFlexClient.from_env()
    authorized_user_id = _authorized_flex_user_id(db)
    if current_user_id != authorized_user_id:
        raise IbkrFlexConfigError(
            f"User {current_user_id} is not authorized to trigger IBKR Flex import "
            f"(configured owner is user {authorized_user_id})."
        )
    max_attempts = int(os.getenv("IBKR_FLEX_MAX_ATTEMPTS", "5"))
    initial_backoff_seconds = float(
        _first_env_value("IBKR_FLEX_INITIAL_BACKOFF_SECONDS", "IBKR_FLEX_BACKOFF_SECONDS", default="2")
    )
    max_backoff_seconds = float(os.getenv("IBKR_FLEX_MAX_BACKOFF_SECONDS", "30"))
    reference_code, xml_text = client.fetch_statement(
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


@valuation_cached(shared=True)
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
