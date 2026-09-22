# 01.project_old-map-creator
**Idea & what it does:** 

Old Map Creator is an interactive Python command-line tool that converts place names or addresses into an Excel workbook. It resolves locations with OpenStreetMap's Nominatim service through `geopy` and saves each result as a recoverable `.xls` checkpoint.

## Requirements

- Python 3.10 or newer
- Network access for geocoding

Install the dependencies in a virtual environment:

```shell
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run

From the project root:

```shell
python src/main.py
```

The program asks for the output workbook before it asks for any places. Only `.xls` is currently supported. When the filename has no extension, `.xls` is appended automatically. If the destination already exists, it is replaced only after explicit confirmation.

For every resolved location, the workbook contains these columns:

| Address | Latitude | Longitude |
| --- | ---: | ---: |
| Resolved display address | Numeric latitude | Numeric longitude |

Latitude and longitude are stored as separate numeric cells.

## Interactive flow

Enter a place name or address at `Enter a place (or 'finish'):`. After a successful lookup, choose whether to add another location. Type `finish` at the place prompt to save and exit; finishing before a successful lookup creates a valid header-only workbook.

If no match is found, the available actions are:

- `r` — retry the same address
- `c` — enter a corrected address
- `s` — skip it and continue
- `f` — finish and save

If the geocoding service times out, is unavailable, or rejects a request, the available actions are retry, skip, or finish. A service failure is reported separately from an address with no match.

## Saving and recovery

Every successfully resolved location is checkpointed before the next prompt. Checkpoints are first written beside the destination and then atomically published, so a failed update leaves the previous workbook recoverable. Normal completion performs a final save and reports the output path and saved row count.

Pressing `Ctrl-C` after a successful checkpoint exits without deleting the saved workbook and reports its path. Interrupting before the first successful location reports that no location rows were saved.

## Tests

Run the offline unit suite from the project root:

```shell
python -m unittest discover -s tests -v
```

The tests use fake geocoding responses and do not contact Nominatim.
