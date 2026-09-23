"""Versioned resumable job state stored beside each destination."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import BatchPlan, Outcome, RowOutcome


SCHEMA_VERSION = 2


class JobStateError(ValueError):
    pass


def job_state_path(output_path: Path) -> Path:
    return output_path.with_name(f".{output_path.name}.oldmap-job.sqlite3")


def discover_resumable_jobs(directory: str | Path) -> list[Path]:
    """Return incomplete, readable job sidecars in deterministic order."""
    results: list[Path] = []
    for candidate in sorted(Path(directory).glob(".*.oldmap-job.sqlite3")):
        try:
            with JobState(candidate) as job:
                if job.is_resumable:
                    results.append(candidate)
        except (sqlite3.DatabaseError, JobStateError):
            continue
    return results


class JobState:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS outcomes (
                source_row INTEGER PRIMARY KEY,
                payload TEXT NOT NULL
            )"""
        )
        self.connection.commit()

    def _set(self, key: str, value: object) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False, sort_keys=True)),
        )

    def _get(self, key: str) -> object | None:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key = ?", (key,)
        ).fetchone()
        return None if row is None else json.loads(row[0])

    def initialize(self, plan: BatchPlan) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM metadata")
            self.connection.execute("DELETE FROM outcomes")
            self._set("schema_version", SCHEMA_VERSION)
            self._set("plan", plan.to_dict())
            self._set("complete", False)

    def load_plan(self) -> BatchPlan:
        version = self._get("schema_version")
        if version is None:
            raise JobStateError("Job state has not been initialized.")
        if version != SCHEMA_VERSION:
            raise JobStateError(
                f"Unsupported job-state version: {version}; restart this batch "
                "to migrate it to the current resumable format."
            )
        payload = self._get("plan")
        if not isinstance(payload, dict):
            raise JobStateError("Job state does not contain a valid plan.")
        return BatchPlan.from_dict(payload)

    def validate_plan(self, plan: BatchPlan) -> None:
        existing = self.load_plan().compatibility_fields()
        proposed = plan.compatibility_fields()
        mismatches = [key for key in existing if existing[key] != proposed[key]]
        if mismatches:
            raise JobStateError(
                "Resume plan is incompatible: " + ", ".join(mismatches)
            )

    def record(self, outcome: RowOutcome) -> None:
        payload = {
            "source_row": outcome.source_row,
            "input_address": outcome.input_address,
            "outcome": outcome.outcome.value,
            "resolved_address": outcome.resolved_address,
            "latitude": outcome.latitude,
            "longitude": outcome.longitude,
            "error": outcome.error,
            "cache_hit": outcome.cache_hit,
            "duplicate_of": outcome.duplicate_of,
        }
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO outcomes(source_row, payload) VALUES (?, ?)",
                (outcome.source_row, json.dumps(payload, ensure_ascii=False)),
            )

    def outcomes(self) -> list[RowOutcome]:
        rows = self.connection.execute(
            "SELECT payload FROM outcomes ORDER BY source_row"
        ).fetchall()
        results = []
        for (payload,) in rows:
            data = json.loads(payload)
            data["outcome"] = Outcome(data["outcome"])
            results.append(RowOutcome(**data))
        return results

    def mark_complete(self) -> None:
        with self.connection:
            self._set("complete", True)

    def set_expected_fingerprint(self, fingerprint: str | None) -> None:
        with self.connection:
            self._set("expected_workbook_fingerprint", fingerprint)

    @property
    def expected_fingerprint(self) -> str | None:
        value = self._get("expected_workbook_fingerprint")
        return value if isinstance(value, str) else None

    @property
    def is_complete(self) -> bool:
        return self._get("complete") is True

    @property
    def is_resumable(self) -> bool:
        return self._get("plan") is not None and not self.is_complete

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "JobState":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
