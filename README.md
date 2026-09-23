# Old Map Creator

Old Map Creator geocodes place names and addresses with OpenStreetMap's public Nominatim service. It supports interactive entry and confirmed batch imports, writes recoverable checkpoints, and exports XLSX, CSV, GeoJSON, or KML.

## Install

Python 3.10 or newer and network access are required for live geocoding.

```shell
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Interactive use

```shell
python -m src.main
```

Choose manual entry or batch import, then choose whether to create a new output or extend an existing XLSX workbook. New output opens the Save dialog; extension opens an XLSX file picker and previews the table that will receive locations. Cancellation occurs before geocoding or file changes. Batch mode then opens a file picker for its separate CSV, TXT, or XLSX source. On a headless system, the program falls back to explicit terminal path prompts.

Manual mode checkpoints every resolved place and immediately returns to the address prompt; type `finish` there when done. A lookup with no match can be retried, corrected, skipped, or used to finish. Service failures are reported separately and can be retried, skipped, or used to finish.

## Batch imports

Inputs may be:

- UTF-8 or UTF-8-BOM CSV, with detected delimiters and a header row
- UTF-8 TXT, with one address per physical line
- XLSX, with explicit worksheet selection when multiple sheets exist

The program suggests a uniquely recognized `address`, `location`, `place`, or `indirizzo` column. Otherwise it requires an explicit mapping. Before any request it shows the source, mapping, destination, row/blank/duplicate/unique/cache counts, a five-row preview, and a public-provider warning. You may proceed, change the mapping, or cancel.

Equivalent addresses are normalized for Unicode width, whitespace, and case and geocoded once per job. Successful lookups and no-matches are cached between jobs; transient service failures are not.

Public Nominatim requests use one worker, a descriptive user agent, finite retries, and at least one second between uncached request starts. For larger or production workloads, use a provider whose usage policy fits that workload.

## Outputs and reports

- XLSX contains `Locations` and a complete, source-ordered `Import Report` worksheet.
- CSV is a self-reporting row-level import report.
- GeoJSON contains resolved Point features in longitude/latitude order plus `<name>-report.csv`.
- KML contains resolved Placemarks in longitude/latitude order plus `<name>-report.csv`.

Every row is classified as `resolved`, `blank`, `no_match`, or `service_failure`, with cache and duplicate provenance reported separately. Files are written beside the destination and atomically replaced so a failed checkpoint preserves the prior file.

Location-bearing outputs are duplicate-free: `Locations`, GeoJSON features, and KML placemarks contain the first occurrence of each normalized resolved address. `Import Report`, CSV, and companion reports retain every source row, including duplicates.

## Extending an existing XLSX

Manual and batch workflows can add locations to any readable `.xlsx` workbook. If one unambiguous table has `Address`, `Latitude`, and `Longitude` headers, new unique locations are appended there. Otherwise the program preserves existing sheets and creates a non-conflicting standard location sheet. Common cell values, formulas, styles, dimensions, and sheet order are preserved; advanced Excel features unsupported by `openpyxl`, encrypted files, `.xls`, and `.xlsm` are outside this mode's preservation guarantee.

Existing and new locations share the same duplicate boundary. If a manual or batch result already exists, no second location row is added; batch report rows are still retained. An external edit during a session or before resume causes a safe stop instead of an overwrite. A batch source must be a different file from the workbook being extended.

Legacy `.xls` output has been fully replaced. Use `.xlsx`; existing `.xls` files are not valid batch inputs and should be converted with a spreadsheet application first.

## Command line

Batch execution is non-interactive and requires an output plus `--yes` confirmation:

```shell
python -m src.main --batch addresses.csv --address-column Address --output map.xlsx --yes
python -m src.main --batch addresses.xlsx --sheet Places --address-column Location --output map.geojson --format geojson --yes
```

An existing destination is protected independently from plan confirmation:

```shell
python -m src.main --batch addresses.txt --output map.csv --yes --overwrite
```

Manual mode can also bypass the Save dialog:

```shell
python -m src.main --manual --output map.xlsx
python -m src.main --manual --extend-existing map.xlsx
python -m src.main --batch new-addresses.csv --address-column Address --extend-existing map.xlsx --yes
```

Interrupted batch state is stored beside the output as `.<output-name>.oldmap-job.sqlite3`. Resume with either the output path or the state path:

```shell
python -m src.main --resume map.xlsx
python -m src.main --resume .map.xlsx.oldmap-job.sqlite3
```

Resume validates the source fingerprint and saved immutable plan, rebuilds primary and companion outputs from committed rows, and does not repeat completed requests. Completed state is retained for audit but is no longer resumable. The application-wide geocode cache is stored in the operating system's standard user cache directory under `old-map-creator`.

Run `python -m src.main --help` for all options. Exit status is `0` for completion/cancellation, `2` for argument or plan errors, and `1` for interruption or runtime/publication failure.

## Tests

The suite is offline and never contacts Nominatim:

```shell
python -m unittest discover -s tests -v
openspec validate add-batch-import-and-export --strict
```
