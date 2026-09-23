"""Atomic XLSX, CSV, GeoJSON, and KML exporters."""

from __future__ import annotations

import csv
import json
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Protocol, Sequence

from openpyxl import Workbook

from .models import Outcome, RowOutcome


SUPPORTED_FORMATS = {"xlsx", "csv", "geojson", "kml"}


class CheckpointError(RuntimeError):
    pass


def normalize_output_path(
    raw_path: str, explicit_format: str | None = None
) -> tuple[Path, str]:
    cleaned = raw_path.strip()
    if not cleaned:
        raise ValueError("The output filename cannot be empty.")
    path = Path(cleaned).expanduser()
    if path.suffix.lower() == ".xls":
        raise ValueError("Legacy .xls output is no longer supported; use .xlsx.")
    selected_format = explicit_format.lower() if explicit_format else None
    if selected_format and selected_format not in SUPPORTED_FORMATS:
        raise ValueError("Supported output formats: xlsx, csv, geojson, kml.")
    if not path.suffix:
        selected_format = selected_format or "xlsx"
        path = path.with_suffix(f".{selected_format}")
    extension = path.suffix.lower().lstrip(".")
    if extension not in SUPPORTED_FORMATS:
        raise ValueError("Supported output formats: .xlsx, .csv, .geojson, .kml.")
    if selected_format and selected_format != extension:
        raise ValueError(
            f"Output format '{selected_format}' conflicts with '.{extension}'."
        )
    return path.resolve(), extension


def validate_output_destination(destination: Path) -> None:
    parent = destination.parent
    if not parent.exists() or not parent.is_dir():
        raise ValueError(f"Output directory does not exist: {parent}")
    if destination.exists() and not destination.is_file():
        raise ValueError(f"Output destination is not a regular file: {destination}")
    probe_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=parent,
            prefix=f".{destination.name}.",
            suffix=".probe",
            delete=False,
        ) as probe:
            probe_name = probe.name
    except OSError as error:
        raise ValueError(f"Output directory is not writable: {parent}") from error
    finally:
        if probe_name:
            try:
                Path(probe_name).unlink()
            except FileNotFoundError:
                pass


def atomic_publish(destination: Path, writer: Callable[[Path], None]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        writer(temporary_path)
        os.replace(temporary_path, destination)
        temporary_path = None
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as error:
        raise CheckpointError(f"Could not publish output: {error}") from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


REPORT_HEADERS = (
    "Source Row",
    "Input Address",
    "Status",
    "Cache Hit",
    "Duplicate Of",
    "Resolved Address",
    "Latitude",
    "Longitude",
    "Error",
)


def report_values(item: RowOutcome) -> tuple[object, ...]:
    return (
        item.source_row,
        item.input_address,
        item.outcome.value,
        item.cache_hit,
        item.duplicate_of if item.duplicate_of is not None else "",
        item.resolved_address or "",
        item.latitude if item.latitude is not None else "",
        item.longitude if item.longitude is not None else "",
        item.error or "",
    )


class Exporter(Protocol):
    destination: Path

    def publish(self, outcomes: Sequence[RowOutcome]) -> None: ...


class XlsxExporter:
    def __init__(self, destination: Path):
        self.destination = destination

    def publish(self, outcomes: Sequence[RowOutcome]) -> None:
        def write(path: Path) -> None:
            workbook = Workbook()
            locations = workbook.active
            locations.title = "Locations"
            locations.append(("Address", "Latitude", "Longitude"))
            for item in outcomes:
                if item.outcome is Outcome.RESOLVED:
                    locations.append(
                        (item.resolved_address, item.latitude, item.longitude)
                    )
            report = workbook.create_sheet("Import Report")
            report.append(REPORT_HEADERS)
            for item in sorted(outcomes, key=lambda value: value.source_row):
                report.append(report_values(item))
            workbook.save(path)

        atomic_publish(self.destination, write)


class CsvExporter:
    def __init__(self, destination: Path):
        self.destination = destination

    def publish(self, outcomes: Sequence[RowOutcome]) -> None:
        def write(path: Path) -> None:
            with path.open("w", encoding="utf-8", newline="") as output:
                writer = csv.writer(output)
                writer.writerow(REPORT_HEADERS)
                for item in sorted(outcomes, key=lambda value: value.source_row):
                    writer.writerow(report_values(item))

        atomic_publish(self.destination, write)


def companion_report_path(destination: Path) -> Path:
    return destination.with_name(f"{destination.stem}-report.csv")


class GeoJsonExporter:
    def __init__(self, destination: Path):
        self.destination = destination
        self.report_destination = companion_report_path(destination)

    def publish(self, outcomes: Sequence[RowOutcome]) -> None:
        def write(path: Path) -> None:
            features = []
            for item in sorted(outcomes, key=lambda value: value.source_row):
                if item.outcome is not Outcome.RESOLVED:
                    continue
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [item.longitude, item.latitude],
                        },
                        "properties": {
                            "source_row": item.source_row,
                            "input_address": item.input_address,
                            "resolved_address": item.resolved_address,
                            "status": item.outcome.value,
                        },
                    }
                )
            path.write_text(
                json.dumps(
                    {"type": "FeatureCollection", "features": features},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        atomic_publish(self.destination, write)
        CsvExporter(self.report_destination).publish(outcomes)


class KmlExporter:
    NAMESPACE = "http://www.opengis.net/kml/2.2"

    def __init__(self, destination: Path):
        self.destination = destination
        self.report_destination = companion_report_path(destination)

    def publish(self, outcomes: Sequence[RowOutcome]) -> None:
        def write(path: Path) -> None:
            ET.register_namespace("", self.NAMESPACE)
            root = ET.Element(f"{{{self.NAMESPACE}}}kml")
            document = ET.SubElement(root, f"{{{self.NAMESPACE}}}Document")
            for item in sorted(outcomes, key=lambda value: value.source_row):
                if item.outcome is not Outcome.RESOLVED:
                    continue
                placemark = ET.SubElement(
                    document, f"{{{self.NAMESPACE}}}Placemark"
                )
                ET.SubElement(placemark, f"{{{self.NAMESPACE}}}name").text = (
                    item.resolved_address
                )
                description = ET.SubElement(
                    placemark, f"{{{self.NAMESPACE}}}description"
                )
                description.text = (
                    f"Source row: {item.source_row}; Input: {item.input_address}; "
                    f"Resolved: {item.resolved_address}"
                )
                point = ET.SubElement(placemark, f"{{{self.NAMESPACE}}}Point")
                ET.SubElement(point, f"{{{self.NAMESPACE}}}coordinates").text = (
                    f"{item.longitude},{item.latitude},0"
                )
            ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

        atomic_publish(self.destination, write)
        CsvExporter(self.report_destination).publish(outcomes)


def get_exporter(destination: Path, output_format: str) -> Exporter:
    if output_format == "xlsx":
        return XlsxExporter(destination)
    if output_format == "csv":
        return CsvExporter(destination)
    if output_format == "geojson":
        return GeoJsonExporter(destination)
    if output_format == "kml":
        return KmlExporter(destination)
    raise ValueError(f"Unsupported exporter: {output_format}")


class WorkbookOutput:
    """Checkpointing output used by the interactive manual workflow."""

    HEADERS = ("Address", "Latitude", "Longitude")

    def __init__(self, destination: Path, workbook_factory: Callable[[], object] | None = None):
        self.destination = destination
        self._outcomes: list[RowOutcome] = []
        self.location_count = 0
        self.saved_count = 0
        output_format = destination.suffix.lower().lstrip(".") or "xlsx"
        self.exporter = get_exporter(destination, output_format)

    def add_location(self, location: object) -> None:
        self.location_count += 1
        self._outcomes.append(
            RowOutcome(
                self.location_count,
                str(getattr(location, "address")),
                Outcome.RESOLVED,
                resolved_address=str(getattr(location, "address")),
                latitude=float(getattr(location, "latitude")),
                longitude=float(getattr(location, "longitude")),
            )
        )

    def checkpoint(self) -> None:
        self.exporter.publish(self._outcomes)
        self.saved_count = self.location_count
