"""Shared domain records for manual and batch geocoding workflows."""

from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Outcome(str, Enum):
    RESOLVED = "resolved"
    BLANK = "blank"
    NO_MATCH = "no_match"
    SERVICE_FAILURE = "service_failure"


def normalize_address(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(normalized.split()).casefold()


def normalize_header(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return "_".join(normalized.strip().casefold().replace("-", " ").split())


@dataclass(frozen=True)
class SourceRow:
    source_row: int
    values: dict[str, Any]


@dataclass(frozen=True)
class ImportedData:
    source_path: Path
    source_hash: str
    headers: tuple[str, ...]
    rows: tuple[SourceRow, ...]
    worksheets: tuple[str, ...] = ()
    worksheet: str | None = None
    text_mode: bool = False


@dataclass(frozen=True)
class ImportRecord:
    source_row: int
    original_address: str
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_address(self) -> str:
        return normalize_address(self.original_address)


@dataclass(frozen=True)
class GeocodeResult:
    outcome: Outcome
    resolved_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    error: str | None = None
    cache_hit: bool = False


@dataclass(frozen=True)
class RowOutcome:
    source_row: int
    input_address: str
    outcome: Outcome
    resolved_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    error: str | None = None
    cache_hit: bool = False
    duplicate_of: int | None = None

    @classmethod
    def from_result(
        cls,
        record: ImportRecord,
        result: GeocodeResult,
        duplicate_of: int | None = None,
    ) -> "RowOutcome":
        return cls(
            source_row=record.source_row,
            input_address=record.original_address,
            outcome=result.outcome,
            resolved_address=result.resolved_address,
            latitude=result.latitude,
            longitude=result.longitude,
            error=result.error,
            cache_hit=result.cache_hit,
            duplicate_of=duplicate_of,
        )


@dataclass(frozen=True)
class BatchPlan:
    source_path: Path
    source_hash: str
    output_path: Path
    output_format: str
    records: tuple[ImportRecord, ...]
    worksheet: str | None
    address_column: str
    provider_id: str = "nominatim-public"
    provider_options: dict[str, Any] = field(default_factory=dict)
    blank_count: int = 0
    duplicate_count: int = 0
    unique_query_count: int = 0
    cached_query_count: int = 0
    preview: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_path"] = str(self.source_path)
        data["output_path"] = str(self.output_path)
        data["records"] = [asdict(record) for record in self.records]
        data["preview"] = list(self.preview)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BatchPlan":
        values = dict(data)
        values["source_path"] = Path(values["source_path"])
        values["output_path"] = Path(values["output_path"])
        values["records"] = tuple(ImportRecord(**item) for item in values["records"])
        values["preview"] = tuple(values.get("preview", ()))
        return cls(**values)

    def compatibility_fields(self) -> dict[str, Any]:
        return {
            "source_hash": self.source_hash,
            "output_path": str(self.output_path.resolve()),
            "output_format": self.output_format,
            "worksheet": self.worksheet,
            "address_column": self.address_column,
            "provider_id": self.provider_id,
            "provider_options": self.provider_options,
        }


@dataclass(frozen=True)
class ProgressSummary:
    total: int
    completed: int
    resolved: int
    blank: int
    no_match: int
    service_failure: int
    cache_hits: int
    duplicate_reuses: int

    @classmethod
    def from_outcomes(
        cls, total: int, outcomes: list[RowOutcome] | tuple[RowOutcome, ...]
    ) -> "ProgressSummary":
        return cls(
            total=total,
            completed=len(outcomes),
            resolved=sum(item.outcome is Outcome.RESOLVED for item in outcomes),
            blank=sum(item.outcome is Outcome.BLANK for item in outcomes),
            no_match=sum(item.outcome is Outcome.NO_MATCH for item in outcomes),
            service_failure=sum(
                item.outcome is Outcome.SERVICE_FAILURE for item in outcomes
            ),
            cache_hits=sum(item.cache_hit for item in outcomes),
            duplicate_reuses=sum(item.duplicate_of is not None for item in outcomes),
        )
