"""What #242 (D-62) changes on this database. Read-only; prints counts and ids only.

    python -m app.scripts.canonical_rules_impact [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--step N] [--user-id N]

e.g. ``docker exec <api container> python -m app.scripts.canonical_rules_impact``.

For every user with accounts and every ``--step``-th day from ``--from`` (default:
the oldest canonical fact) to ``--to`` (default: today, app clock), it runs the
old and the new rule side by side and reports where they disagree:

1. **Owner key**: positions newest per broker account (new) vs per legacy
   account (old), with and without NAV accounts' own positions. Reports the
   legacy and broker accounts involved, the (user, day) pairs and how many
   position rows are now shown (the new rule only adds rows: a broker account
   whose newest snapshot is older than its legacy account's newest). NAV and broker cash were already
   per broker account: nothing to compare.
2. **Coverage date**: Flex-routed (new) vs not (old). Reports the (user, day)
   pairs whose date differs, and the Flex-owned legacy accounts with uploaded
   balances, or non-Flex broker cash or positions, that count on some day.
3. **Held positions for pricing**: the list on day d vs day d-1. The old rule
   ("today" = the UTC date) showed day d-1's list during the hours when the app
   timezone is already on d and UTC isn't (00:00-08:00 in Singapore); it reports
   on how many days the two lists differ, and whether they differ right now.

Everything runs in one READ ONLY transaction (Postgres), rolled back at the end.
No amounts, names or symbols are printed: only counts, dates and internal ids.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.clock import app_now, app_today, current_timezone_name
from app.market_data.service import held_position_rows
from app.portfolio import effective_facts as ef

OLD_POSITIONS_OWNER = ("ba.legacy_account_id",)


def _position_rows(db: Session, user_id: int, anchor: date, *, include_nav: bool, old: bool) -> set[tuple[int, int, int]]:
    """(snapshot id, broker account, legacy account) the positions reader returns."""
    if old:
        inner = ef.effective_rows_sql(
            ef.POSITIONS,
            OLD_POSITIONS_OWNER,
            where=[ef.flex_routed_sql("ba"), ef.nav_rule_sql("ba", include_nav_accounts=":include_nav_accounts")],
        )
    else:
        inner = ef.effective_positions_sql()
    rows = db.execute(
        text(
            "WITH flex_authority_accounts AS (" + ef.flex_authority_accounts_cte() + ")\n"
            "SELECT ps.id, ba.id AS broker_account_id, ba.legacy_account_id\n"
            "FROM (" + inner + ") ps JOIN broker_accounts ba ON ba.id = ps.broker_account_id"
        ),
        {"anchor_date": anchor, "current_user_id": user_id, "include_nav_accounts": include_nav, **ef.flex_binds()},
    ).all()
    return {(int(r[0]), int(r[1]), int(r[2])) for r in rows}


def _coverage_parts(*, routed: bool) -> list[str]:
    positions_where = [ef.nav_rule_sql("ba", include_nav_accounts="TRUE")]
    balances_where = ["abs.balance_type <> 'credit_balance'"]
    cash_where: list[str] = []
    if routed:
        positions_where.insert(0, ef.flex_routed_sql("ba"))
        balances_where.append(ef.not_flex_owned_sql("acc.id"))
        cash_where.append(ef.flex_routed_sql("ba"))
    return [
        ef.latest_per_account_sql(ef.POSITIONS, ef.BROKER_ACCOUNT_OWNER, where=positions_where),
        ef.latest_per_account_sql(ef.NAV, ef.BROKER_ACCOUNT_OWNER),
        ef.latest_per_account_sql(ef.BALANCES, ef.BALANCE_OWNER, where=balances_where),
        ef.latest_per_account_sql(ef.BROKER_CASH, ef.BROKER_ACCOUNT_OWNER, where=cash_where),
    ]


def coverage_as_of(db: Session, user_id: int, anchor: date, *, routed: bool) -> Any:
    """``canonical_snapshot_coverage_as_of`` with every component (``routed``: the
    #242 rule; else the old one, without Flex routing)."""
    parts = _coverage_parts(routed=routed)
    sql = (
        "WITH flex_authority_accounts AS (" + ef.flex_authority_accounts_cte() + "),\nlatest AS (\n"
        + "\nUNION ALL\n".join(f"SELECT as_of_date FROM ({p}) _c{i}" for i, p in enumerate(parts))
        + "\n)\nSELECT MAX(as_of_date) FROM latest"
    )
    return db.execute(text(sql), {"anchor_date": anchor, "current_user_id": user_id, **ef.flex_binds()}).scalar()


def _flex_owned_extra_accounts(db: Session, user_id: int, anchor: date) -> set[int]:
    """Flex-owned legacy accounts with a fact that counted for the old coverage
    date but not for the routed one: an uploaded (non-card) balance, or broker
    cash / positions on a non-Flex broker account."""
    rows = db.execute(
        text(
            "WITH flex_authority_accounts AS (" + ef.flex_authority_accounts_cte() + ")\n"
            "SELECT DISTINCT acc.id FROM account_balance_snapshots abs JOIN accounts acc ON acc.id = abs.account_id\n"
            "WHERE " + ef.counting_sql(ef.BALANCES) + "\n  AND abs.balance_type <> 'credit_balance'\n"
            "  AND NOT (" + ef.not_flex_owned_sql("acc.id") + ")\n"
            "UNION\n"
            "SELECT DISTINCT ba.legacy_account_id FROM portfolio_cash_balance_snapshots cs " + ef.BROKER_CASH.joins() + "\n"
            "WHERE " + ef.counting_sql(ef.BROKER_CASH) + "\n  AND NOT (" + ef.flex_routed_sql("ba") + ")\n"
            "UNION\n"
            "SELECT DISTINCT ba.legacy_account_id FROM portfolio_position_snapshots ps " + ef.POSITIONS.joins() + "\n"
            "WHERE " + ef.counting_sql(ef.POSITIONS) + "\n  AND NOT (" + ef.flex_routed_sql("ba") + ")\n"
            "  AND (" + ef.nav_rule_sql("ba", include_nav_accounts="TRUE") + ")"
        ),
        {"anchor_date": anchor, "current_user_id": user_id, **ef.flex_binds()},
    ).all()
    return {int(r[0]) for r in rows}


def _held_ids(db: Session, today: date, user_id: int | None) -> set[int]:
    return {int(r["instrument_id"]) for r in held_position_rows(db, today=today, user_id=user_id)}


@dataclass
class Impact:
    users: list[int]
    start: date
    end: date
    step: int
    multi_broker_legacy_accounts: dict[int, list[int]] = field(default_factory=dict)
    position_pairs: dict[bool, set[tuple[int, date]]] = field(default_factory=lambda: {False: set(), True: set()})
    position_legacy_accounts: set[int] = field(default_factory=set)
    position_broker_accounts: set[int] = field(default_factory=set)
    rows_now_shown: set[int] = field(default_factory=set)
    rows_no_longer_shown: set[int] = field(default_factory=set)
    coverage_pairs: set[tuple[int, date]] = field(default_factory=set)
    coverage_flex_owned_accounts: set[int] = field(default_factory=set)
    held_days: dict[int | None, int] = field(default_factory=dict)
    held_instruments: set[int] = field(default_factory=set)
    held_now_differs: int = 0
    utc_today: date | None = None
    local_today: date | None = None


def _anchors(start: date, end: date, step: int) -> list[date]:
    out, day = [], start
    while day <= end:
        out.append(day)
        day += timedelta(days=step)
    if out and out[-1] != end:
        out.append(end)
    return out


def _users(db: Session, user_id: int | None) -> list[int]:
    if user_id is not None:
        return [user_id]
    return [int(r[0]) for r in db.execute(text("SELECT DISTINCT user_id FROM accounts WHERE user_id IS NOT NULL ORDER BY user_id"))]


def _oldest_fact(db: Session) -> date | None:
    value = db.execute(
        text(
            "SELECT MIN(d) FROM ("
            "SELECT MIN(report_date) AS d FROM portfolio_position_snapshots UNION ALL "
            "SELECT MIN(report_date) FROM portfolio_nav_snapshots UNION ALL "
            "SELECT MIN(report_date) FROM portfolio_cash_balance_snapshots UNION ALL "
            "SELECT MIN(as_of_date) FROM account_balance_snapshots) _all"
        )
    ).scalar()
    if value is None:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _multi_broker_legacy_accounts(db: Session, users: Sequence[int]) -> dict[int, list[int]]:
    """Legacy accounts (of ``users``) with 2+ broker accounts holding authoritative position snapshots."""
    rows = db.execute(
        text(
            "SELECT ba.legacy_account_id, ba.id FROM broker_accounts ba JOIN accounts acc ON acc.id = ba.legacy_account_id "
            "WHERE EXISTS (SELECT 1 FROM portfolio_position_snapshots ps WHERE ps.broker_account_id = ba.id AND "
            + ef.authoritative_sql("ps")
            + ") ORDER BY ba.legacy_account_id, ba.id"
        )
    ).all()
    wanted = set(users)
    owners = {int(r[0]): int(r[1]) for r in db.execute(text("SELECT id, user_id FROM accounts WHERE user_id IS NOT NULL"))}
    by_account: dict[int, list[int]] = {}
    for legacy, broker in rows:
        if owners.get(int(legacy)) in wanted:
            by_account.setdefault(int(legacy), []).append(int(broker))
    return {k: v for k, v in by_account.items() if len(v) > 1}


def measure(db: Session, *, start: date, end: date, step: int = 1, user_id: int | None = None) -> Impact:
    users = _users(db, user_id)
    impact = Impact(users=users, start=start, end=end, step=step)
    impact.multi_broker_legacy_accounts = _multi_broker_legacy_accounts(db, users)
    anchors = _anchors(start, end, step)
    for user in users:
        held_before: set[int] | None = None
        days_changed = 0
        for anchor in anchors:
            for include_nav in (False, True):
                old = _position_rows(db, user, anchor, include_nav=include_nav, old=True)
                new = _position_rows(db, user, anchor, include_nav=include_nav, old=False)
                if old != new:
                    impact.position_pairs[include_nav].add((user, anchor))
                    for row in old ^ new:
                        impact.position_broker_accounts.add(row[1])
                        impact.position_legacy_accounts.add(row[2])
                    impact.rows_now_shown.update(r[0] for r in new - old)
                    impact.rows_no_longer_shown.update(r[0] for r in old - new)
            if coverage_as_of(db, user, anchor, routed=True) != coverage_as_of(db, user, anchor, routed=False):
                impact.coverage_pairs.add((user, anchor))
                impact.coverage_flex_owned_accounts |= _flex_owned_extra_accounts(db, user, anchor)
            held = _held_ids(db, anchor, user)
            day_before = _held_ids(db, anchor - timedelta(days=1), user) if step != 1 or held_before is None else held_before
            if held != day_before:
                days_changed += 1
                impact.held_instruments |= held ^ day_before
            held_before = held
        impact.held_days[user] = days_changed
    impact.held_days[None] = sum(
        1 for anchor in anchors if _held_ids(db, anchor, None) != _held_ids(db, anchor - timedelta(days=1), None)
    )
    impact.utc_today = app_now().astimezone(timezone.utc).date()
    impact.local_today = app_today()
    if impact.utc_today != impact.local_today:
        impact.held_now_differs = len(_held_ids(db, impact.local_today, None) ^ _held_ids(db, impact.utc_today, None))
    return impact


def _ids(values: Any) -> str:
    items = sorted(values)
    return ", ".join(str(v) for v in items) if items else "none"


def _span(pairs: set[tuple[int, date]]) -> str:
    if not pairs:
        return "0"
    days = sorted({d for _u, d in pairs})
    return f"{len(pairs)} (users: {_ids({u for u, _d in pairs})}; days {days[0]} .. {days[-1]})"


def report(impact: Impact) -> list[str]:
    lines = [
        "Read-only impact of #242 (D-62) on this database.",
        f"Days {impact.start} .. {impact.end}, every {impact.step} day(s); users: {_ids(impact.users)}.",
        "",
        "1. Owner key: positions newest per broker account (was: per legacy account).",
        f"   Legacy accounts with 2+ broker accounts holding authoritative position snapshots: "
        f"{len(impact.multi_broker_legacy_accounts)}"
        + "".join(f"\n     legacy account {k}: broker accounts {_ids(v)}" for k, v in sorted(impact.multi_broker_legacy_accounts.items())),
        f"   (user, day) pairs where the positions reader differs: {_span(impact.position_pairs[False])}",
        f"   ... with NAV accounts' own positions (holdings detail): {_span(impact.position_pairs[True])}",
        f"   Legacy accounts affected: {_ids(impact.position_legacy_accounts)}; broker accounts: {_ids(impact.position_broker_accounts)}",
        f"   Position snapshot rows now shown on some day: {len(impact.rows_now_shown)}; no longer shown: "
        f"{len(impact.rows_no_longer_shown)} (always 0: the old rule kept only the broker accounts on the",
        "   legacy account's newest date, the new one keeps each broker account's newest, so it only adds rows)",
        "   NAV and broker cash: already newest per broker account, unchanged.",
        "",
        "2. Coverage date: Flex-routed (was: every account's facts).",
        f"   (user, day) pairs where the coverage date differs: {_span(impact.coverage_pairs)}",
        f"   Flex-owned legacy accounts whose uploaded balances / non-Flex facts set it: {_ids(impact.coverage_flex_owned_accounts)}",
        "",
        f"3. Held positions for pricing: today = app clock ({current_timezone_name()}) (was: UTC date).",
        "   Days on which the held list differs from the day before (the old rule showed the day before's",
        "   list for the first hours of each such day, e.g. 00:00-08:00 in Singapore):",
        *(f"     user {u}: {n}" for u, n in sorted((k, v) for k, v in impact.held_days.items() if k is not None)),
        f"     all users (the quote job's check): {impact.held_days.get(None, 0)}",
        f"   Instruments involved on those days: {len(impact.held_instruments)}",
        f"   Now: app today {impact.local_today}, UTC today {impact.utc_today}; instruments differing now: {impact.held_now_differs}",
    ]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only impact of #242 (D-62). Prints counts and ids only.")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=None)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
    parser.add_argument("--step", type=int, default=1, help="Every N-th day (default 1).")
    parser.add_argument("--user-id", type=int, default=None)
    args = parser.parse_args(argv)
    if args.step < 1:
        parser.error("--step must be at least 1")

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        start = args.start or _oldest_fact(db)
        end = args.end or app_today()
        if start is None:
            print("No canonical facts: nothing to compare.")
            return 0
        print("\n".join(report(measure(db, start=start, end=end, step=args.step, user_id=args.user_id))))
    finally:
        db.rollback()
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
