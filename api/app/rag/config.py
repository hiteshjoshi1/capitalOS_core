"""Config loader for the user-managed author registry (config/rag_authors.yaml)."""

import os
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from app.models.rag import RagAuthor, RagAuthorCard

# Default path relative to the repo root; override with RAG_AUTHORS_CONFIG env var.
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[5] / "config" / "rag_authors.yaml"


def _config_path() -> Path:
    env = os.getenv("RAG_AUTHORS_CONFIG")
    if env:
        return Path(env)
    return _DEFAULT_CONFIG_PATH


def load_author_config() -> dict[str, Any]:
    """Load and return the raw YAML config dict."""
    path = _config_path()
    if not path.exists():
        raise FileNotFoundError(f"Author config not found: {path}")
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def sync_authors_from_config(db: Session) -> dict[str, int]:
    """
    Upsert authors and author cards from config/rag_authors.yaml into the DB.
    Returns a summary dict with counts of created/updated records.
    """
    data = load_author_config()
    authors_cfg = data.get("authors", [])

    created = 0
    updated = 0

    for entry in authors_cfg:
        author_id = entry["id"]
        lens = entry.get("reasoning_lens", {})

        existing = db.get(RagAuthor, author_id)
        if existing is None:
            author = RagAuthor(
                id=author_id,
                name=entry["name"],
                enabled=entry.get("enabled", True),
                domains=entry.get("domains", []),
                expertise_tags=entry.get("expertise_tags", []),
                overall_weight=float(entry.get("overall_weight", 1.0)),
                role_type=entry.get("role_type"),
                config_source=str(_config_path()),
            )
            db.add(author)
            created += 1
        else:
            existing.name = entry["name"]
            existing.enabled = entry.get("enabled", True)
            existing.domains = entry.get("domains", [])
            existing.expertise_tags = entry.get("expertise_tags", [])
            existing.overall_weight = float(entry.get("overall_weight", 1.0))
            existing.role_type = entry.get("role_type")
            existing.config_source = str(_config_path())
            updated += 1

        # Upsert reasoning card
        card = db.get(RagAuthorCard, author_id)
        focus = lens.get("focus", [])
        avoid = lens.get("avoid", [])
        biases = lens.get("biases", [])

        if card is None:
            card = RagAuthorCard(
                author_id=author_id,
                focus_areas=focus,
                avoid_patterns=avoid,
                biases=biases,
                prompt_adapter={},
                enabled=True,
            )
            db.add(card)
        else:
            card.focus_areas = focus
            card.avoid_patterns = avoid
            card.biases = biases

    db.commit()
    return {"authors_created": created, "authors_updated": updated, "total": created + updated}
