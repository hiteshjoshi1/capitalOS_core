from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.parser_registry import ParserRegistry


def lookup_parser_key(db: Session, signature: str) -> str | None:
    row = db.query(ParserRegistry).filter(ParserRegistry.format_signature == signature).one_or_none()
    return row.parser_key if row else None


def register_signature(db: Session, signature: str, parser_key: str, version: int = 1) -> ParserRegistry:
    existing = db.query(ParserRegistry).filter(ParserRegistry.format_signature == signature).one_or_none()
    if existing:
        return existing
    row = ParserRegistry(format_signature=signature, parser_key=parser_key, version=version)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
