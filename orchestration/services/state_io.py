from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class StateIOService:
    def __init__(self, repo_root: str) -> None:
        self.repo_root = Path(repo_root)
        self.state_dir = self.repo_root / ".task-flow" / "exports"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def export_state(self, thread_id: str, snapshot: dict[str, Any]) -> str:
        path = self.state_dir / f"{thread_id}.json"
        path.write_text(json.dumps(snapshot, indent=2, default=str))
        return str(path.relative_to(self.repo_root))

    def import_state(self, file_path: str) -> dict[str, Any]:
        path = self.repo_root / file_path
        return json.loads(path.read_text())