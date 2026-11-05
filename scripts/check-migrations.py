#!/usr/bin/env python3
"""Migration lint (#158, #130 finding 1.11), run by `make lint` (and so by CI).

Checks every migrations/NNN_*.sql file:
- no transaction control of its own (BEGIN; / START TRANSACTION / COMMIT / ROLLBACK / END;
  at statement level): `make db-migrate` runs each file in one transaction (psql -1) with
  its schema_migrations row, and a COMMIT inside would commit half a migration;
- no two files share a numeric prefix;
- the name is NNN_lower_snake_case.sql.

PL/pgSQL blocks (DO $$ ... BEGIN ... END $$) are fine: only a bare BEGIN; is rejected.
Applied migrations are never edited (CLAUDE.md), so the files that predate these rules
are allow-listed below instead of fixed. See migrations/README.md.

    scripts/check-migrations.py [migrations-dir]
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

# Applied everywhere before this lint existed; never edit an applied migration.
# 028_crypto_base_asset.sql wraps itself in BEGIN; ... COMMIT; (harmless under psql -1:
# the inner BEGIN only warns and its COMMIT ends the runner's transaction early, before the
# schema_migrations insert; it is already applied on every existing database).
TRANSACTION_ALLOWED = {"028_crypto_base_asset.sql"}
# Two files were numbered 028 before the rule; both are applied, by filename.
DUPLICATE_PREFIX_ALLOWED = {"028": {"028_crypto_base_asset.sql", "028_fix_dbs_salary_type.sql"}}

_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
_NUMBERED = re.compile(r"^\d{3}_.*\.sql$")
# A whole statement that is transaction control.
_TXN = re.compile(
    r"^(BEGIN(\s+(TRANSACTION|WORK))?|START\s+TRANSACTION\b.*|COMMIT\b.*|ROLLBACK\b.*|END(\s+(TRANSACTION|WORK))?)$",
    re.IGNORECASE | re.DOTALL,
)
_DOLLAR = re.compile(r"\$[A-Za-z_]*\$")


def _strip(sql: str) -> list[tuple[int, str]]:
    """(line number, code) outside comments, string literals and dollar-quoted bodies."""
    out: list[tuple[int, str]] = []
    in_block_comment = False
    dollar: str | None = None
    for number, raw in enumerate(sql.splitlines(), 1):
        line = raw
        code = ""
        i = 0
        while i < len(line):
            if in_block_comment:
                end = line.find("*/", i)
                if end < 0:
                    i = len(line)
                    continue
                in_block_comment = False
                i = end + 2
                continue
            if dollar is not None:
                end = line.find(dollar, i)
                if end < 0:
                    i = len(line)
                    continue
                i = end + len(dollar)
                dollar = None
                code += " "
                continue
            if line.startswith("--", i):
                break
            if line.startswith("/*", i):
                in_block_comment = True
                i += 2
                continue
            if line[i] == "'":
                end = line.find("'", i + 1)
                while end >= 0 and line.startswith("''", end):
                    end = line.find("'", end + 2)
                i = len(line) if end < 0 else end + 1
                code += "''"
                continue
            match = _DOLLAR.match(line, i)
            if match:
                dollar = match.group(0)
                i = match.end()
                code += " "
                continue
            code += line[i]
            i += 1
        out.append((number, code))
    return out


def _statements(sql: str) -> list[tuple[int, str]]:
    """(first line, text) of each top-level statement, comments and quoted bodies removed."""
    statements: list[tuple[int, str]] = []
    current = ""
    start = 0
    for number, code in _strip(sql):
        for i, part in enumerate(code.split(";")):
            if i > 0:
                if current.strip():
                    statements.append((start, " ".join(current.split())))
                current = ""
            if part.strip() and not current.strip():
                start = number
            current += part + "\n"
    if current.strip():
        statements.append((start, " ".join(current.split())))
    return statements


def check(directory: Path) -> list[str]:
    errors: list[str] = []
    by_prefix: dict[str, list[str]] = defaultdict(list)
    files = sorted(p for p in directory.iterdir() if p.is_file() and _NUMBERED.match(p.name))
    for path in files:
        name = path.name
        match = _NAME.match(name)
        if not match:
            errors.append(f"{name}: name must be NNN_lower_snake_case.sql")
            continue
        by_prefix[match.group(1)].append(name)
        if name in TRANSACTION_ALLOWED:
            continue
        for number, statement in _statements(path.read_text(encoding="utf-8")):
            if _TXN.match(statement):
                errors.append(
                    f"{name}:{number}: transaction control ({statement.split()[0]}) in a migration; "
                    "make db-migrate already runs each file in one transaction"
                )
    for prefix, names in sorted(by_prefix.items()):
        if len(names) > 1 and set(names) != DUPLICATE_PREFIX_ALLOWED.get(prefix, set()):
            errors.append(f"duplicate migration number {prefix}: {', '.join(names)}")
    return errors


def main(argv: list[str]) -> int:
    directory = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent / "migrations"
    errors = check(directory)
    for error in errors:
        print(f"migration lint: {error}", file=sys.stderr)
    if errors:
        print("See migrations/README.md for the rules.", file=sys.stderr)
        return 1
    count = sum(1 for p in directory.iterdir() if _NUMBERED.match(p.name))
    print(f"migration lint: {count} migrations OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
