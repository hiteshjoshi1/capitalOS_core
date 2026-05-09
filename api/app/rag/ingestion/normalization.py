from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.rag.ingestion.parser import DocumentSection, StructuredParseResult


def normalize_with_ingestion_config(
    parsed: StructuredParseResult,
    ingestion_config: dict[str, Any] | None,
) -> StructuredParseResult:
    if not ingestion_config:
        return parsed

    normalized = deepcopy(parsed)

    split_markers = ingestion_config.get("split_markers")
    if not normalized.sections and isinstance(split_markers, list) and split_markers:
        normalized.sections = synthesize_sections_from_markers(
            normalized.clean_text or normalized.raw_text,
            split_markers,
        )

    section_splits = ingestion_config.get("section_splits")
    if not isinstance(section_splits, list) or not section_splits:
        return normalized

    normalized.sections = apply_section_splits(list(normalized.sections or []), section_splits)
    return normalized


def synthesize_sections_from_markers(
    text: str,
    split_markers: list[dict[str, Any]],
) -> list[DocumentSection]:
    if not split_markers:
        return []

    positions: list[tuple[int, str, str, int]] = []
    search_start = 0
    for rule in split_markers:
        marker_text = str(rule.get("marker") or "").strip()
        heading = str(rule.get("heading") or marker_text).strip()
        if not marker_text:
            raise RuntimeError("split_markers entries require a non-empty marker")
        position = text.find(marker_text, search_start)
        if position < 0:
            raise RuntimeError(f"split_marker='{marker_text}' did not match any text in the document.")
        positions.append((position, marker_text, heading, int(rule.get("level") or 1)))
        search_start = position + len(marker_text)

    sections: list[DocumentSection] = []
    for index, (position, marker_text, heading, level) in enumerate(positions):
        next_position = positions[index + 1][0] if index + 1 < len(positions) else len(text)
        body = text[position + len(marker_text) : next_position].strip()
        sections.append(
            DocumentSection(
                heading=heading,
                level=level,
                content=body,
                content_type="text",
                table_markdown=None,
                table_rows=None,
                items=None,
            )
        )
    return sections


def apply_section_splits(
    sections: list[DocumentSection],
    section_splits: list[dict[str, Any]],
) -> list[DocumentSection]:
    if not section_splits:
        return sections

    result: list[DocumentSection] = []
    for section in sections:
        applied = False
        for rule in section_splits:
            if rule.get("match_heading") != section.heading:
                continue
            split_sections = _split_section_by_markers(section, rule.get("markers") or [])
            if split_sections is None:
                break
            result.extend(split_sections)
            applied = True
            break
        if not applied:
            result.append(section)
    return result


def _split_section_by_markers(
    section: DocumentSection,
    markers: list[dict[str, Any]],
) -> list[DocumentSection] | None:
    if not markers:
        return None

    content = section.content or ""
    positions: list[tuple[int, dict[str, Any]]] = []
    search_start = 0
    for marker in markers:
        marker_text = str(marker.get("marker") or "").strip()
        if not marker_text:
            return None
        position = content.find(marker_text, search_start)
        if position < 0:
            return None
        positions.append((position, marker))
        search_start = position + len(marker_text)

    split_sections: list[DocumentSection] = [
        DocumentSection(
            heading=section.heading,
            level=section.level,
            content=content[: positions[0][0]].strip(),
            content_type=section.content_type,
            table_markdown=section.table_markdown,
            table_rows=section.table_rows,
            items=section.items,
            metadata=dict(section.metadata or {}),
        )
    ]

    for index, (position, marker) in enumerate(positions):
        marker_text = str(marker.get("marker") or "")
        next_position = positions[index + 1][0] if index + 1 < len(positions) else len(content)
        body = content[position + len(marker_text) : next_position].strip()
        split_sections.append(
            DocumentSection(
                heading=str(marker.get("heading") or marker_text),
                level=int(marker.get("level") or section.level),
                content=body,
                content_type=section.content_type,
                table_markdown=None,
                table_rows=section.table_rows,
                items=section.items,
                metadata=dict(section.metadata or {}),
            )
        )

    return split_sections
