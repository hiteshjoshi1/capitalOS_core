from __future__ import annotations

import json
import os
from typing import Any


def write_report(report_path: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
