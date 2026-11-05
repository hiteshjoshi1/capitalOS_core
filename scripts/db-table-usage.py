#!/usr/bin/env python3
"""Usage report for the candidate dead tables (#158, #130 finding 1.9). Read-only.

For each candidate table it prints:
- where the app code (api/app) reads it (FROM / JOIN), writes it (INSERT / UPDATE /
  DELETE), maps it with an ORM model, or names it as a string (dynamic SQL);
- the same for the dev seeds (migrations/seed_dummy*.sql), scripts/ and the tests;
- its exact row count in a database, when --psql is given (a read-only psql command;
  `make db-table-usage` passes this stack's, in a READ ONLY session);
- what a later destructive migration would have to do for it.

Nothing is dropped or changed: the owner decides on the drop later (#158).

    make db-table-usage                       # this stack's database
    scripts/db-table-usage.py                 # code scan only, no database
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Candidates from #130 finding 1.9, with what dropping each would take.
CANDIDATES: dict[str, str] = {
    "asset_identifiers": "DROP TABLE (FKs out to assets / broker_instruments only; nothing references it).",
    "portfolio_event_groups": (
        "Drop the event_group_id FKs (and columns, if never set) on portfolio_cash_ledger_entries, "
        "portfolio_trades and portfolio_corporate_action_events, then DROP TABLE."
    ),
    "transfer_links": (
        "DROP TABLE; remove its explicit delete in app/ingestion/undo.py and its rows in "
        "migrations/seed_dummy.sql / seed_dummy_cleanup.sql in the same change."
    ),
    "wallet_accounts": "DROP TABLE (FKs out to accounts / chains only).",
    "raw_files": "DROP TABLE (before ingestion_jobs: it references it).",
    "ingestion_jobs": "DROP TABLE after raw_files (the upload flow uses import_jobs).",
    "crypto_user_networth": (
        "Remove its ownership count/reassign in app/services/ownership.py and the ORM model "
        "(app/models/crypto.py), then DROP TABLE."
    ),
    "portfolio_report_metrics": (
        "Stop the IBKR Flex import writing it (app/portfolio/ibkr_flex.py), then DROP TABLE. "
        "Its rows are also kept in the raw Flex XMLs."
    ),
    "portfolio_fx_rates": "Keep: read by app/fx.py since #197 (statement FX rates). Not dead any more.",
    "positions": (
        "Keep until its last readers go: legacy_backfill.py, parity_report.py and "
        "market_data/service.py held_asset_ids (#153); "
        "then drop its BEFORE DELETE/UPDATE/INSERT guard triggers (057) and DROP TABLE."
    ),
}

SCAN = {
    "app": [ROOT / "api" / "app"],
    "seeds": [ROOT / "migrations" / "seed_dummy.sql", ROOT / "migrations" / "seed_dummy_cleanup.sql"],
    "scripts": [ROOT / "scripts"],
    "tests": [ROOT / "api" / "tests"],
}


def _files(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for path in paths:
        if path.is_dir():
            out.extend(p for p in sorted(path.rglob("*")) if p.suffix in {".py", ".sql", ".sh"} and p.is_file())
        elif path.is_file():
            out.append(path)
    return [p for p in out if p.resolve() != Path(__file__).resolve()]


def _code_lines(path: Path) -> list[tuple[int, str]]:
    lines = []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("#", "--")):
            continue
        lines.append((number, line))
    return lines


def _orm_classes(table: str) -> list[str]:
    classes = []
    pattern = re.compile(r"__tablename__\s*=\s*[\"']%s[\"']" % re.escape(table))
    for path in _files(SCAN["app"]):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in pattern.finditer(text):
            head = text[: match.start()]
            found = re.findall(r"^class\s+(\w+)\s*[(:]", head, re.MULTILINE)
            if found:
                classes.append(found[-1])
    return classes


def scan(table: str) -> dict[str, dict[str, list[str]]]:
    t = re.escape(table)
    kinds = {
        "reads": re.compile(rf"(?<!DELETE )(?<!delete )\b(FROM|JOIN)\s+{t}\b", re.IGNORECASE),
        "writes": re.compile(rf"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+{t}\b", re.IGNORECASE),
    }
    if "_" in table:  # a plain word ("positions") is also a dict key everywhere
        kinds["named"] = re.compile(rf"[\"']{t}[\"']")
    classes = _orm_classes(table)
    if classes:
        kinds["orm"] = re.compile(r"\b(%s)\b" % "|".join(map(re.escape, classes)))
    result: dict[str, dict[str, list[str]]] = {}
    for area, paths in SCAN.items():
        hits: dict[str, list[str]] = {}
        for path in _files(paths):
            rel = str(path.relative_to(ROOT))
            for number, line in _code_lines(path):
                for kind, pattern in kinds.items():
                    if pattern.search(line):
                        if kind == "named" and (kinds["reads"].search(line) or kinds["writes"].search(line)):
                            continue
                        if kind == "orm" and "__tablename__" in line:
                            continue
                        hits.setdefault(kind, []).append(f"{rel}:{number}")
        result[area] = hits
    return result


def row_counts(psql: str, tables: list[str]) -> dict[str, str]:
    selects = " UNION ALL ".join(
        f"SELECT '{t}', CASE WHEN to_regclass('public.{t}') IS NULL THEN 'absent' "
        f"ELSE (xpath('/row/c/text()', query_to_xml('SELECT COUNT(*) AS c FROM public.{t}', false, true, '')))[1]::text END"
        for t in tables
    )
    sql = f"BEGIN TRANSACTION READ ONLY; {selects}; ROLLBACK;"
    out = subprocess.run(
        [*shlex.split(psql), "-At", "-F", "\t", "-c", sql],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    counts: dict[str, str] = {}
    for line in out.splitlines():
        if "\t" in line:
            name, count = line.split("\t", 1)
            counts[name] = count
    return counts


def _summary(hits: dict[str, list[str]]) -> str:
    if not hits:
        return "none"
    return "; ".join(f"{kind} {len(where)}x ({', '.join(where[:4])}{', ...' if len(where) > 4 else ''})" for kind, where in hits.items())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--psql", default="", help="A read-only psql command for row counts (make db-table-usage sets it).")
    args = parser.parse_args(argv)
    counts = row_counts(args.psql, list(CANDIDATES)) if args.psql else {}
    for table, plan in CANDIDATES.items():
        usage = scan(table)
        app = usage["app"]
        reads = bool(app.get("reads") or app.get("orm"))
        writes = bool(app.get("writes"))
        if reads and writes:
            verdict = "read and written by the app"
        elif reads:
            verdict = "read by the app"
        elif writes:
            verdict = "written by the app, never read"
        elif app.get("named"):
            verdict = "only named in app code (dynamic SQL)"
        else:
            verdict = "never read or written by the app"
        print(f"== {table}: {verdict}" + (f"; rows: {counts.get(table, '?')}" if counts else ""))
        for area in ("app", "seeds", "scripts", "tests"):
            print(f"   {area:8} {_summary(usage[area])}")
        print(f"   later:   {plan}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
