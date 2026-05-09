from __future__ import annotations

import re
from typing import Any

from app.rag.ingestion.parser import DocumentSection


def normalize_table_rows(rows: list[list[str]] | None) -> list[list[str]]:
    if not rows:
        return []
    width = max(len(row) for row in rows)
    return [list(row) + [""] * (width - len(row)) for row in rows]


def markdown_table_to_rows(markdown: str | None) -> list[list[str]]:
    if not markdown:
        return []
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    rows: list[list[str]] = []
    for index, line in enumerate(lines):
        if not line.startswith("|") or not line.endswith("|"):
            return []
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if index == 1 and all(re.fullmatch(r":?-{3,}:?", cell or "---") for cell in cells):
            continue
        rows.append(cells)
    return normalize_table_rows(rows)


def list_items_from_content(section: DocumentSection) -> list[str]:
    if section.items:
        return [item.strip() for item in section.items if item.strip()]
    items: list[str] = []
    for line in section.content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^[-*+]\s+", "", stripped)
        stripped = re.sub(r"^\d+[.)]\s+", "", stripped)
        items.append(stripped)
    return items


def build_content_blocks(
    sections: list[DocumentSection],
    *,
    fallback_text: str,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current_heading: str | None = None

    def _append(
        block_type: str,
        *,
        level: int | None = None,
        text: str | None = None,
        items: list[str] | None = None,
        table_markdown: str | None = None,
        table_rows: list[list[str]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        order = len(blocks)
        block_metadata = dict(metadata or {})
        block = {
            "block_id": f"blk-{order:04d}",
            "type": block_type,
            "order": order,
            "level": level,
            "text": text,
            "items": items,
            "table_markdown": table_markdown,
            "table_rows": table_rows,
            "metadata": block_metadata,
        }
        blocks.append(block)

    def _add_paragraphs(text: str, *, metadata: dict[str, Any]) -> None:
        paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
        for paragraph in paragraphs:
            compact = re.sub(r"\s+", " ", paragraph).strip()
            if compact:
                _append("paragraph", text=compact, metadata=metadata)

    candidate_sections = list(sections or [])
    if not candidate_sections and fallback_text.strip():
        candidate_sections = [
            DocumentSection(
                heading=None,
                level=1,
                content=part.strip(),
                content_type="text",
            )
            for part in re.split(r"\n{2,}", fallback_text)
            if part.strip()
        ]

    for section in candidate_sections:
        metadata = dict(section.metadata or {})
        heading_text = (section.heading or "").strip() or None
        if section.content_type == "heading" and heading_text:
            current_heading = heading_text
            _append("heading", level=section.level or 1, text=heading_text, metadata=metadata)
            continue

        if heading_text and heading_text != current_heading:
            current_heading = heading_text
            _append("heading", level=section.level or 1, text=heading_text, metadata=metadata)

        if current_heading and "heading_context" not in metadata:
            metadata["heading_context"] = current_heading

        if section.content_type == "table":
            rows = normalize_table_rows(section.table_rows) or markdown_table_to_rows(section.table_markdown)
            _append(
                "table",
                text=(section.content or "").strip() or None,
                table_markdown=section.table_markdown,
                table_rows=rows or None,
                metadata=metadata,
            )
            continue

        if section.content_type == "list":
            items = list_items_from_content(section)
            if items:
                _append("list", items=items, metadata=metadata)
            continue

        if section.content_type == "quote":
            quote = re.sub(r"\s+", " ", (section.content or "").strip())
            if quote:
                _append("quote", text=quote, metadata=metadata)
            continue

        _add_paragraphs(section.content or "", metadata=metadata)

    return blocks
