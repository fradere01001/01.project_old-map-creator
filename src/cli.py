"""Command-line and interactive workflow composition."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Sequence

from .batch import build_batch_plan, confirm_plan, format_plan, process_batch
from .cache import GeocodeCache
from .dialogs import select_input_path, select_output_path
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
    parser.add_argument("--output", help="destination file")
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
        with GeocodeCache(cache_path) as cache:
            profile = ProviderProfile(provider_id=plan.provider_id)
            geocoder = BatchGeocoder(geocoder_factory(profile), profile)
            process_batch(
                plan,
                geocoder,
                cache,
                job,
                get_exporter(plan.output_path, plan.output_format),
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
                (args.output, args.format, args.sheet, args.address_column, args.yes, args.overwrite)
            )
            if forbidden:
                raise ValueError("--resume cannot be combined with planning or output options.")
            return _run_resume(args.resume, cache_path, geocoder_factory, output_fn)

        mode = "manual" if args.manual else "batch" if args.batch else None
        if mode is None:
            if noninteractive:
                raise ValueError("Choose --manual, --batch, or --resume.")
            mode = _choose_mode(input_fn, output_fn)

        if noninteractive and args.output is None:
            raise ValueError("Non-interactive workflows require --output.")
        chooser_fn = chooser if chooser is not None else None
        selection_kwargs = {
            "input_fn": input_fn,
            "output_fn": output_fn,
            "cli_output": args.output,
            "explicit_format": args.format,
            "overwrite": args.overwrite,
            "use_gui": not noninteractive,
        }
        if chooser_fn is not None:
            selection_kwargs["chooser"] = chooser_fn
        selected = select_output_path(**selection_kwargs)  # type: ignore[arg-type]
        if selected is None:
            output_fn("Cancelled; no output was created.")
            return 0
        destination, output_format = selected

        if mode == "manual":
            if any((args.batch, args.sheet, args.address_column, args.yes)):
                raise ValueError("Batch-only options cannot be used with --manual.")
            geocoder = geocoder_factory(ProviderProfile())
            return 0 if run_session(
                geocoder, WorkbookOutput(destination), input_fn, output_fn
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
        interactive = not noninteractive
        worksheet = _choose_sheet(source_path, args.sheet, interactive, input_fn)
        data = load_source(source_path, worksheet)
        column = _resolve_column(data, args.address_column, interactive, input_fn)

        with GeocodeCache(cache_path) as cache:
            while True:
                plan = build_batch_plan(
                    data, column, destination, output_format, cache
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
                profile = ProviderProfile(provider_id=plan.provider_id)
                geocoder = BatchGeocoder(geocoder_factory(profile), profile)
                try:
                    process_batch(
                        plan,
                        geocoder,
                        cache,
                        job,
                        get_exporter(destination, output_format),
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
    except (ValueError, ImportSourceError, JobStateError) as error:
        output_fn(f"Error: {error}")
        return 2
    except (CheckpointError, OSError, RuntimeError) as error:
        output_fn(f"Failure: {error}")
        return 1
