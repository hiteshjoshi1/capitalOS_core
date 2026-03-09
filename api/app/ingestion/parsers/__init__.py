from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.ingestion.parsers.base import ParseResult


@runtime_checkable
class CsvParserProtocol(Protocol):
    def __call__(self, file_path: str, delimiter: str) -> ParseResult: ...


@runtime_checkable
class ExcelParserProtocol(Protocol):
    def __call__(self, file_path: str) -> ParseResult: ...


__all__ = [
    "ParseResult",
    "CsvParserProtocol",
    "ExcelParserProtocol",
]
