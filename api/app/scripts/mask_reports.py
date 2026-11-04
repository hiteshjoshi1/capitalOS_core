"""Mask account numbers in existing import reports (#190), one-off.

New reports are written masked (``app.ingestion.masking``); this brings the
older ``data/reports/*.json`` in line. Only the in-scope fields change:
``parser_meta``'s account-identifier fields and ``signature_debug``. Transaction
descriptions (``preview_transactions``) are left as they are.

Dry run by default: it lists, per file, the fields it would change (field
names only, never values). ``--apply`` rewrites those files. It refuses any
directory other than this checkout's ``data/reports`` (``$DATA_DIR/reports``),
and skips files that resolve outside it (symlinks).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.ingestion.masking import mask_report


def allowed_reports_dir() -> Path:
    data_dir = os.getenv("DATA_DIR", os.path.join(os.getcwd(), "data"))
    return (Path(data_dir) / "reports").resolve()


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def mask_reports(reports_dir: Path, *, apply: bool) -> dict[str, int]:
    """Mask every report in ``reports_dir``; returns counts. Raises
    ``ValueError`` for a directory that isn't the allowed one."""
    root = allowed_reports_dir()
    target = reports_dir.resolve()
    if target != root:
        raise ValueError(f"refusing {reports_dir}: only {root} (this checkout's data/reports) is allowed")
    key = "changed" if apply else "would_change"
    counts = {"files": 0, key: 0, "skipped": 0}
    if not target.is_dir():
        return counts
    for path in sorted(target.glob("*.json")):
        counts["files"] += 1
        real = path.resolve()
        if path.is_symlink() or not _inside(real, root) or not real.is_file():
            print(f"skip {path.name}: not a regular file inside {root}")
            counts["skipped"] += 1
            continue
        try:
            report = json.loads(real.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(f"skip {path.name}: unreadable ({exc.__class__.__name__})")
            counts["skipped"] += 1
            continue
        if not isinstance(report, dict):
            counts["skipped"] += 1
            continue
        masked, fields = mask_report(report)
        if not fields:
            continue
        counts[key] += 1
        print(f"{'masked' if apply else 'would mask'} {path.name}: {', '.join(fields)}")
        if apply:
            tmp = real.with_name(real.name + ".masking")
            tmp.write_text(json.dumps(masked, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, real)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mask account numbers in existing import reports (#190).")
    parser.add_argument("--apply", action="store_true", help="Rewrite the files. Without it, only lists them.")
    parser.add_argument(
        "--reports-dir",
        default=None,
        help="Must be this checkout's data/reports (the default); anything else is refused.",
    )
    args = parser.parse_args(argv)
    reports_dir = Path(args.reports_dir) if args.reports_dir else allowed_reports_dir()
    try:
        counts = mask_reports(reports_dir, apply=args.apply)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    summary = ", ".join(f"{k}={v}" for k, v in counts.items())
    print(f"{'applied' if args.apply else 'dry run (APPLY=1 to write)'}: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
