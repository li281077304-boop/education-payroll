from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Generic, Mapping, TypeVar


class CellValueState(StrEnum):
    RAW_VALUE = "RAW_VALUE"
    FORMULA = "FORMULA"
    CACHED_VALUE = "CACHED_VALUE"
    MISSING_CACHE = "MISSING_CACHE"
    EXTERNAL_REFERENCE = "EXTERNAL_REFERENCE"


@dataclass(frozen=True)
class SourceEvidence:
    source_file: str
    sheet: str
    coordinate: str
    source_field: str
    raw_value: Any
    normalized_value: Any
    state: CellValueState


@dataclass(frozen=True)
class CommentRecord:
    source_file: str
    sheet: str
    coordinate: str
    target: str
    field: str
    text: str
    author: str | None = None


@dataclass(frozen=True)
class AdapterIssue:
    code: str
    message: str
    sheet: str = ""
    field: str = ""


T = TypeVar("T")


@dataclass
class AdapterResult(Generic[T]):
    records: list[T] = field(default_factory=list)
    warnings: list[AdapterIssue] = field(default_factory=list)
    errors: list[AdapterIssue] = field(default_factory=list)
    # Adapters may expose small, non-sensitive evidence metadata here (for
    # example all source dates before period filtering).  Keep the result
    # generic because some adapters also report counts and ranges.
    coverage: Mapping[str, Any] = field(default_factory=dict)
    unsupported_fields: tuple[str, ...] = ()
    comments: list[CommentRecord] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors
