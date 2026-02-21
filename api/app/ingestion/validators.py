from __future__ import annotations

from typing import List, Dict


def validate_transactions(transactions: List[Dict]) -> list[str]:
    warnings: list[str] = []
    if not transactions:
        warnings.append("No transactions parsed.")
        return warnings
    for i, tx in enumerate(transactions):
        if tx.get("amount") is None:
            warnings.append(f"Missing amount at index {i}")
        if not tx.get("currency"):
            warnings.append(f"Missing currency at index {i}")
        if not tx.get("type"):
            warnings.append(f"Missing type at index {i}")
    return warnings
