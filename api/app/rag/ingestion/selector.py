"""
Selective ingestion controls for HTML/text sources.

Applies deterministic section-selection rules to a list of DocumentSection
objects produced by the parser.  All matching is case-insensitive substring.

Rules:
  start_after      — include only sections *after* the first heading that
                     contains the marker string.
  stop_before      — stop including sections when a heading matches.
  include_headings — only include sections whose heading matches any entry.
  exclude_sections — drop sections whose heading matches any entry.

If all rules are absent (None / empty list) the sections list is returned
unchanged.

If rules are present but produce zero selected sections, NoContentSelectedError
is raised so the caller can fail the ingestion job with a clear reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class NoContentSelectedError(RuntimeError):
    """Raised when selective-ingestion rules produce no usable sections."""


@dataclass
class SelectiveIngestionOptions:
    """Optional controls for selecting a sub-set of document sections."""

    start_after: Optional[str] = None
    stop_before: Optional[str] = None
    include_headings: list[str] = field(default_factory=list)
    exclude_sections: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return (
            not self.start_after
            and not self.stop_before
            and not self.include_headings
            and not self.exclude_sections
        )

    def to_dict(self) -> dict:
        return {
            "start_after": self.start_after,
            "stop_before": self.stop_before,
            "include_headings": self.include_headings,
            "exclude_sections": self.exclude_sections,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SelectiveIngestionOptions":
        return cls(
            start_after=d.get("start_after"),
            stop_before=d.get("stop_before"),
            include_headings=d.get("include_headings") or [],
            exclude_sections=d.get("exclude_sections") or [],
        )


def _heading_matches(heading: Optional[str], marker: str) -> bool:
    """Case-insensitive substring match against a section heading."""
    if not heading:
        return False
    return marker.lower() in heading.lower()


def _collect_descendant_indexes(sections: list, start_index: int) -> set[int]:
    """
    Return the index of the matched heading plus any immediately following
    descendant sections until the hierarchy returns to the same-or-higher level.
    """
    matched = sections[start_index]
    matched_level = getattr(matched, "level", 1) or 1
    indexes = {start_index}
    for idx in range(start_index + 1, len(sections)):
        section = sections[idx]
        heading = getattr(section, "heading", None)
        if not heading:
            indexes.add(idx)
            continue
        section_level = getattr(section, "level", 1) or 1
        if section_level <= matched_level:
            break
        indexes.add(idx)
    return indexes


def apply_selective_options(sections: list, options: SelectiveIngestionOptions) -> list:
    """
    Filter *sections* according to *options*.

    Parameters
    ----------
    sections:
        List of DocumentSection objects (from parser.py).
    options:
        SelectiveIngestionOptions instance describing the desired selection.

    Returns
    -------
    Filtered list of DocumentSection objects.

    Raises
    ------
    NoContentSelectedError
        When rules are non-empty but produce zero remaining sections.
    """
    if options.is_empty():
        return sections

    result = list(sections)

    # ── start_after ──────────────────────────────────────────────────────────
    if options.start_after:
        marker = options.start_after
        start_idx: Optional[int] = None
        for i, section in enumerate(result):
            if _heading_matches(section.heading, marker):
                start_idx = i + 1  # begin *after* the matching heading
                break
        if start_idx is None:
            raise NoContentSelectedError(
                f"start_after='{marker}' did not match any heading in the document."
            )
        result = result[start_idx:]

    # ── stop_before ──────────────────────────────────────────────────────────
    if options.stop_before:
        marker = options.stop_before
        stop_idx: Optional[int] = None
        for i, section in enumerate(result):
            if _heading_matches(section.heading, marker):
                stop_idx = i
                break
        if stop_idx is not None:
            result = result[:stop_idx]
        # stop_before not found is not an error — we just include everything

    # ── include_headings ─────────────────────────────────────────────────────
    if options.include_headings:
        markers = [m.lower() for m in options.include_headings]
        matched_indexes: set[int] = set()
        for idx, section in enumerate(result):
            heading = getattr(section, "heading", None)
            if heading and any(m in heading.lower() for m in markers):
                matched_indexes.update(_collect_descendant_indexes(result, idx))
        result = [section for idx, section in enumerate(result) if idx in matched_indexes]

    # ── exclude_sections ─────────────────────────────────────────────────────
    if options.exclude_sections:
        markers = [m.lower() for m in options.exclude_sections]
        excluded_indexes: set[int] = set()
        for idx, section in enumerate(result):
            heading = getattr(section, "heading", None)
            if heading and any(m in heading.lower() for m in markers):
                excluded_indexes.update(_collect_descendant_indexes(result, idx))
        result = [section for idx, section in enumerate(result) if idx not in excluded_indexes]

    # ── guard: rules were specified but produced nothing ──────────────────────
    if not result:
        raise NoContentSelectedError(
            "Selective-ingestion rules produced no usable content from the source. "
            f"Options applied: {options.to_dict()}"
        )

    return result
