# datagate

A small HTTP service that ingests CSV files and Excel workbooks — fetched from a URL or
uploaded — and serves them back as JSON or CSV.

## Running

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

`--port` defaults to `8001` and `--address` to `127.0.0.1`.

## Endpoints

### `GET /convert?source=<url>[&charset=<encoding>]`

Downloads the file at `source`, parses it, and returns the endpoint it is served from:

```json
{"ok": true, "endpoint": "/datasets/0daefea780c7d65a"}
```

The id is a hash of the `source` URL string, so the same URL always maps to the same endpoint.
`charset` is optional and applies to CSV text only; without it the encoding is detected from the
content.

| Condition | Status |
| --- | --- |
| Missing `source`, invalid URL, bad `charset`, unreadable or non-tabular content | 400 |
| Source unreachable or remote HTTP error | 404 |

### `POST /upload`

Ingests a file sent as `multipart/form-data` under the field `file` or `attachment`:

```bash
curl -F file=@staff.xlsx http://127.0.0.1:8001/upload
```

```json
{"ok": true, "endpoint": "/datasets/9a361d18403c0719"}
```

The id is a hash of the file's bytes, so re-uploading the same content — under either field name,
under any file name — maps to the same endpoint.

| Condition | Status |
| --- | --- |
| Malformed multipart body, neither `file` nor `attachment` present, unreadable content | 400 |
| Request is not `multipart/form-data` | 415 |

### Accepted formats

Both ingestion endpoints accept CSV text, `.xls` and `.xlsx`. The format is read from the payload
itself rather than from a file name, and only the workbook's first worksheet is ingested — it has
to be tabular (a header row and at least one data row), or the request is a 400. Spreadsheet cells
keep their own types, and formulas are read as the value cached in the file, if any.

### `GET /datasets/<id>`

```json
{"ok": true, "columns": ["name", "age"], "rows": [["Ada", 36]], "total": 1, "query_ms": 0.014}
```

Columns and rows keep their source order, and `total` is the number of matching rows before
pagination.
Unknown ids give 404.

Cells become JSON numbers when they are unambiguously an integer or a decimal; everything else —
including time-like values such as `08:30` — stays text.

#### Control parameters

| Parameter | Default | Effect |
| --- | --- | --- |
| `_size` | `100` | Positive integer row limit; a size past the end returns the rows that exist |
| `_offset` | `0` | Non-negative integer count of rows to skip |
| `_sort=<column>` | — | Sort ascending by `<column>` |
| `_sort_desc=<column>` | — | Sort descending by `<column>`; wins if `_sort` is also given |
| `_shape` | `lists` | `lists` for array rows, `objects` for one dict per row |
| `_rowid=hide` | — | Drop `rowid` from object rows |
| `_total=hide` | — | Drop `total` from the response |

Sorting is stable — tied rows keep their source order — and runs before pagination. Numbers sort
ahead of text, so a column mixing `7` with `n/a` is still sortable.

`_shape=objects` keys each row by column name and prefixes it with `rowid`, the 1-based position
of the row among the source file's data rows. It survives sorting and pagination, so it always
points back at the same source row, and it is never listed in `columns`:

```json
{"ok": true, "columns": ["name", "age"],
 "rows": [{"rowid": 2, "name": "Grace", "age": 45}], "total": 2, "query_ms": 0.021}
```

A control parameter that is repeated, or given a value outside the table above — a non-positive
`_size`, a negative `_offset`, an unknown or empty sort column, an unrecognised `_shape`, a
`_rowid`/`_total` value other than `hide` — is a 400.

#### Filter parameters

Any other parameter shaped `<column>__<comparator>=<value>` filters the rows:

| Comparator | Keeps a row when its cell |
| --- | --- |
| `exact` | equals the value, as text and case-sensitively |
| `contains` | contains the value, as text and case-sensitively |
| `less` | reads as a number strictly below the value |
| `greater` | reads as a number strictly above the value |

```
/datasets/<id>?role__exact=engineer&age__greater=40&_sort_desc=age
```

Several filters are ANDed. Column names match exactly and case-sensitively, and cells that are not
numbers — `n/a`, or a time such as `08:30` — never match `less` or `greater`. Filtering runs first,
then sorting, then pagination, so `total` reports the matches rather than the file's row count.

Parameters that name no comparator, such as `role=engineer`, are not filters and are ignored. A
repeated filter, an unknown column, an unknown comparator, a non-numeric value for `less`/`greater`,
and a query that outruns its time budget are all 400s.

### `GET /datasets/<id>/export`

Returns the same rows as `/datasets/<id>` as a CSV file:

```
Content-Type: text/csv
Content-Disposition: attachment; filename="<id>.csv"
```

Columns follow the source order and rows are filtered, sorted and paginated exactly as they are for
the dataset endpoint, so `?role__exact=engineer&_sort_desc=age&_size=10` narrows the download the
same way. `_shape`, `_rowid` and `_total` describe a JSON response and make no difference to the
CSV. Unknown ids give 404, bad parameters 400 — both as JSON.

Every response carries `ok`, errors use `{"ok": false, "error": "..."}`, and all responses
(including errors) carry permissive CORS headers for browser clients.

## Layout

| File | Responsibility |
| --- | --- |
| `datagate.py` | Command line entry point |
| `app.py` | Routes, uploads, CORS, JSON error envelope |
| `fetching.py` | Source URL validation and download |
| `ingestion.py` | Format detection and the grid-to-dataset split |
| `csv_parsing.py` | Decoding, delimiter inference, type inference |
| `spreadsheets.py` | First-worksheet reading of `.xls` and `.xlsx` workbooks |
| `exporting.py` | CSV rendering of an exported page |
| `querying.py` | Control parameters: pagination, sorting, response shape |
| `filtering.py` | Filter parameters: comparators and the filtered row scan |
| `store.py` | Dataset records, cell types, and content-derived ids |
| `errors.py` | Error type carrying an HTTP status |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

The suite serves CSV and workbook fixtures over a real loopback HTTP server and drives the app
end to end.
