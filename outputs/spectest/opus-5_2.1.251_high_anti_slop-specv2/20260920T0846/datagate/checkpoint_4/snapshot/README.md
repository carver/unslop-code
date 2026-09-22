# datagate

Converts remote and uploaded tables — CSV, `.xls`, `.xlsx` — into queryable
JSON datasets, and exports them back out as CSV.

## Setup

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

## Endpoints

| Route | Parameters | Result |
| --- | --- | --- |
| `GET /convert` | `source` (required URL), `charset` (optional) | `{"ok": true, "endpoint": "/datasets/<id>"}` |
| `POST /upload` | multipart field `file` or `attachment`, `charset` (optional) | `{"ok": true, "endpoint": "/datasets/<id>"}` |
| `GET /datasets/<id>` | the controls and filters below (all optional) | `{"ok": true, "columns": [...], "rows": [...], "total": 42, "query_ms": 3.2}` |
| `GET /datasets/<id>/export` | the same controls and filters | the rows as a `text/csv` attachment named `<id>.csv` |

An upload must be a `multipart/form-data` request — anything else is a 415 —
carrying the file under either accepted field name; a body that carries neither,
or that is malformed enough to parse to nothing, is a 400.

`/export` writes the source columns, in source order, above the rows the
dataset route would have returned: filters, sorting and pagination all apply.
`_shape`, `_rowid` and `_total` describe a JSON body, so a CSV file ignores
them.

### Dataset controls

| Parameter | Values | Effect |
| --- | --- | --- |
| `_size` | positive integer, default 100 | how many rows to return; a size past the end returns the rest |
| `_offset` | non-negative integer, default 0 | how many rows to skip first |
| `_sort` | column name | sort ascending by that column |
| `_sort_desc` | column name | sort descending; outranks `_sort` when both are given |
| `_shape` | `lists` (default) or `objects` | rows as value arrays, or as column-keyed objects |
| `_rowid` | `hide` | drop `rowid` from object rows |
| `_total` | `hide` | drop `total` from the response |

Sorting is stable and runs before pagination, `total` counts the rows before
it, and `rowid` is the row's 1-based line in the source file, counting the
header as line one. Repeating any control, or giving it a value outside the
table above, is a 400.

### Column filters

Any parameter shaped `<column>__<comparator>=<value>` filters the rows:

| Comparator | Keeps a row when its value... |
| --- | --- |
| `exact` | equals the value, case-sensitively |
| `contains` | holds the value as a substring, case-sensitively |
| `less` | reads as a number below the value |
| `greater` | reads as a number above the value |

Column names must match exactly, and several filters all have to hold at once,
as in `?role__contains=eng&score__greater=10`. Filtering happens before
sorting, so `total` and pagination both describe the matching rows. Values
that are not numbers — text, blanks — never match `less` or `greater`, and a
non-numeric filter value for either is a 400, as are an unknown column, an
unknown comparator, a repeated filter and a query that outlives its time
budget. Names starting with `_` are controls, and names without a `__`
suffix are neither filter nor control and are ignored.

Errors are JSON: `{"ok": false, "error": "..."}` — 400 for bad requests and
content that describes no table, 404 for unreachable sources and unknown
datasets or routes, 415 for an upload that is not multipart. All responses
carry permissive CORS headers.

## Behaviour

- CSV, `.xls` and `.xlsx` payloads are all accepted, and the format is read
  off the bytes rather than off a file name or a URL. Anything that is neither
  a readable workbook nor a delimited table is a 400.
- Only a workbook's first worksheet is ingested, in its own column order, and
  it needs a header row and at least one data row like any other source.
- The dataset id is a hash of the source URL for a conversion and of the file
  bytes for an upload, so the same source always maps to the same endpoint and
  re-ingesting it refreshes its rows in place.
- `charset` only describes text CSV, and is only validated there: a workbook
  brings its own encoding and ignores the parameter.
- Without an explicit `charset`, a BOM or a clean UTF-8 decode decides the
  encoding; otherwise the bytes are read as latin-1.
- The delimiter (`,`, `;`, tab or `|`) is inferred by picking the one that
  splits the file into the widest consistent table.
- Integers and decimals become JSON numbers; times such as `08:30` and every
  other value stay text.

## Layout

| File | Responsibility |
| --- | --- |
| `datagate.py` | CLI entry point |
| `app.py` | routes, error envelope, CORS |
| `fetcher.py` | source URL validation and download |
| `uploads.py` | multipart upload reading and content fingerprinting |
| `tabular.py` | format dispatch, decoding, delimiter detection, type inference, CSV output |
| `sheets.py` | first-worksheet reading for `.xls` and `.xlsx` workbooks |
| `query.py` | dataset query controls: paging, sorting, response shape |
| `filters.py` | `column__comparator` filters and the query time budget |
| `store.py` | dataset records and id derivation |
| `test_datagate.py` | pytest suite (`.venv/bin/python -m pytest`) |
