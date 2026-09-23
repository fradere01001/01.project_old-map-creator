"""Persistent application-wide geocoding cache."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from platformdirs import user_cache_path

from .models import GeocodeResult, Outcome, normalize_address


def default_cache_path() -> Path:
    return user_cache_path("old-map-creator") / "geocode-cache.sqlite3"


class GeocodeCache:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else default_cache_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS geocode_cache (
                cache_key TEXT PRIMARY KEY,
                outcome TEXT NOT NULL,
                resolved_address TEXT,
                latitude REAL,
                longitude REAL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        self.connection.commit()

    @staticmethod
    def key(query: str, provider_id: str, options: dict[str, Any]) -> str:
        payload = json.dumps(
            {
                "query": normalize_address(query),
                "provider": provider_id,
                "options": options,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def get(
        self, query: str, provider_id: str, options: dict[str, Any]
    ) -> GeocodeResult | None:
        row = self.connection.execute(
            "SELECT outcome, resolved_address, latitude, longitude "
            "FROM geocode_cache WHERE cache_key = ?",
            (self.key(query, provider_id, options),),
        ).fetchone()
        if row is None:
            return None
        return GeocodeResult(
            Outcome(row[0]), row[1], row[2], row[3], cache_hit=True
        )

    def put(
        self,
        query: str,
        provider_id: str,
        options: dict[str, Any],
        result: GeocodeResult,
    ) -> None:
        if result.outcome not in {Outcome.RESOLVED, Outcome.NO_MATCH}:
            return
        with self.connection:
            self.connection.execute(
                """INSERT OR REPLACE INTO geocode_cache
                   (cache_key, outcome, resolved_address, latitude, longitude)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    self.key(query, provider_id, options),
                    result.outcome.value,
                    result.resolved_address,
                    result.latitude,
                    result.longitude,
                ),
            )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "GeocodeCache":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
