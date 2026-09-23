"""Command-line and interactive workflow composition."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Sequence

from .batch import build_batch_plan, confirm_plan, format_plan, process_batch
from .cache import GeocodeCache
from .dialogs import select_existing_workbook, select_input_path, select_output_path
from .exporters import CheckpointError, WorkbookOutput, get_exporter
from .geocoding import BatchGeocoder, ProviderProfile, make_default_geocoder
from .importers import (
    ImportSourceError,
    list_xlsx_worksheets,
    load_source,
    resolve_address_column,
)
from .jobs import JobState, JobStateError, job_state_path
from .manual import run_session
from .models import DestinationMode, DestinationPlan, WorkbookLayout
from .workbooks import (
    WorkbookInspectionError,
    extension_preview,
    file_fingerprint,
    inspect_existing_workbook,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="old-map-creator",
        description="Geocode addresses manually or from CSV, TXT, and XLSX files.",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--manual", action="store_true", help="collect addresses interactively")
    modes.add_argument("--batch", metavar="FILE", help="import CSV, TXT, or XLSX addresses")
    modes.add_argument("--resume", metavar="STATE_OR_OUTPUT", help="resume an interrupted batch job")
    parser.add_argument("--sheet", help="XLSX worksheet name")
    parser.add_argument("--address-column", help="column containing addresses")
    destinations = parser.add_mutually_exclusive_group()
    destinations.add_argument("--output", help="new destination file")
    destinations.add_argument(
        "--extend-existing", metavar="WORKBOOK", help="existing XLSX workbook to extend"
    )
    parser.add_argument(
        "--format", choices=("xlsx", "csv", "geojson", "kml"), help="output format"
    )
    parser.add_argument("--yes", action="store_true", help="accept the batch preview")
    parser.add_argument(
        "--overwrite", action="store_true", help="allow replacement of an existing output"
    )
    return parser


def _choose_mode(input_fn: Callable[[str], str], output_fn: Callable[[str], None]) -> str:
    while True:
        answer = input_fn("Manual entry or batch import? [m/b]: ").strip().lower()
        if answer in {"m", "manual"}:
            return "manual"
        if answer in {"b", "batch"}:
            return "batch"
        output_fn("Choose manual or batch.")


def _choose_destination_mode(
    input_fn: Callable[[str], str], output_fn: Callable[[str], None]
) -> DestinationMode:
    while True:
        answer = input_fn("Create a new output or extend an existing XLSX? [n/e]: ").strip().lower()
        if answer in {"n", "new", "create"}:
            return DestinationMode.NEW
        if answer in {"e", "extend", "existing"}:
            return DestinationMode.EXTEND
        output_fn("Choose new or extend.")


def _confirm_layout(
    input_fn: Callable[[str], str], output_fn: Callable[[str], None]
) -> bool:
    while True:
        answer = input_fn("Use this workbook layout? [y/n]: ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        output_fn("Please answer yes or no.")


def _choose_sheet(
    path: str,
    requested: str | None,
    interactive: bool,
    input_fn: Callable[[str], str],
) -> str | None:
    if Path(path).suffix.lower() != ".xlsx" or requested is not None:
        return requested
    sheets = list_xlsx_worksheets(path)
    if len(sheets) <= 1:
        return sheets[0] if sheets else None
    if not interactive:
        raise ImportSourceError(
            "XLSX has multiple worksheets; provide --sheet. Available: "
            + ", ".join(sheets)
        )
    answer = input_fn("Worksheet (" + ", ".join(sheets) + "): ").strip()
    if answer not in sheets:
        raise ImportSourceError(f"Worksheet '{answer}' not found.")
    return answer


def _resolve_column(
    data: object,
    requested: str | None,
    interactive: bool,
    input_fn: Callable[[str], str],
) -> str:
    try:
        return resolve_address_column(data, requested)  # type: ignore[arg-type]
    except ImportSourceError:
        if not interactive or requested is not None:
            raise
        headers = getattr(data, "headers")
        answer = input_fn("Address column (" + ", ".join(headers) + "): ").strip()
        return resolve_address_column(data, answer)  # type: ignore[arg-type]


def _resume_state_path(raw: str) -> Path:
    candidate = Path(raw).expanduser().resolve()
    if candidate.name.endswith(".oldmap-job.sqlite3"):
        return candidate
    return job_state_path(candidate)


def _run_resume(
    raw: str,
    cache_path: str | Path | None,
    geocoder_factory: Callable[[ProviderProfile], object],
    output_fn: Callable[[str], None],
) -> int:
    state_path = _resume_state_path(raw)
    if not state_path.is_file():
        raise JobStateError(f"Resume state not found: {state_path}")
    with JobState(state_path) as job:
        if not job.is_resumable:
            raise JobStateError("The selected job is complete and is not resumable.")
        plan = job.load_plan()
        current = load_source(plan.source_path, plan.worksheet)
        if current.source_hash != plan.source_hash:
            raise JobStateError("Source file changed since this job was created.")
        layout = WorkbookLayout(**plan.workbook_layout) if plan.workbook_layout else None
        destination_plan = DestinationPlan(
            DestinationMode(plan.destination_mode),
            plan.output_path,
            plan.output_format,
            layout,
            plan.base_fingerprint,
            plan.existing_location_identities,
        )
        expected = job.expected_fingerprint or plan.base_fingerprint
        if destination_plan.mode is DestinationMode.EXTEND:
            if expected is None or file_fingerprint(plan.output_path) != expected:
                raise JobStateError(
                    "Existing workbook changed since the last checkpoint; refusing to resume."
                )
        with GeocodeCache(cache_path) as cache:
            profile = ProviderProfile(provider_id=plan.provider_id)
            geocoder = BatchGeocoder(geocoder_factory(profile), profile)
            process_batch(
                plan,
                geocoder,
                cache,
                job,
                get_exporter(
                    plan.output_path, plan.output_format, destination_plan, expected
                ),
                output_fn,
            )
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    chooser: Callable[[], str | None] | None = None,
    input_chooser: Callable[[], str | None] | None = None,
    existing_chooser: Callable[[], str | None] | None = None,
    cache_path: str | Path | None = None,
    geocoder_factory: Callable[[ProviderProfile], object] = make_default_geocoder,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    supplied_argv = list(argv) if argv is not None else list(sys.argv[1:])
    noninteractive = bool(supplied_argv)

    try:
        if args.resume:
            forbidden = any(
                (args.output, args.extend_existing, args.format, args.sheet, args.address_column, args.yes, args.overwrite)
            )
            if forbidden:
                raise ValueError("--resume cannot be combined with planning or output options.")
            return _run_resume(args.resume, cache_path, geocoder_factory, output_fn)

        mode = "manual" if args.manual else "batch" if args.batch else None
        if mode is None:
            if noninteractive:
                raise ValueError("Choose --manual, --batch, or --resume.")
            mode = _choose_mode(input_fn, output_fn)

        if args.extend_existing and (args.format or args.overwrite):
            raise ValueError("--extend-existing cannot be combined with --format or --overwrite.")
        if noninteractive and args.output is None and args.extend_existing is None:
            raise ValueError("Non-interactive workflows require --output or --extend-existing.")

        destination_mode = (
            DestinationMode.EXTEND if args.extend_existing else
            DestinationMode.NEW if args.output else
            _choose_destination_mode(input_fn, output_fn)
        )
        if destination_mode is DestinationMode.EXTEND:
            existing_kwargs = {
                "input_fn": input_fn,
                "output_fn": output_fn,
                "cli_path": args.extend_existing,
                "use_gui": not noninteractive,
            }
            if existing_chooser is not None:
                existing_kwargs["chooser"] = existing_chooser
            existing_path = select_existing_workbook(**existing_kwargs)  # type: ignore[arg-type]
            if existing_path is None:
                output_fn("Cancelled; the existing workbook was not changed.")
                return 0
            destination_plan = inspect_existing_workbook(existing_path)
            destination, output_format = destination_plan.path, "xlsx"
            if not noninteractive:
                output_fn(extension_preview(destination_plan))
                if mode == "manual" and not _confirm_layout(input_fn, output_fn):
                    output_fn("Cancelled; the existing workbook was not changed.")
                    return 0
        else:
            selection_kwargs = {
                "input_fn": input_fn,
                "output_fn": output_fn,
                "cli_output": args.output,
                "explicit_format": args.format,
                "overwrite": args.overwrite,
                "use_gui": not noninteractive,
            }
            if chooser is not None:
                selection_kwargs["chooser"] = chooser
            selected = select_output_path(**selection_kwargs)  # type: ignore[arg-type]
            if selected is None:
                output_fn("Cancelled; no output was created.")
                return 0
            destination, output_format = selected
            destination_plan = DestinationPlan(
                DestinationMode.NEW, destination, output_format
            )

        if mode == "manual":
            if any((args.batch, args.sheet, args.address_column, args.yes)):
                raise ValueError("Batch-only options cannot be used with --manual.")
            geocoder = geocoder_factory(ProviderProfile())
            return 0 if run_session(
                geocoder,
                WorkbookOutput(destination, destination_plan=destination_plan),
                input_fn,
                output_fn,
            ) else 1

        if args.batch:
            source_path = str(select_input_path(cli_input=args.batch, use_gui=False))
        else:
            input_selection_kwargs = {
                "input_fn": input_fn,
                "output_fn": output_fn,
                "use_gui": True,
            }
            if input_chooser is not None:
                input_selection_kwargs["chooser"] = input_chooser
            input_path = select_input_path(**input_selection_kwargs)  # type: ignore[arg-type]
            if input_path is None:
                output_fn("Cancelled; no input was processed and no output was created.")
                return 0
            source_path = str(input_path)
        if destination_mode is DestinationMode.EXTEND and Path(source_path).resolve() == destination.resolve():
            raise ValueError(
                "The batch source and extended workbook must be different files."
            )
        interactive = not noninteractive
        worksheet = _choose_sheet(source_path, args.sheet, interactive, input_fn)
        data = load_source(source_path, worksheet)
        column = _resolve_column(data, args.address_column, interactive, input_fn)

        with GeocodeCache(cache_path) as cache:
            while True:
                plan = build_batch_plan(
                    data, column, destination, output_format, cache,
                    destination_plan=destination_plan,
                )
                output_fn(format_plan(plan))
                if noninteractive:
                    if not args.yes:
                        raise ValueError("Batch execution requires --yes after reviewing the plan.")
                    action = "proceed"
                else:
                    action = confirm_plan(input_fn, output_fn)
                if action == "cancel":
                    output_fn("Cancelled; no network requests or output writes were made.")
                    return 0
                if action == "mapping":
                    column = _resolve_column(data, input_fn("Address column: ").strip(), True, input_fn)
                    continue
                break

            state_path = job_state_path(destination)
            with JobState(state_path) as job:
                job.initialize(plan)
                job.set_expected_fingerprint(destination_plan.base_fingerprint)
                profile = ProviderProfile(provider_id=plan.provider_id)
                geocoder = BatchGeocoder(geocoder_factory(profile), profile)
                try:
                    process_batch(
                        plan,
                        geocoder,
                        cache,
                        job,
                        get_exporter(
                            destination,
                            output_format,
                            destination_plan,
                            job.expected_fingerprint,
                        ),
                        output_fn,
                    )
                except (KeyboardInterrupt, CheckpointError, OSError, RuntimeError) as error:
                    completed = len(job.outcomes())
                    output_fn(
                        f"Stopped after {completed}/{len(plan.records)} row(s): {error}. "
                        f"Resume with: python -m src.main --resume {state_path}"
                    )
                    return 1
        return 0
    except KeyboardInterrupt:
        output_fn("Interrupted. Resume the batch with --resume and its state path.")
        return 1
    except (ValueError, ImportSourceError, JobStateError, WorkbookInspectionError) as error:
        output_fn(f"Error: {error}")
        return 2
    except (CheckpointError, OSError, RuntimeError) as error:
        output_fn(f"Failure: {error}")
        return 1
