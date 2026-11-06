"""The canonical read layer (#231, #130 10.2): which canonical fact rows count at an anchor.

Every reader of account facts (positions, NAV, broker cash, uploaded balances,
card statements, completeness) builds its SQL from this module, so each rule
below is written once. The anchor date is bound as ``:anchor_date`` (or the
name a caller passes), the reader as ``:current_user_id``.

At an anchor date d:

1. **Authority** (#140): a fact row counts only when its ``authority_status`` is
   ``authoritative`` (``authoritative_sql``). Authority windows never make a row
   count; they are stamped into the rows at write time.
2. **Owner and open account** (D-50, D-52): the row's account belongs to the
   reader (``account_scope_sql``) and is open on d (``account_open_sql``: no
   ``closed_on``, or one on or after d). A closed account contributes nothing.
3. **Latest per account**: of the counting rows dated on or before d, a reader
   sees the ones on their account's newest date (``latest_per_account_sql``,
   ``effective_rows_sql``). "Account" is the fact's owner key:
   - broker facts (positions, NAV, broker cash): the broker account
     (``BROKER_ACCOUNT_OWNER``), one rule for all three (D-62, #242). A legacy
     account with two broker accounts that Flex routing doesn't separate shows
     each one's newest facts;
   - uploaded balances and card statements: the account (``BALANCE_OWNER``);
   - completeness: the broker account and scope.
4. **Carry-forward**: the newest row is carried forward however old it is
   (``valuation.account_status`` flags it as carried forward), except a card
   statement balance: at most ``CARD_STATEMENT_MAX_AGE_DAYS`` (D-52).
5. **Flex routing** (#140): a legacy account whose IBKR Flex window covers d
   and that has a Flex fact on or before d is read from that Flex broker account
   only (``flex_routed_sql``); its uploaded balances don't count
   (``not_flex_owned_sql``). Needs the ``flex_authority_accounts`` CTE
   (``flex_authority_accounts_cte``) and the ``:ibkr_flex_source_kind`` /
   ``:ibkr_flex_fact_scope`` binds (``flex_binds``).
6. **NAV coverage**: an account with an authoritative NAV on or before d is
   valued by its NAV; its positions are detail only (``nav_rule_sql``).

Shared SQL builder, not Postgres views or functions: a view can't take the
anchor, and SQL functions would exist only on Postgres while the backend suite
runs on SQLite (D-56).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.auth_context import account_scope_sql
from app.portfolio.account_open import account_open_sql
from app.portfolio.authority import FLEX_FACT_SCOPE, FLEX_SOURCE_KIND, authoritative_sql, window_covers_sql

# A card statement balance (a dated ``credit_balance`` snapshot, #207) is the
# card's liability at an anchor when it is the newest one on or before the
# anchor's date and at most this many days older than it: about one statement
# cycle plus two weeks, so a monthly statement always reaches the next month-end.
# An older one is not carried forward: the card falls back to its transactions (D-52).
CARD_STATEMENT_MAX_AGE_DAYS = 45

ANCHOR = ":anchor_date"


@dataclass(frozen=True)
class FactTable:
    """A canonical fact table and how its rows reach their account.

    Broker facts join ``broker_accounts ba`` and then ``accounts acc`` through
    ``ba.legacy_account_id``; balances join ``accounts acc`` directly."""

    table: str
    alias: str
    date_col: str
    via_broker_account: bool
    has_authority: bool = True

    @property
    def date(self) -> str:
        return f"{self.alias}.{self.date_col}"

    def joins(self) -> str:
        if self.via_broker_account:
            return (
                f"JOIN broker_accounts ba ON ba.id = {self.alias}.broker_account_id\n"
                "JOIN accounts acc ON acc.id = ba.legacy_account_id"
            )
        return f"JOIN accounts acc ON acc.id = {self.alias}.account_id"


POSITIONS = FactTable("portfolio_position_snapshots", "ps", "report_date", via_broker_account=True)
NAV = FactTable("portfolio_nav_snapshots", "ns", "report_date", via_broker_account=True)
BROKER_CASH = FactTable("portfolio_cash_balance_snapshots", "cs", "report_date", via_broker_account=True)
BALANCES = FactTable("account_balance_snapshots", "abs", "as_of_date", via_broker_account=False)
COMPLETENESS = FactTable(
    "portfolio_data_completeness", "dc", "report_date", via_broker_account=True, has_authority=False
)

# Owner keys (rule 3). Positions, NAV and broker cash share one (D-62).
BROKER_ACCOUNT_OWNER = ("ba.id",)
BALANCE_OWNER = ("acc.id",)
COMPLETENESS_OWNER = ("ba.id", "dc.fact_scope")


def counting_sql(
    fact: FactTable,
    *,
    anchor: str = ANCHOR,
    oldest: str | None = None,
    scoped: bool = True,
) -> str:
    """Rules 1, 2 and 4: the row is dated on or before the anchor (and not before
    ``oldest``, a bound date, when the fact has a carry-forward limit), counts, and
    its account is the reader's (``scoped``) and open on the anchor."""
    parts = [f"{fact.date} <= {anchor}"]
    if oldest is not None:
        parts.append(f"{fact.date} >= {oldest}")
    if fact.has_authority:
        parts.append(authoritative_sql(fact.alias))
    if scoped:
        parts.append(f"({account_scope_sql('acc')})")
    parts.append(account_open_sql("acc", anchor))
    return "\n  AND ".join(parts)


def _where(fact: FactTable, where: Sequence[str], *, anchor: str, oldest: str | None, scoped: bool) -> str:
    counting = counting_sql(fact, anchor=anchor, oldest=oldest, scoped=scoped)
    return "\n  AND ".join([counting] + [f"({w})" for w in where])


def latest_per_account_sql(
    fact: FactTable,
    owner: Sequence[str],
    *,
    where: Sequence[str] = (),
    anchor: str = ANCHOR,
    oldest: str | None = None,
    scoped: bool = True,
) -> str:
    """Rule 3: each owner's newest date among its counting rows (plus ``where``):
    columns ``owner_0`` .. ``owner_n`` and ``as_of_date``."""
    keys = ", ".join(f"{expr} AS owner_{i}" for i, expr in enumerate(owner))
    return (
        f"SELECT {keys}, MAX({fact.date}) AS as_of_date\n"
        f"FROM {fact.table} {fact.alias}\n{fact.joins()}\n"
        f"WHERE {_where(fact, where, anchor=anchor, oldest=oldest, scoped=scoped)}\n"
        f"GROUP BY {', '.join(owner)}"
    )


def effective_rows_sql(
    fact: FactTable,
    owner: Sequence[str],
    *,
    where: Sequence[str] = (),
    anchor: str = ANCHOR,
    oldest: str | None = None,
    scoped: bool = True,
) -> str:
    """The rows of ``fact`` a reader sees at the anchor (rules 1-4): its counting
    rows (plus ``where``) on their owner's newest date, the same newest date
    ``latest_per_account_sql`` gives (one window over the counting rows, so the
    predicates are evaluated once). Selects the fact table's own columns plus
    ``_owner_latest``, so a reader can use it as a subquery in place of the table
    and keep its own joins."""
    return (
        f"SELECT * FROM (\n"
        f"SELECT {fact.alias}.*, MAX({fact.date}) OVER (PARTITION BY {', '.join(owner)}) AS _owner_latest\n"
        f"FROM {fact.table} {fact.alias}\n{fact.joins()}\n"
        f"WHERE {_where(fact, where, anchor=anchor, oldest=oldest, scoped=scoped)}\n"
        f") _counting WHERE _counting.{fact.date_col} = _counting._owner_latest"
    )


# ─── Rule 5: Flex routing ────────────────────────────────────────────────────


def flex_binds() -> dict[str, str]:
    """Bind parameters the ``flex_authority_accounts`` CTE needs."""
    return {"ibkr_flex_source_kind": FLEX_SOURCE_KIND, "ibkr_flex_fact_scope": FLEX_FACT_SCOPE}


def flex_authority_accounts_cte() -> str:
    """Body of the ``flex_authority_accounts`` CTE: (legacy account, broker account)
    pairs where IBKR Flex is the authority at :anchor_date (its window covers the
    anchor) and has written a fact that counts at or before it (#140).

    The window only routes the legacy account to its Flex broker account; whether
    a row counts is its authority_status (``authoritative_sql``)."""
    return (
        """
          SELECT ba.legacy_account_id AS account_id, ba.id AS broker_account_id
          FROM portfolio_source_authority_windows aw
          JOIN broker_accounts ba ON ba.id = aw.broker_account_id
          JOIN broker_connections bc ON bc.id = ba.connection_id
          JOIN accounts acc ON acc.id = ba.legacy_account_id
          WHERE aw.source_kind = :ibkr_flex_source_kind
            AND aw.fact_scope = :ibkr_flex_fact_scope
            AND """
        + window_covers_sql("aw", ANCHOR)
        + """
            AND ba.legacy_account_id IS NOT NULL
            AND bc.platform_code = 'IBKR'
            AND (
              EXISTS (
                SELECT 1 FROM portfolio_nav_snapshots ns
                WHERE ns.broker_account_id = ba.id
                  AND ns.report_date <= :anchor_date
                  AND """
        + authoritative_sql("ns")
        + """
              )
              OR EXISTS (
                SELECT 1 FROM portfolio_position_snapshots ps
                WHERE ps.broker_account_id = ba.id
                  AND ps.report_date <= :anchor_date
                  AND """
        + authoritative_sql("ps")
        + """
              )
              OR EXISTS (
                SELECT 1 FROM portfolio_cash_balance_snapshots cs
                WHERE cs.broker_account_id = ba.id
                  AND cs.report_date <= :anchor_date
                  AND """
        + authoritative_sql("cs")
        + """
              )
            )
            AND ("""
        + account_scope_sql("acc")
        + """)
        """
    )


def flex_routed_sql(ba: str = "ba") -> str:
    """The broker account ``ba`` is the one its legacy account is read from: Flex
    doesn't own the legacy account at the anchor, or ``ba`` is its Flex account."""
    return (
        f"NOT EXISTS (SELECT 1 FROM flex_authority_accounts faa WHERE faa.account_id = {ba}.legacy_account_id)"
        f" OR EXISTS (SELECT 1 FROM flex_authority_accounts faa"
        f" WHERE faa.account_id = {ba}.legacy_account_id AND faa.broker_account_id = {ba}.id)"
    )


def not_flex_owned_sql(account_expr: str) -> str:
    """Flex doesn't own the legacy account ``account_expr`` at the anchor (its
    uploaded balances count)."""
    return f"NOT EXISTS (SELECT 1 FROM flex_authority_accounts faa WHERE faa.account_id = {account_expr})"


# ─── Rule 6: NAV coverage ────────────────────────────────────────────────────


def has_nav_sql(ba: str = "ba", *, anchor: str = ANCHOR) -> str:
    """The broker account ``ba`` has an authoritative NAV on or before the anchor."""
    return (
        "EXISTS (SELECT 1 FROM portfolio_nav_snapshots _nav"
        f" WHERE _nav.broker_account_id = {ba}.id AND _nav.report_date <= {anchor}"
        f" AND {authoritative_sql('_nav')})"
    )


def valued_by_nav_sql(account_expr: str, *, anchor: str = ANCHOR) -> str:
    """The legacy account ``account_expr`` has an authoritative NAV on or before
    the anchor, on any of its broker accounts."""
    return (
        "EXISTS (SELECT 1 FROM portfolio_nav_snapshots _nav"
        " JOIN broker_accounts _nav_ba ON _nav_ba.id = _nav.broker_account_id"
        f" WHERE _nav_ba.legacy_account_id = {account_expr} AND _nav.report_date <= {anchor}"
        f" AND {authoritative_sql('_nav')})"
    )


def nav_rule_sql(ba: str = "ba", *, include_nav_accounts: str) -> str:
    """Positions of broker account ``ba`` count unless its legacy account is valued
    by a NAV; with ``include_nav_accounts`` (a SQL boolean: a bind or TRUE), a
    NAV account's own positions count too, as detail."""
    return (
        f"NOT {valued_by_nav_sql(f'{ba}.legacy_account_id')}"
        f" OR ({include_nav_accounts} AND {has_nav_sql(ba)})"
    )


# ─── The effective facts at an anchor ────────────────────────────────────────


def effective_positions_sql(*, include_nav_accounts: str = ":include_nav_accounts") -> str:
    """Position snapshots at the anchor, newest per broker account (D-62), routed
    (needs the ``flex_authority_accounts`` CTE) and without NAV accounts' positions
    unless ``include_nav_accounts`` (a SQL boolean)."""
    return effective_rows_sql(
        POSITIONS,
        BROKER_ACCOUNT_OWNER,
        where=[flex_routed_sql("ba"), nav_rule_sql("ba", include_nav_accounts=include_nav_accounts)],
    )


def effective_nav_sql() -> str:
    """NAV snapshots at the anchor, newest per broker account."""
    return effective_rows_sql(NAV, BROKER_ACCOUNT_OWNER)


def effective_uploaded_balances_sql() -> str:
    """``account_balance_snapshots`` rows at the anchor, newest per account, for
    accounts Flex doesn't own (needs the ``flex_authority_accounts`` CTE)."""
    return effective_rows_sql(BALANCES, BALANCE_OWNER, where=[not_flex_owned_sql("acc.id")])


def effective_broker_cash_sql(*, extra_where: Sequence[str] = ()) -> str:
    """Broker cash snapshots at the anchor, newest per broker account, routed
    (needs the ``flex_authority_accounts`` CTE)."""
    return effective_rows_sql(BROKER_CASH, BROKER_ACCOUNT_OWNER, where=[*extra_where, flex_routed_sql("ba")])


def effective_card_statements_sql(*, oldest: str = ":oldest") -> str:
    """Card statement balances at the anchor: each card's newest ``credit_balance``
    snapshot, at most CARD_STATEMENT_MAX_AGE_DAYS old (bind ``oldest``)."""
    return effective_rows_sql(
        BALANCES,
        BALANCE_OWNER,
        where=["acc.account_type = 'CREDIT_CARD'", "abs.balance_type = 'credit_balance'"],
        oldest=oldest,
    )


def effective_completeness_sql() -> str:
    """Completeness records at the anchor, newest per broker account and scope."""
    return effective_rows_sql(COMPLETENESS, COMPLETENESS_OWNER)
