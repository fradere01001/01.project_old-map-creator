"""Interactive address geocoder with recoverable XLS checkpoints."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Protocol

from geopy.exc import GeocoderServiceError
from geopy.geocoders import Nominatim
from xlwt import Workbook


InputFunction = Callable[[str], str]
OutputFunction = Callable[[str], None]


class Location(Protocol):
    address: str
    latitude: float
    longitude: float


class Geocoder(Protocol):
    def geocode(self, query: str) -> Location | None: ...


class GeocodeStatus(Enum):
    SUCCESS = "success"
    NO_MATCH = "no_match"
    SERVICE_FAILURE = "service_failure"


@dataclass(frozen=True)
class GeocodeOutcome:
    status: GeocodeStatus
    location: Location | None = None
    error: Exception | None = None


class CheckpointError(RuntimeError):
    """Raised when a workbook checkpoint cannot be published."""


def geocode_address(geocoder: Geocoder, address: str) -> GeocodeOutcome:
    """Classify a geocoding attempt without hiding programming errors."""
    try:
        location = geocoder.geocode(address)
    except GeocoderServiceError as error:
        return GeocodeOutcome(GeocodeStatus.SERVICE_FAILURE, error=error)

    if location is None:
        return GeocodeOutcome(GeocodeStatus.NO_MATCH)
    return GeocodeOutcome(GeocodeStatus.SUCCESS, location=location)


def normalize_output_path(raw_path: str) -> Path:
    """Return an absolute XLS output path or raise ``ValueError``."""
    cleaned = raw_path.strip()
    if not cleaned:
        raise ValueError("The output filename cannot be empty.")

    destination = Path(cleaned).expanduser()
    if not destination.suffix:
        destination = destination.with_suffix(".xls")
    elif destination.suffix.lower() != ".xls":
        raise ValueError("Only the .xls output format is supported.")

    return destination.resolve()


def validate_output_destination(destination: Path) -> None:
    """Check that an atomic checkpoint can be created beside destination."""
    parent = destination.parent
    if not parent.exists():
        raise ValueError(f"Output directory does not exist: {parent}")
    if not parent.is_dir():
        raise ValueError(f"Output parent is not a directory: {parent}")
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
        if probe_name is not None:
            try:
                Path(probe_name).unlink()
            except FileNotFoundError:
                pass


def _ask_yes_no(
    prompt: str,
    input_fn: InputFunction,
    output_fn: OutputFunction,
) -> bool:
    while True:
        answer = input_fn(prompt).strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        output_fn("Please answer yes or no.")


def select_output_path(
    input_fn: InputFunction = input,
    output_fn: OutputFunction = print,
) -> Path:
    """Prompt until the user selects a writable, confirmed destination."""
    while True:
        raw_path = input_fn("Output workbook (.xls): ")
        try:
            destination = normalize_output_path(raw_path)
            validate_output_destination(destination)
        except ValueError as error:
            output_fn(str(error))
            continue

        if destination.exists() and not _ask_yes_no(
            f"{destination} already exists. Replace it? [y/n]: ",
            input_fn,
            output_fn,
        ):
            output_fn("Existing file left unchanged. Choose another destination.")
            continue
        return destination


class WorkbookOutput:
    """Own workbook rows and publish them as atomic checkpoints."""

    HEADERS = ("Address", "Latitude", "Longitude")

    def __init__(self, destination: Path, workbook_factory: Callable[[], object] = Workbook):
        self.destination = destination
        self.workbook = workbook_factory()
        self.sheet = self.workbook.add_sheet("Locations")
        for column, header in enumerate(self.HEADERS):
            self.sheet.write(0, column, header)
        self.location_count = 0
        self.saved_count = 0

    def add_location(self, location: Location) -> None:
        row = self.location_count + 1
        self.sheet.write(row, 0, location.address)
        self.sheet.write(row, 1, float(location.latitude))
        self.sheet.write(row, 2, float(location.longitude))
        self.location_count += 1

    def checkpoint(self) -> None:
        """Write beside the destination, then atomically publish the file."""
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.destination.parent,
                prefix=f".{self.destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
            self.workbook.save(str(temporary_path))
            os.replace(temporary_path, self.destination)
            temporary_path = None
            self.saved_count = self.location_count
        except BaseException as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            raise CheckpointError(
                f"Could not publish workbook checkpoint: {error}"
            ) from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except FileNotFoundError:
                    pass


def _ask_choice(
    prompt: str,
    choices: dict[str, str],
    input_fn: InputFunction,
    output_fn: OutputFunction,
) -> str:
    while True:
        answer = input_fn(prompt).strip().lower()
        if answer in choices:
            return choices[answer]
        output_fn(f"Choose one of: {', '.join(choices)}.")


def _finish_session(store: WorkbookOutput, output_fn: OutputFunction) -> bool:
    try:
        store.checkpoint()
    except CheckpointError as error:
        output_fn(str(error))
        if store.saved_count:
            output_fn(
                f"The last recoverable workbook is {store.destination} "
                f"with {store.saved_count} saved location row(s)."
            )
        else:
            output_fn("No recoverable workbook was published.")
        return False

    output_fn(
        f"Saved {store.saved_count} location row(s) to {store.destination}."
    )
    return True


def _report_interruption(store: WorkbookOutput, output_fn: OutputFunction) -> None:
    if store.saved_count:
        output_fn(
            f"Interrupted. The recoverable workbook is {store.destination} "
            f"with {store.saved_count} saved location row(s)."
        )
    else:
        output_fn("Interrupted. No location rows were saved.")


def run_session(
    geocoder: Geocoder,
    store: WorkbookOutput,
    input_fn: InputFunction = input,
    output_fn: OutputFunction = print,
) -> bool:
    """Run one interactive session. Return true after a successful final save."""
    try:
        while True:
            address = input_fn("Enter a place (or 'finish'): ").strip()
            if address.lower() in {"finish", "no"}:
                return _finish_session(store, output_fn)
            if not address:
                output_fn("Enter a place or type 'finish'.")
                continue

            while True:
                outcome = geocode_address(geocoder, address)

                if outcome.status is GeocodeStatus.SUCCESS:
                    assert outcome.location is not None
                    store.add_location(outcome.location)
                    try:
                        store.checkpoint()
                    except CheckpointError as error:
                        output_fn(str(error))
                        if store.saved_count:
                            output_fn(
                                f"Collection stopped. The last recoverable workbook is "
                                f"{store.destination} with {store.saved_count} saved "
                                "location row(s)."
                            )
                        else:
                            output_fn(
                                "Collection stopped. No recoverable workbook was published."
                            )
                        return False

                    output_fn(f"Saved: {outcome.location.address}")
                    if _ask_yes_no(
                        "Add another location? [y/n]: ", input_fn, output_fn
                    ):
                        break
                    return _finish_session(store, output_fn)

                if outcome.status is GeocodeStatus.NO_MATCH:
                    output_fn(f"No match found for: {address}")
                    action = _ask_choice(
                        "Retry, correct, skip, or finish? [r/c/s/f]: ",
                        {
                            "r": "retry",
                            "retry": "retry",
                            "c": "correct",
                            "correct": "correct",
                            "s": "skip",
                            "skip": "skip",
                            "f": "finish",
                            "finish": "finish",
                        },
                        input_fn,
                        output_fn,
                    )
                    if action == "retry":
                        continue
                    if action == "correct":
                        address = input_fn("Corrected place: ").strip()
                        if not address:
                            output_fn("The corrected place cannot be empty.")
                            continue
                        continue
                    if action == "skip":
                        break
                    return _finish_session(store, output_fn)

                output_fn(f"Geocoding service failure: {outcome.error}")
                action = _ask_choice(
                    "Retry, skip, or finish? [r/s/f]: ",
                    {
                        "r": "retry",
                        "retry": "retry",
                        "s": "skip",
                        "skip": "skip",
                        "f": "finish",
                        "finish": "finish",
                    },
                    input_fn,
                    output_fn,
                )
                if action == "retry":
                    continue
                if action == "skip":
                    break
                return _finish_session(store, output_fn)
    except KeyboardInterrupt:
        _report_interruption(store, output_fn)
        return False


def main(
    input_fn: InputFunction = input,
    output_fn: OutputFunction = print,
    geocoder_factory: Callable[[], Geocoder] | None = None,
    workbook_factory: Callable[[], object] = Workbook,
) -> int:
    """Configure and run the command-line application."""
    try:
        destination = select_output_path(input_fn, output_fn)
    except KeyboardInterrupt:
        output_fn("Interrupted. No location rows were saved.")
        return 1

    if geocoder_factory is None:
        geocoder_factory = lambda: Nominatim(user_agent="old-map-creator/1.0")

    store = WorkbookOutput(destination, workbook_factory)
    completed = run_session(geocoder_factory(), store, input_fn, output_fn)
    return 0 if completed else 1


if __name__ == "__main__":
    raise SystemExit(main())
