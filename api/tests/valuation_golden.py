"""Golden-file plumbing for the valuation harness (#142).

A golden file is ``tests/golden/valuation/<scenario>.json``: the responses of
the main valuation endpoints for the synthetic household (tests/valuation_household.py)
at one frozen "now", as pretty JSON with sorted keys and floats rounded, so a
change reads as a normal diff in review.

Regenerate deliberately, after checking that the change in numbers is wanted:

    UPDATE_GOLDEN=1 pytest tests/test_valuation_golden.py      # in api/
    make golden-update                                          # same, in Docker

then review ``git diff api/tests/golden`` like any other change.
"""
from __future__ import annotations

import difflib
import json
import os
from pathlib import Path
from typing import Any

GOLDEN_DIR = Path(__file__).parent / "golden" / "valuation"
FLOAT_DIGITS = 4

# Fields that carry the wall-clock time a value was computed, not the value.
VOLATILE_KEYS = frozenset({"computed_at"})


def normalise(value: Any) -> Any:
    if isinstance(value, float):
        rounded = round(value, FLOAT_DIGITS)
        return 0.0 if rounded == 0 else rounded
    if isinstance(value, dict):
        return {k: ("<volatile>" if k in VOLATILE_KEYS and v is not None else normalise(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [normalise(v) for v in value]
    return value


def dumps(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def updating() -> bool:
    return os.getenv("UPDATE_GOLDEN", "").strip().lower() in {"1", "true", "yes"}


def check_golden(name: str, actual: dict[str, Any]) -> None:
    """Compare ``actual`` with the stored golden, or write it with UPDATE_GOLDEN=1.

    On a mismatch the assertion message is a unified diff per changed endpoint."""
    path = GOLDEN_DIR / f"{name}.json"
    actual = normalise(actual)
    if updating():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(actual), encoding="utf-8")
        return
    assert path.exists(), f"No golden file {path}. Create it with UPDATE_GOLDEN=1 (see tests/valuation_golden.py)."
    expected = json.loads(path.read_text(encoding="utf-8"))
    if actual == expected:
        return
    expected_responses = expected.get("responses", {})
    actual_responses = actual.get("responses", {})
    chunks = []
    for key in sorted(set(expected_responses) | set(actual_responses)):
        old, new = expected_responses.get(key), actual_responses.get(key)
        if old == new:
            continue
        diff = difflib.unified_diff(
            dumps(old).splitlines(), dumps(new).splitlines(), f"golden {key}", f"actual {key}", lineterm="", n=2
        )
        chunks.append("\n".join(diff))
    for key in sorted(set(expected) | set(actual)):
        if key != "responses" and expected.get(key) != actual.get(key):
            chunks.append(f"{key}: golden {expected.get(key)!r} != actual {actual.get(key)!r}")
    raise AssertionError(
        f"Valuation output differs from {path.name} in {len(chunks)} place(s). If the change is intended, "
        "regenerate with UPDATE_GOLDEN=1 and review the diff.\n\n" + "\n\n".join(chunks)
    )
