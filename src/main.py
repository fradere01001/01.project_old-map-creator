"""Import-safe public entry point for Old Map Creator."""

from __future__ import annotations

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cli import build_parser, main
from src.dialogs import select_existing_workbook, select_input_path, select_output_path
from src.exporters import (
    CheckpointError,
    WorkbookOutput,
    normalize_output_path,
    validate_output_destination,
)
from src.geocoding import GeocodeOutcome, GeocodeStatus, geocode_address
from src.manual import run_session

__all__ = [
    "CheckpointError",
    "GeocodeOutcome",
    "GeocodeStatus",
    "WorkbookOutput",
    "build_parser",
    "geocode_address",
    "main",
    "normalize_output_path",
    "run_session",
    "select_output_path",
    "select_input_path",
    "select_existing_workbook",
    "validate_output_destination",
]


if __name__ == "__main__":
    raise SystemExit(main())
