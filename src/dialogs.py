"""Injectable native and terminal destination selection."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .exporters import normalize_output_path, validate_output_destination


class DialogUnavailable(RuntimeError):
    pass


SAVE_FILE_TYPES = [
    ("Excel workbook", "*.xlsx"),
    ("CSV report", "*.csv"),
    ("GeoJSON", "*.geojson"),
    ("KML", "*.kml"),
    ("All files", "*.*"),
]

INPUT_FILE_TYPES = [
    ("Supported address files", "*.csv *.txt *.xlsx"),
    ("CSV files", "*.csv"),
    ("Text files", "*.txt"),
    ("Excel workbooks", "*.xlsx"),
]

SUPPORTED_INPUT_EXTENSIONS = {".csv", ".txt", ".xlsx"}


def native_save_dialog() -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            selected = filedialog.asksaveasfilename(
                title="Save Old Map Creator output",
                defaultextension=".xlsx",
                filetypes=SAVE_FILE_TYPES,
                confirmoverwrite=True,
            )
        finally:
            root.destroy()
    except Exception as error:
        raise DialogUnavailable(str(error)) from error
    return selected or None


def native_open_dialog() -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            selected = filedialog.askopenfilename(
                title="Choose a batch address file",
                filetypes=INPUT_FILE_TYPES,
            )
        finally:
            root.destroy()
    except Exception as error:
        raise DialogUnavailable(str(error)) from error
    return selected or None


def native_existing_workbook_dialog() -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            selected = filedialog.askopenfilename(
                title="Choose an XLSX workbook to extend",
                filetypes=[("Excel workbooks", "*.xlsx")],
            )
        finally:
            root.destroy()
    except Exception as error:
        raise DialogUnavailable(str(error)) from error
    return selected or None


def select_existing_workbook(
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    chooser: Callable[[], str | None] = native_existing_workbook_dialog,
    cli_path: str | None = None,
    use_gui: bool = True,
) -> Path | None:
    def validate(raw: str) -> Path:
        path = Path(raw.strip()).expanduser().resolve()
        if path.suffix.lower() != ".xlsx":
            raise ValueError("Only an existing .xlsx workbook can be extended.")
        if not path.is_file():
            raise ValueError(f"Existing workbook is not readable: {path}")
        return path

    if cli_path is not None:
        return validate(cli_path)
    if use_gui:
        try:
            selected = chooser()
        except DialogUnavailable as error:
            output_fn(f"Native Open dialog unavailable ({error}); using terminal input.")
        else:
            return None if selected is None else validate(selected)
    while True:
        try:
            return validate(input_fn("Full path to existing .xlsx workbook: "))
        except ValueError as error:
            output_fn(str(error))


def _validate_input_path(raw_path: str) -> Path:
    cleaned = raw_path.strip()
    candidate = Path(cleaned).expanduser()
    if candidate.suffix.lower() not in SUPPORTED_INPUT_EXTENSIONS:
        raise ValueError(
            "Choose an actual .csv, .txt, or .xlsx file path; "
            f"'{cleaned}' is not a supported input file."
        )
    resolved = candidate.resolve()
    if not resolved.is_file():
        raise ValueError(f"Input file does not exist or is not readable: {resolved}")
    return resolved


def select_input_path(
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    chooser: Callable[[], str | None] = native_open_dialog,
    cli_input: str | None = None,
    use_gui: bool = True,
) -> Path | None:
    if cli_input is not None:
        return _validate_input_path(cli_input)

    if use_gui:
        try:
            selected = chooser()
        except DialogUnavailable as error:
            output_fn(f"Native Open dialog unavailable ({error}); using terminal input.")
        else:
            if selected is None:
                return None
            return _validate_input_path(selected)

    while True:
        raw = input_fn("Full path to batch file (.csv, .txt, or .xlsx): ")
        try:
            return _validate_input_path(raw)
        except ValueError as error:
            output_fn(str(error))


def _ask_yes_no(
    prompt: str,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> bool:
    while True:
        answer = input_fn(prompt).strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        output_fn("Please answer yes or no.")


def select_output_path(
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    chooser: Callable[[], str | None] = native_save_dialog,
    cli_output: str | None = None,
    explicit_format: str | None = None,
    overwrite: bool = False,
    use_gui: bool = True,
) -> tuple[Path, str] | None:
    if cli_output is not None:
        destination, output_format = normalize_output_path(cli_output, explicit_format)
        validate_output_destination(destination)
        if destination.exists() and not overwrite:
            raise ValueError("Output already exists; pass --overwrite to replace it.")
        return destination, output_format

    if use_gui:
        try:
            selected = chooser()
        except DialogUnavailable as error:
            output_fn(f"Native Save dialog unavailable ({error}); using terminal input.")
        else:
            if selected is None:
                return None
            destination, output_format = normalize_output_path(selected, explicit_format)
            validate_output_destination(destination)
            return destination, output_format

    while True:
        raw = input_fn("Output file (.xlsx, .csv, .geojson, or .kml): ")
        try:
            destination, output_format = normalize_output_path(raw, explicit_format)
            validate_output_destination(destination)
        except ValueError as error:
            output_fn(str(error))
            continue
        if destination.exists() and not _ask_yes_no(
            f"{destination} already exists. Replace it? [y/n]: ", input_fn, output_fn
        ):
            output_fn("Existing file left unchanged. Choose another destination.")
            continue
        return destination, output_format
