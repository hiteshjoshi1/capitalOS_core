#!/usr/bin/env python3
"""Release-age check for a pip lock file (#81, D-1).

Fails when a package that only arrives transitively was uploaded less than --days ago.
Direct pins (the `.in` files) are exempt: they are reviewed one by one, and a young one
can be a deliberate security fix. Hold a young transitive package back by pinning an
older version in the `.in` file, then `make api-lock` again.

    scripts/check-lock-age.py api/requirements.txt api/requirements.in [more .in files]

Stdlib only; needs network (PyPI JSON API).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;\\]+)")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pins(path: str) -> dict[str, str]:
    found: dict[str, str] = {}
    with open(path) as fh:
        for line in fh:
            match = PIN.match(line.strip())
            if match:
                found[normalize(match.group(1))] = match.group(2)
    return found


def uploaded(name: str, version: str) -> datetime:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as resp:
        files = json.load(resp)["urls"]
    return min(datetime.fromisoformat(f["upload_time_iso_8601"].replace("Z", "+00:00")) for f in files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("lock")
    parser.add_argument("direct", nargs="+", help=".in files whose pins are exempt")
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()

    direct: set[str] = set()
    for path in args.direct:
        direct |= set(pins(path))
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=args.days)

    young = []
    for name, version in sorted(pins(args.lock).items()):
        if name in direct:
            continue
        when = uploaded(name, version)
        if when > cutoff:
            young.append(f"  {name}=={version} uploaded {when:%Y-%m-%d}")
    if young:
        print(f"{args.lock}: transitive packages under {args.days} days old (D-1):")
        print("\n".join(young))
        print("Hold each back with an older pin in the .in file, then re-lock.")
        return 1
    print(f"{args.lock}: every transitive package is at least {args.days} days old.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
