from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParseResult:
    transactions: list[dict[str, Any]]
    positions: list[dict[str, Any]]
    section_counts: dict[str, int]
    parser_meta: dict[str, Any] = field(default_factory=dict)
