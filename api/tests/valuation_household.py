"""A synthetic household for the valuation harness (#142).

Fixed inputs that touch every valuation path the dashboard has today, built
through the real write paths where one exists (IBKR Flex XML import, the
upload balance adapter) and plain inserts elsewhere (accounts, prices, wallet
snapshots, transactions, FX rates). Every name, number and identifier here is
made up.

User A (``USER_A``) holds:
- a DBS savings account (SGD) and an HSBC account in USD, balances uploaded on
  several dates;
- an IBKR account (account currency USD, Flex base currency SGD) imported from
  synthetic Flex statements: NAV, two holdings (USD and HKD), cash in two
  currencies, dividends in the Statement of Funds. Before Flex took over it had
  one uploaded balance (December);
- a Sharekhan account (INR) with uploaded holdings, priced by the price job;
- a credit card (with a ``credit_card_accounts`` row) whose spending is the
  liability, and a CREDIT_CARD account without one that holds a bank balance
  uploaded to it by mistake (the #180 case);
- two active crypto wallets (one with stablecoins) and an inactive one;
- income, spending and dividend transactions in three currencies.

User B (``USER_B``) has a bank account, a card and a wallet of their own, so a
test can check that none of it reaches user A's numbers.

FX rates are stored in ``fx_rates`` (EUR-based, like ECB data), different every
month and never 1.0; providers are switched off, so only these rates are used.
The clock is frozen by ``freeze_clock``: "now" is the same instant in every
module that reads it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import datetime as _real_datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ingestion.parsers.base import ParseResult
from app.portfolio.ibkr_flex import run_ibkr_flex_import_from_xml
from app.portfolio.upload_canonical import run_upload_balance_canonical_adapter
from tests.canonical_test_helpers import seed_canonical_position_snapshot_for_test

SGT = ZoneInfo("Asia/Singapore")

USER_A = 1  # = conftest.TEST_USER_ID: the user the `client` fixture signs in as (#154)
USER_B = 2

DBS_SAVINGS = 101
HSBC_USD = 102
IBKR = 103
SHAREKHAN = 104
DBS_CARD = 105
MISFILED_CARD = 106  # CREDIT_CARD account with a savings balance uploaded to it (#180)
B_BANK = 201
B_CARD = 202

AAPL, TENCENT, RELIANCE, INFY = 1, 2, 3, 4

# Frozen "now" for each scenario.
#  mid:   a normal day: March is the open month, February closed.
#  first: the 1st of a month at 06:00 SGT, which is still the 31st in UTC, so
#         the month-end anchor (00:00Z on the 1st) hasn't passed yet.
SCENARIOS: dict[str, datetime] = {
    "mid": datetime(2026, 3, 18, 10, 0, tzinfo=SGT),
    "first": datetime(2026, 4, 1, 6, 0, tzinfo=SGT),
}


# ─── Frozen clock ────────────────────────────────────────────────────────────


class _FrozenMeta(type):
    """Stands in for ``datetime`` in a module: everything is the real class
    except ``now``/``utcnow``/``today``. Constructors and ``isinstance`` behave
    exactly as with the real class (instances are real datetimes)."""

    frozen_at: _real_datetime

    def __instancecheck__(cls, obj: Any) -> bool:
        return isinstance(obj, _real_datetime)

    def __subclasscheck__(cls, sub: type) -> bool:
        return issubclass(sub, _real_datetime)

    def __getattr__(cls, name: str) -> Any:
        return getattr(_real_datetime, name)

    def __call__(cls, *args: Any, **kwargs: Any) -> _real_datetime:
        return _real_datetime(*args, **kwargs)


def _frozen_datetime(when: datetime) -> type:
    instant = when.astimezone(timezone.utc)

    class FrozenDatetime(metaclass=_FrozenMeta):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return instant.replace(tzinfo=None)

        @classmethod
        def today(cls):
            return instant.replace(tzinfo=None)

    return FrozenDatetime


# Every module on the valuation read path (and the write paths the harness
# drives) that asks for "now".
_CLOCK_MODULES = (
    "app.routers.dashboard",
    "app.valuation.clock",
    "app.valuation.prices",
    "app.valuation.history",
    "app.services.data_hub",
    "app.routers.crypto",
    "app.routers.dividends",
    "app.routers.spending",
    "app.fx",
    "app.crypto.valuation",
    "app.crypto.ingest",
    "app.wealth_rollup_dirty",
    "app.valuation_cache",
    "app.core.clock",
    "app.market_data.service",
    "app.portfolio.ibkr_flex",
    "app.portfolio.upload_canonical",
)


def freeze_clock(monkeypatch, when: datetime) -> None:
    import importlib

    frozen = _frozen_datetime(when)
    for name in _CLOCK_MODULES:
        module = importlib.import_module(name)
        if getattr(module, "datetime", None) is not None:
            monkeypatch.setattr(module, "datetime", frozen)


# ─── Synthetic FX ────────────────────────────────────────────────────────────

# Units of each currency per 1 EUR, per calendar month. Deliberately not 1.0
# and different every month, so a value converted at the wrong date moves.
MONTHLY_FX_PER_EUR: dict[str, dict[str, float]] = {
    "2025-01": {"USD": 1.03, "SGD": 1.41, "HKD": 8.02, "INR": 88.0},
    "2025-02": {"USD": 1.04, "SGD": 1.40, "HKD": 8.10, "INR": 88.5},
    "2025-03": {"USD": 1.05, "SGD": 1.42, "HKD": 8.16, "INR": 88.2},
    "2025-04": {"USD": 1.06, "SGD": 1.43, "HKD": 8.24, "INR": 88.9},
    "2025-05": {"USD": 1.06, "SGD": 1.44, "HKD": 8.25, "INR": 89.3},
    "2025-06": {"USD": 1.07, "SGD": 1.44, "HKD": 8.33, "INR": 89.1},
    "2025-07": {"USD": 1.08, "SGD": 1.45, "HKD": 8.41, "INR": 89.6},
    "2025-08": {"USD": 1.07, "SGD": 1.44, "HKD": 8.34, "INR": 89.4},
    "2025-09": {"USD": 1.06, "SGD": 1.44, "HKD": 8.26, "INR": 88.8},
    "2025-10": {"USD": 1.07, "SGD": 1.45, "HKD": 8.33, "INR": 89.2},
    "2025-11": {"USD": 1.07, "SGD": 1.45, "HKD": 8.35, "INR": 89.0},
    "2025-12": {"USD": 1.08, "SGD": 1.46, "HKD": 8.42, "INR": 90.0},
    "2026-01": {"USD": 1.09, "SGD": 1.465, "HKD": 8.50, "INR": 91.0},
    "2026-02": {"USD": 1.10, "SGD": 1.47, "HKD": 8.58, "INR": 92.0},
    "2026-03": {"USD": 1.085, "SGD": 1.455, "HKD": 8.47, "INR": 91.5},
    "2026-04": {"USD": 1.095, "SGD": 1.46, "HKD": 8.55, "INR": 92.5},
}
_FX_FIRST_DAY = date(2025, 1, 1)
_FX_LAST_DAY = date(2026, 4, 5)


def fx_per_eur(day: date, currency: str) -> float:
    if currency == "EUR":
        return 1.0
    return MONTHLY_FX_PER_EUR[day.strftime("%Y-%m")][currency]


def fx(day: date, quote: str, base: str = "SGD") -> float:
    """Value of 1 ``quote`` in ``base`` on ``day`` under the synthetic table."""
    return fx_per_eur(day, base) / fx_per_eur(day, quote)


def _seed_fx_rates(conn) -> None:
    rows = []
    day = _FX_FIRST_DAY
    while day <= _FX_LAST_DAY:
        for currency, rate in MONTHLY_FX_PER_EUR[day.strftime("%Y-%m")].items():
            rows.append({"d": day.isoformat(), "q": currency, "r": rate})
        day += timedelta(days=1)
    conn.execute(
        text(
            "INSERT INTO fx_rates (rate_date, base, quote, rate, source) "
            "VALUES (:d, 'EUR', :q, :r, 'synthetic')"
        ),
        rows,
    )


# ─── IBKR Flex statements ────────────────────────────────────────────────────


@dataclass(frozen=True)
class FlexHolding:
    conid: str
    symbol: str
    description: str
    exchange: str
    currency: str
    quantity: float
    price: float


@dataclass(frozen=True)
class FlexReport:
    report_date: date
    cash_sgd: float
    cash_usd: float
    holdings: tuple[FlexHolding, ...]
    funds: tuple[tuple[str, str, float, str, str], ...] = ()  # (date, currency, amount, code, id)
    # Earlier days a multi-day (backfill) report also carries NAV for: (date, cash, stock), base currency.
    nav_history: tuple[tuple[date, float, float], ...] = ()


def _aapl(quantity: float, price: float) -> FlexHolding:
    return FlexHolding("900001", "AAPL", "APPLE INC", "NASDAQ", "USD", quantity, price)


def _tencent(quantity: float, price: float) -> FlexHolding:
    return FlexHolding("900002", "700", "TENCENT HOLDINGS LTD", "SEHK", "HKD", quantity, price)


FLEX_REPORTS: tuple[FlexReport, ...] = (
    FlexReport(date(2026, 1, 30), 2000.0, 1500.0, (_aapl(20, 180.0), _tencent(100, 300.0))),
    FlexReport(
        date(2026, 2, 27),
        2500.0,
        1500.0,
        (_aapl(20, 190.0), _tencent(100, 320.0)),
        funds=(
            ("2026-02-12", "USD", 5.0, "DIV", "SYN-DIV-1"),
            ("2026-02-12", "USD", -1.5, "FRTAX", "SYN-WHT-1"),
        ),
    ),
    FlexReport(date(2026, 3, 16), 1200.0, 1500.0, (_aapl(25, 200.0), _tencent(100, 310.0))),
    FlexReport(date(2026, 3, 31), 1300.0, 1600.0, (_aapl(25, 204.0), _tencent(100, 305.0))),
)


def flex_xml(report: FlexReport, *, from_date: date | None = None) -> str:
    """A synthetic Flex statement for one report date (base currency SGD)."""
    day = report.report_date
    start = from_date or day
    usd_sgd = fx(day, "USD")
    stock_base = 0.0
    positions = []
    rates = {"USD": usd_sgd, "HKD": fx(day, "HKD")}
    for h in report.holdings:
        value_local = h.quantity * h.price
        value_base = value_local * rates[h.currency]
        stock_base += value_base
        positions.append(
            f'<OpenPosition reportDate="{day}" conid="{h.conid}" symbol="{h.symbol}" '
            f'description="{h.description}" assetCategory="STK" listingExchange="{h.exchange}" '
            f'currency="{h.currency}" position="{h.quantity}" markPrice="{h.price:.4f}" '
            f'positionValue="{value_local:.4f}" positionValueInBase="{value_base:.4f}" '
            f'costBasisMoney="{value_local * 0.8:.4f}" costBasisMoneyInBase="{value_base * 0.8:.4f}" '
            f'fxRateToBase="{rates[h.currency]:.8f}" />'
        )
    cash_base = report.cash_sgd + report.cash_usd * usd_sgd
    total = cash_base + stock_base
    funds = "".join(
        f'<StmtFunds date="{d}" currency="{cur}" amount="{amount:.2f}" activityCode="{code}" '
        f'activityDescription="AAPL(US0000000001) Cash Dividend" transactionID="{tid}" />'
        for d, cur, amount, code, tid in report.funds
    )
    history = "".join(
        f'<EquitySummaryByReportDateInBase reportDate="{d}" cash="{c:.4f}" stock="{st:.4f}" options="0" funds="0" '
        f'bonds="0" interestAccruals="0" dividendAccruals="0" total="{c + st:.4f}" />'
        for d, c, st in report.nav_history
    )
    return f"""
    <FlexQueryResponse>
      <FlexStatements count="1">
        <FlexStatement accountId="U0000142" fromDate="{start}" toDate="{day}" whenGenerated="{day};20:00:00">
          <EquitySummaryInBase>{history}
            <EquitySummaryByReportDateInBase reportDate="{day}" cash="{cash_base:.4f}" stock="{stock_base:.4f}"
              options="0" funds="0" bonds="0" interestAccruals="0" dividendAccruals="0" total="{total:.4f}" />
          </EquitySummaryInBase>
          <CashReport>
            <CashReportCurrency currency="SGD" toDate="{day}" endingCash="{report.cash_sgd:.2f}" endingSettledCash="{report.cash_sgd:.2f}" />
            <CashReportCurrency currency="USD" toDate="{day}" endingCash="{report.cash_usd:.2f}" endingSettledCash="{report.cash_usd:.2f}" />
            <CashReportCurrency currency="BASE_SUMMARY" toDate="{day}" endingCash="{cash_base:.4f}" />
          </CashReport>
          <OpenPositions>{"".join(positions)}</OpenPositions>
          <ConversionRates>
            <ConversionRate reportDate="{day}" fromCurrency="USD" toCurrency="SGD" rate="{usd_sgd:.8f}" />
            <ConversionRate reportDate="{day}" fromCurrency="HKD" toCurrency="SGD" rate="{rates['HKD']:.8f}" />
          </ConversionRates>
          <StmtFunds>{funds}</StmtFunds>
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>
    """


def import_flex(db_engine, report: FlexReport, *, from_date: date | None = None, cutover: date | None = None) -> None:
    db = Session(bind=db_engine)
    try:
        run_ibkr_flex_import_from_xml(
            db,
            current_user_id=USER_A,
            legacy_account_id=IBKR,
            xml_text=flex_xml(report, from_date=from_date),
            cutover_date=cutover,
        )
        db.commit()
    finally:
        db.close()


# ─── Uploaded balances ───────────────────────────────────────────────────────

# (account, statement date, currency, balance)
BANK_BALANCES: tuple[tuple[int, str, str, float], ...] = (
    (DBS_SAVINGS, "2025-12-20", "SGD", 40000.0),
    (DBS_SAVINGS, "2026-01-28", "SGD", 42000.0),
    (DBS_SAVINGS, "2026-02-26", "SGD", 45500.0),
    (DBS_SAVINGS, "2026-03-12", "SGD", 47250.0),
    (DBS_SAVINGS, "2026-03-31", "SGD", 46100.0),
    (HSBC_USD, "2026-01-15", "USD", 8000.0),
    (HSBC_USD, "2026-02-20", "USD", 8200.0),
    (HSBC_USD, "2026-03-10", "USD", 8100.0),
    # Before IBKR Flex took over, the IBKR account's cash came from an upload.
    (IBKR, "2025-12-31", "USD", 3000.0),
    # A savings statement uploaded to a card account by mistake (#180).
    (MISFILED_CARD, "2026-02-26", "SGD", 3100.0),
    (B_BANK, "2026-01-25", "SGD", 15000.0),
    (B_BANK, "2026-02-25", "SGD", 16000.0),
    (B_BANK, "2026-03-05", "SGD", 17000.0),
)


def upload_balance(db_engine, account_id: int, as_of: str, currency: str, amount: float) -> None:
    """The upload write path for a bank statement's balance."""
    db = Session(bind=db_engine)
    try:
        run_upload_balance_canonical_adapter(
            db,
            account_id=account_id,
            import_job_id=None,
            parse_result=ParseResult(
                transactions=[],
                positions=[{"asset_class": "CASH", "currency": currency, "quantity": amount}],
                section_counts={},
                parser_meta={"statement_period_end": as_of},
            ),
        )
        db.commit()
    finally:
        db.close()


# ─── Holdings, prices, wallets, transactions ─────────────────────────────────

# Sharekhan (INR) holdings as uploaded: (date, asset, quantity, price INR)
SHAREKHAN_HOLDINGS: tuple[tuple[str, int, float, float], ...] = (
    ("2026-01-31", RELIANCE, 10, 2800.0),
    ("2026-01-31", INFY, 20, 1600.0),
    ("2026-02-28", RELIANCE, 10, 2850.0),
    ("2026-02-28", INFY, 20, 1580.0),
    ("2026-03-15", RELIANCE, 12, 2880.0),
    ("2026-03-15", INFY, 20, 1620.0),
)

# The price job's quotes: (trade date, asset, price, currency)
PRICES: tuple[tuple[str, int, float, str], ...] = (
    ("2026-01-30", AAPL, 180.0, "USD"),
    ("2026-02-27", AAPL, 190.0, "USD"),
    ("2026-03-17", AAPL, 205.0, "USD"),
    ("2026-03-31", AAPL, 206.0, "USD"),
    ("2026-01-30", TENCENT, 300.0, "HKD"),
    ("2026-02-27", TENCENT, 320.0, "HKD"),
    ("2026-03-17", TENCENT, 315.0, "HKD"),
    ("2026-03-31", TENCENT, 301.0, "HKD"),
    ("2026-01-30", RELIANCE, 2810.0, "INR"),
    ("2026-02-27", RELIANCE, 2840.0, "INR"),
    ("2026-03-17", RELIANCE, 2900.0, "INR"),
    ("2026-03-31", RELIANCE, 2950.0, "INR"),
    ("2026-01-30", INFY, 1605.0, "INR"),
    ("2026-02-27", INFY, 1575.0, "INR"),
    ("2026-03-17", INFY, 1650.0, "INR"),
    ("2026-03-31", INFY, 1640.0, "INR"),
)

# Wallets: (id, user, chain_type, chain, address, label, status)
WALLETS: tuple[tuple[str, int, str, str, str, str, str], ...] = (
    ("wallet-a-evm", USER_A, "evm", "ethereum", "0x00000000000000000000000000000000000a0001", "A main", "active"),
    ("wallet-a-sol", USER_A, "solana", "solana", "SynthA111111111111111111111111111111111111", "A sol", "active"),
    ("wallet-a-old", USER_A, "evm", "base", "0x00000000000000000000000000000000000a0002", "A retired", "inactive"),
    ("wallet-b-evm", USER_B, "evm", "base", "0x00000000000000000000000000000000000b0001", "B main", "active"),
)

# Wallet snapshots: (wallet, as_of, [(symbol, kind, amount, price_usd)])
WALLET_SNAPSHOTS: tuple[tuple[str, str, tuple[tuple[str, str, float, float], ...]], ...] = (
    ("wallet-a-evm", "2026-01-31", (("ETH", "native", 2.0, 3000.0), ("USDC", "token", 1500.0, 1.0))),
    ("wallet-a-evm", "2026-02-28", (("ETH", "native", 2.0, 2800.0), ("USDC", "token", 2000.0, 1.0))),
    ("wallet-a-evm", "2026-03-17", (("ETH", "native", 2.5, 3100.0), ("USDC", "token", 1000.0, 1.0))),
    ("wallet-a-evm", "2026-03-31", (("ETH", "native", 2.5, 3050.0), ("USDC", "token", 1100.0, 1.0))),
    ("wallet-a-sol", "2026-02-10", (("SOL", "native", 40.0, 150.0),)),
    ("wallet-a-sol", "2026-03-15", (("SOL", "native", 40.0, 170.0), ("USDT", "token", 250.0, 1.0))),
    ("wallet-a-old", "2026-02-01", (("ETH", "native", 9.0, 2900.0),)),
    ("wallet-b-evm", "2026-01-20", (("ETH", "native", 1.0, 3200.0), ("USDT", "token", 500.0, 1.0))),
    ("wallet-b-evm", "2026-03-01", (("ETH", "native", 1.0, 3000.0), ("USDT", "token", 700.0, 1.0))),
)

# Transactions: (ts, account, amount, type, currency, category, merchant)
TRANSACTIONS: tuple[tuple[str, int, float, str, str, str | None, str | None], ...] = (
    ("2025-12-24 09:00:00+00:00", DBS_SAVINGS, 8000.0, "INCOME", "SGD", "Salary", "Synthetic Employer"),
    ("2026-01-02 09:00:00+00:00", DBS_SAVINGS, -2500.0, "EXPENSE", "SGD", "Rent", "Synthetic Landlord"),
    ("2026-01-24 09:00:00+00:00", DBS_SAVINGS, 8000.0, "INCOME", "SGD", "Salary", "Synthetic Employer"),
    ("2026-01-31 09:00:00+00:00", DBS_SAVINGS, -12.0, "FEE", "SGD", "Fees", "Bank"),
    ("2026-02-02 09:00:00+00:00", DBS_SAVINGS, -2500.0, "EXPENSE", "SGD", "Rent", "Synthetic Landlord"),
    ("2026-02-24 09:00:00+00:00", DBS_SAVINGS, 8000.0, "INCOME", "SGD", "Salary", "Synthetic Employer"),
    ("2026-03-02 09:00:00+00:00", DBS_SAVINGS, -2500.0, "EXPENSE", "SGD", "Rent", "Synthetic Landlord"),
    ("2026-03-10 09:00:00+00:00", DBS_SAVINGS, 450.0, "INCOME", "SGD", "Refund", "Synthetic Shop"),
    ("2026-02-15 09:00:00+00:00", HSBC_USD, 120.0, "INCOME", "USD", "Interest", "HSBC"),
    ("2026-03-15 09:00:00+00:00", HSBC_USD, -300.0, "EXPENSE", "USD", "Travel", "Synthetic Airline"),
    ("2026-02-14 09:00:00+00:00", SHAREKHAN, 450.0, "INCOME", "INR", "Dividend", "RELIANCE"),
    ("2026-02-14 09:00:00+00:00", SHAREKHAN, -45.0, "TAX", "INR", "Withholding tax", "RELIANCE"),
    ("2026-03-05 09:00:00+00:00", SHAREKHAN, 320.0, "INCOME", "INR", "Dividend", "INFY"),
    ("2026-01-10 09:00:00+00:00", DBS_CARD, -820.0, "EXPENSE", "SGD", "Groceries", "Synthetic Mart"),
    ("2026-01-22 09:00:00+00:00", DBS_CARD, -140.0, "EXPENSE", "SGD", "Dining", "Synthetic Cafe"),
    ("2026-02-08 09:00:00+00:00", DBS_CARD, -1210.4, "EXPENSE", "SGD", "Shopping", "Synthetic Store"),
    ("2026-02-18 09:00:00+00:00", DBS_CARD, -95.0, "EXPENSE", "SGD", "Dining", "Synthetic Cafe"),
    ("2026-02-25 09:00:00+00:00", DBS_CARD, 1000.0, "TRANSFER", "SGD", "Card payment", "DBS"),
    ("2026-03-03 09:00:00+00:00", DBS_CARD, -660.0, "EXPENSE", "SGD", "Groceries", "Synthetic Mart"),
    ("2026-03-14 09:00:00+00:00", DBS_CARD, -310.55, "EXPENSE", "SGD", "Travel", "Synthetic Hotel"),
    ("2026-03-30 09:00:00+00:00", DBS_CARD, -75.0, "EXPENSE", "SGD", "Dining", "Synthetic Cafe"),
    ("2026-02-03 09:00:00+00:00", MISFILED_CARD, 2200.0, "INCOME", "SGD", "Salary", "Synthetic Employer"),
    ("2026-02-05 09:00:00+00:00", B_BANK, 6000.0, "INCOME", "SGD", "Salary", "B Employer"),
    ("2026-03-05 09:00:00+00:00", B_BANK, 6000.0, "INCOME", "SGD", "Salary", "B Employer"),
    ("2026-02-11 09:00:00+00:00", B_CARD, -900.0, "EXPENSE", "SGD", "Shopping", "B Store"),
    ("2026-03-11 09:00:00+00:00", B_CARD, -400.0, "EXPENSE", "SGD", "Dining", "B Cafe"),
)


def _on_or_before(value: str, day: date) -> bool:
    return date.fromisoformat(value[:10]) <= day


# Accounts: (id, owner, name, platform code, type, currency, country, platform id)
ACCOUNTS: tuple[tuple[int, int, str, str, str, str, str, int], ...] = (
    (DBS_SAVINGS, USER_A, "DBS Savings", "DBS", "BANK", "SGD", "SG", 1),
    (HSBC_USD, USER_A, "HSBC USD Saver", "HSBC", "BANK", "USD", "HK", 4),
    (IBKR, USER_A, "IBKR Main", "IBKR", "BROKER", "USD", "US", 2),
    (SHAREKHAN, USER_A, "Sharekhan Demat", "SHAREKHAN", "BROKER", "INR", "IN", 3),
    (DBS_CARD, USER_A, "DBS Card", "DBS", "CREDIT_CARD", "SGD", "SG", 1),
    (MISFILED_CARD, USER_A, "DBS Altitude", "DBS", "CREDIT_CARD", "SGD", "SG", 1),
    (B_BANK, USER_B, "OCBC 360", "OCBC", "BANK", "SGD", "SG", 5),
    (B_CARD, USER_B, "OCBC Card", "OCBC", "CREDIT_CARD", "SGD", "SG", 5),
)
# Card details: (account, name, issuer, limit, available, available as of).
# The misfiled card has no row here (#180).
CARDS: tuple[tuple[int, str, str, float, float | None, str | None], ...] = (
    (DBS_CARD, "DBS Card", "DBS", 10000.0, None, None),
    (B_CARD, "OCBC Card", "OCBC", 5000.0, 4200.0, "2026-02-20 00:00:00+00:00"),
)
_OWNER = {account[0]: account[1] for account in ACCOUNTS}
_WALLET_OWNER = {wallet[0]: wallet[1] for wallet in WALLETS}


def _insert_shared_data(conn, through: date) -> None:
    """What no user owns: users, platforms, assets, quotes, FX rates."""
    _seed_fx_rates(conn)
    conn.execute(
        text(
            # OR IGNORE: the `client` fixture has already created the user it signs in as.
            "INSERT OR IGNORE INTO users (id, username, display_name, is_active, is_admin) VALUES "
            "(:a, 'household_a', 'Household A', 1, 0), (:b, 'household_b', 'Household B', 1, 0)"
        ),
        {"a": USER_A, "b": USER_B},
    )
    conn.execute(
        text(
            "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
            "(1, 'DBS', 'DBS Bank', 'BANK', 'SG'), "
            "(2, 'IBKR', 'Interactive Brokers', 'BROKER', 'US'), "
            "(3, 'SHAREKHAN', 'Sharekhan', 'BROKER', 'IN'), "
            "(4, 'HSBC', 'HSBC', 'BANK', 'HK'), "
            "(5, 'OCBC', 'OCBC Bank', 'BANK', 'SG')"
        )
    )
    conn.execute(
        text(
            "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
            "(:aapl, 'AAPL', 'Apple Inc.', 'STOCK', 'USD', 'US'), "
            "(:tencent, '0700', 'Tencent Holdings', 'STOCK', 'HKD', 'HK'), "
            "(:rel, 'RELIANCE', 'Reliance Industries', 'STOCK', 'INR', 'IN'), "
            "(:infy, 'INFY', 'Infosys', 'STOCK', 'INR', 'IN')"
        ),
        {"aapl": AAPL, "tencent": TENCENT, "rel": RELIANCE, "infy": INFY},
    )
    exchange = {"USD": "US", "HKD": "HKEX", "INR": "NSE"}
    conn.execute(
        text(
            "INSERT INTO prices (asset_id, ts, trade_date, price, currency, source, exchange_code) "
            "VALUES (:asset, :ts, :d, :p, :c, 'synthetic', :x)"
        ),
        [
            {"asset": asset, "ts": f"{d} 10:00:00+00:00", "d": d, "p": price, "c": cur, "x": exchange[cur]}
            for d, asset, price, cur in PRICES
            if _on_or_before(d, through)
        ],
    )


def _insert_user_rows(conn, user_id: int, through: date) -> None:
    """One user's accounts, cards, wallets and transactions (plain inserts)."""
    conn.execute(
        text(
            "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country, platform_id) "
            "VALUES (:id, :name, :platform, :user, :type, :currency, :country, :pid)"
        ),
        [
            {"id": i, "user": u, "name": n, "platform": p, "type": t, "currency": c, "country": co, "pid": pid}
            for i, u, n, p, t, c, co, pid in ACCOUNTS
            if u == user_id
        ],
    )
    cards = [card for card in CARDS if _OWNER[card[0]] == user_id]
    if cards:
        conn.execute(
            text(
                "INSERT INTO credit_card_accounts (account_id, card_name, issuer, credit_limit, available_limit, "
                "available_limit_as_of, statement_day, due_day) VALUES (:a, :n, :i, :l, :av, :avd, 20, 5)"
            ),
            [{"a": a, "n": n, "i": i, "l": lim, "av": av, "avd": avd} for a, n, i, lim, av, avd in cards],
        )
    conn.execute(
        text(
            "INSERT INTO crypto_wallets (id, user_id, chain_type, chain, address, label, status, created_at) "
            "VALUES (:id, :u, :ct, :ch, :addr, :label, :status, '2026-01-01 00:00:00+00:00')"
        ),
        [
            {"id": w, "u": u, "ct": ct, "ch": ch, "addr": addr, "label": label, "status": status}
            for w, u, ct, ch, addr, label, status in WALLETS
            if u == user_id
        ],
    )
    chain_of = {w[0]: (w[2], w[3]) for w in WALLETS}
    for wallet_id, as_of, items in WALLET_SNAPSHOTS:
        if _WALLET_OWNER[wallet_id] != user_id or not _on_or_before(as_of, through):
            continue
        total = sum(amount * price for _s, _k, amount, price in items)
        fetched_at = f"{as_of} 12:00:00+00:00"
        snapshot_id = conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshots (wallet_id, as_of_date, fetched_at, total_usd, source_versions) "
                "VALUES (:w, :d, :f, :t, :sv) RETURNING id"
            ),
            {
                "w": wallet_id, "d": as_of, "f": fetched_at, "t": total,
                "sv": f'{{"holdings_as_of": "{fetched_at}", "price_as_of": "{fetched_at}"}}',
            },
        ).scalar_one()
        chain_type, chain = chain_of[wallet_id]
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshot_items "
                "(snapshot_id, chain_type, chain, asset_kind, symbol, normalized_amount, price_usd, value_usd, price_source) "
                "VALUES (:s, :ct, :ch, :k, :sym, :amt, :p, :v, 'synthetic')"
            ),
            [
                {"s": snapshot_id, "ct": chain_type, "ch": chain, "k": kind, "sym": sym, "amt": amount, "p": price,
                 "v": amount * price}
                for sym, kind, amount, price in items
            ],
        )
    rows = [
        {"ts": ts, "a": acc, "amt": amt, "t": typ, "c": cur, "cat": cat, "m": merchant}
        for ts, acc, amt, typ, cur, cat, merchant in TRANSACTIONS
        if _OWNER[acc] == user_id and _on_or_before(ts, through)
    ]
    if rows:
        conn.execute(
            text(
                "INSERT INTO transactions (ts, account_id, amount, type, currency, category, merchant_counterparty) "
                "VALUES (:ts, :a, :amt, :t, :c, :cat, :m)"
            ),
            rows,
        )


def build_user(db_engine, user_id: int, *, now: datetime) -> None:
    """One user's part of the household as it stood at ``now``: plain inserts,
    then the upload and IBKR Flex write paths."""
    through = now.astimezone(SGT).date()
    with db_engine.begin() as conn:
        _insert_user_rows(conn, user_id, through)
    for account_id, as_of, currency, amount in BANK_BALANCES:
        if _OWNER[account_id] == user_id and _on_or_before(as_of, through):
            upload_balance(db_engine, account_id, as_of, currency, amount)
    if user_id != USER_A:
        return
    for as_of, asset_id, quantity, price in SHAREKHAN_HOLDINGS:
        if _on_or_before(as_of, through):
            seed_canonical_position_snapshot_for_test(
                db_engine,
                account_id=SHAREKHAN,
                asset_id=asset_id,
                as_of=as_of,
                quantity=quantity,
                market_value_base=quantity * price,
                market_price=price,
                cost_basis_base=quantity * price * 0.9,
                currency="INR",
                platform_code="SHAREKHAN",
            )
    for report in FLEX_REPORTS:
        if report.report_date <= through:
            import_flex(db_engine, report)


def build_household(db_engine, *, now: datetime, include_user_b: bool = True) -> None:
    """Write the household as it stood at ``now`` (nothing dated after it).

    Call after ``household_env`` so write-side timestamps are frozen too. Runs
    on the empty per-test database the suite's ``clear_db`` leaves."""
    with db_engine.begin() as conn:
        # Autoincrement ids restart for every build, so ids in responses are
        # the same whichever test ran before.
        conn.exec_driver_sql("DELETE FROM sqlite_sequence")
        _insert_shared_data(conn, now.astimezone(SGT).date())
    build_user(db_engine, USER_A, now=now)
    if include_user_b:
        build_user(db_engine, USER_B, now=now)


def household_env(monkeypatch, when: datetime) -> None:
    """Everything a household test needs besides the data: frozen clock, the
    app timezone, snapshot day 1, no FX providers (stored rates only) and no
    legacy NULL ownership (every row here has an owner)."""
    from app import fx as fx_module

    monkeypatch.setenv("TZ", "Asia/Singapore")
    monkeypatch.setenv("SNAPSHOT_DAY", "1")
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    monkeypatch.setattr(fx_module, "remote_enabled", lambda: False)
    fx_module._CACHE.clear()
    freeze_clock(monkeypatch, when)
    _postgres_date_types(monkeypatch)


def _postgres_date_types(monkeypatch) -> None:
    """SQLite hands a DATE column back as text where Postgres returns a date.
    The History rollup's crypto freshness does date arithmetic on one such
    value, so on SQLite it is converted the way Postgres would type it."""
    import app.valuation.history as history
    from app.valuation.clock import _date_only

    original = history._crypto_snapshot_coverage_as_of

    def _typed(db, anchor_date, current_user_id):  # noqa: ANN001
        return _date_only(original(db, anchor_date, current_user_id))

    monkeypatch.setattr(history, "_crypto_snapshot_coverage_as_of", _typed)


def as_user(client, user_id: int) -> None:  # noqa: ANN001
    """Sign the test client in as user_id with a real access token (#154)."""
    from tests.auth_helpers import auth_headers

    client.headers.update(auth_headers(user_id))
