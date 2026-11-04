"""One function per dashboard response, composing the valuation modules."""
from __future__ import annotations

import os


def _summary_top_holdings_limit() -> int:
    raw = os.getenv("DASHBOARD_TOP_HOLDINGS_LIMIT", "200")
    try:
        limit = int(raw)
    except ValueError:
        limit = 200
    # Keep payload bounded while allowing rich detail pages to paginate client-side.
    return max(20, min(limit, 500))


