"""Batch planning, confirmation, processing, and progress reporting."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .cache import GeocodeCache
from .exporters import Exporter
from .geocoding import BatchGeocoder
from .jobs import JobState
from .models import (
    BatchPlan,
    GeocodeResult,
    ImportedData,
    ImportRecord,
    Outcome,
    ProgressSummary,
    RowOutcome,
)


def build_records(data: ImportedData, address_column: str) -> tuple[ImportRecord, ...]:
    return tuple(
        ImportRecord(
            row.source_row,
            "" if row.values.get(address_column) is None else str(row.values.get(address_column)),
            dict(row.values),
        )
        for row in data.rows
    )


def build_batch_plan(
    data: ImportedData,
    address_column: str,
    output_path: Path,
    output_format: str,
    cache: GeocodeCache,
    provider_id: str = "nominatim-public",
    provider_options: dict[str, object] | None = None,
) -> BatchPlan:
    records = build_records(data, address_column)
    options = provider_options or {}
    seen: set[str] = set()
    duplicate_count = 0
    cached_count = 0
    unique_count = 0
    for record in records:
        normalized = record.normalized_address
        if not normalized:
            continue
        if normalized in seen:
            duplicate_count += 1
            continue
        seen.add(normalized)
        unique_count += 1
        if cache.get(record.original_address, provider_id, options) is not None:
            cached_count += 1
    return BatchPlan(
        source_path=data.source_path,
        source_hash=data.source_hash,
        output_path=output_path,
        output_format=output_format,
        records=records,
        worksheet=data.worksheet,
        address_column=address_column,
        provider_id=provider_id,
        provider_options=dict(options),
        blank_count=sum(not item.normalized_address for item in records),
        duplicate_count=duplicate_count,
        unique_query_count=unique_count,
        cached_query_count=cached_count,
        preview=tuple(item.original_address for item in records[:5]),
    )


def format_plan(plan: BatchPlan) -> str:
    preview = "\n".join(
        f"  {index}. {value or '[blank]'}"
        for index, value in enumerate(plan.preview, start=1)
    ) or "  (no data rows)"
    return (
        f"Batch preview\nSource: {plan.source_path}\n"
        f"Worksheet: {plan.worksheet or '(not applicable)'}\n"
        f"Address column: {plan.address_column}\nRows: {len(plan.records)}; "
        f"blank: {plan.blank_count}; duplicates: {plan.duplicate_count}; "
        f"unique queries: {plan.unique_query_count}; cached: {plan.cached_query_count}\n"
        f"Output: {plan.output_path} ({plan.output_format})\n"
        "Provider: public Nominatim; uncached requests are serialized at >=1 second.\n"
        f"First rows:\n{preview}"
    )


def confirm_plan(
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> str:
    while True:
        answer = input_fn("Proceed, change mapping, or cancel? [p/m/c]: ").strip().lower()
        if answer in {"p", "proceed"}:
            return "proceed"
        if answer in {"m", "mapping", "change"}:
            return "mapping"
        if answer in {"c", "cancel"}:
            return "cancel"
        output_fn("Choose proceed, mapping, or cancel.")


def progress_text(summary: ProgressSummary) -> str:
    return (
        f"Progress {summary.completed}/{summary.total}: resolved={summary.resolved}, "
        f"blank={summary.blank}, no_match={summary.no_match}, "
        f"service_failure={summary.service_failure}, cache_hits={summary.cache_hits}, "
        f"duplicate_reuses={summary.duplicate_reuses}"
    )


def process_batch(
    plan: BatchPlan,
    geocoder: BatchGeocoder,
    cache: GeocodeCache,
    job: JobState,
    exporter: Exporter,
    output_fn: Callable[[str], None] = print,
) -> ProgressSummary:
    completed = {item.source_row: item for item in job.outcomes()}
    representatives: dict[str, int] = {}
    for record in plan.records:
        normalized = record.normalized_address
        if normalized and normalized not in representatives:
            representatives[normalized] = record.source_row

    for record in plan.records:
        if record.source_row in completed:
            continue
        normalized = record.normalized_address
        if not normalized:
            row_outcome = RowOutcome.from_result(
                record, GeocodeResult(Outcome.BLANK)
            )
        else:
            representative = representatives[normalized]
            if representative != record.source_row:
                original = completed.get(representative)
                if original is None:
                    raise RuntimeError("Duplicate representative has not been processed.")
                row_outcome = RowOutcome(
                    record.source_row,
                    record.original_address,
                    original.outcome,
                    original.resolved_address,
                    original.latitude,
                    original.longitude,
                    original.error,
                    False,
                    duplicate_of=representative,
                )
            else:
                result = cache.get(
                    record.original_address, plan.provider_id, plan.provider_options
                )
                if result is None:
                    result = geocoder.resolve(record.original_address)
                    cache.put(
                        record.original_address,
                        plan.provider_id,
                        plan.provider_options,
                        result,
                    )
                row_outcome = RowOutcome.from_result(record, result)
        job.record(row_outcome)
        completed[record.source_row] = row_outcome
        ordered = [completed[key] for key in sorted(completed)]
        exporter.publish(ordered)
        output_fn(progress_text(ProgressSummary.from_outcomes(len(plan.records), ordered)))

    ordered = [completed[key] for key in sorted(completed)]
    exporter.publish(ordered)
    summary = ProgressSummary.from_outcomes(len(plan.records), ordered)
    job.mark_complete()
    output_fn("Complete. " + progress_text(summary))
    return summary
