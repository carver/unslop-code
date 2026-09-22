# datagate

A small HTTP gateway that converts remote CSV and spreadsheet files into
queryable JSON datasets, and exports them back as CSV.

## Run

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

## Endpoints

- `GET /convert?source=<url>[&charset=<codec>]` → `{"ok": true, "endpoint": "/datasets/<id>"}`
- `POST /upload` (multipart, field `file` or `attachment`) → `{"ok": true, "endpoint": "/datasets/<id>"}`
- `GET /datasets/<id>` → `{"ok": true, "columns": [...], "rows": [...], "total": 42, "query_ms": 1.2}`
- `GET /datasets/<id>/export` → the same page as CSV, as a downloadable attachment

Errors are always JSON: `{"ok": false, "error": "<message>"}`.

### Ingestion formats

Both ingestion routes accept CSV, `.xls` and `.xlsx`, recognised from the
payload's leading bytes rather than from a filename or a served content type.
Only the first worksheet of a workbook is read, and it must hold a header row
and at least one data row. `charset` decodes text CSV only; it is ignored for
workbooks. Anything else is `HTTP 400`.

An upload is content-addressed: the same bytes always land on the same dataset
id, whichever field carried them and whatever the part was named. A request that
is not `multipart/form-data` is `HTTP 415`; one that is multipart but malformed,
or that carries neither `file` nor `attachment`, is `HTTP 400`.

### Export

`GET /datasets/<id>/export` answers `Content-Type: text/csv` and
`Content-Disposition: attachment; filename="<dataset-id>.csv"`. It honours the
same filters, sorting and pagination as `/datasets/<id>`, including the default
page size, and writes the columns in source order beneath a header row.
`_shape`, `_rowid` and `_total` are still validated but cannot change the bytes.

### Dataset control parameters

| Parameter | Values | Effect |
| --- | --- | --- |
| `_size` | positive integer (default `100`) | Rows per response. |
| `_offset` | non-negative integer (default `0`) | Rows skipped first. |
| `_sort` | column name | Sort ascending. |
| `_sort_desc` | column name | Sort descending; wins over `_sort`. |
| `_shape` | `lists` (default) or `objects` | Rows as arrays, or as objects carrying `rowid`. |
| `_rowid` | `hide` | Drop `rowid` from object rows. |
| `_total` | `hide` | Drop `total` from the response. |

Sorting is stable and happens before pagination. An invalid value, an unknown
sort column, or any repeated control parameter is `HTTP 400`.

### Dataset filters

Any other parameter shaped `<column>__<comparator>=<value>` filters the rows:

| Comparator | Match |
| --- | --- |
| `exact` | Case-sensitive equality with the cell's text. |
| `contains` | Case-sensitive substring of the cell's text. |
| `less` | Cell parses as a float and is strictly below the value. |
| `greater` | Cell parses as a float and is strictly above the value. |

Filters are ANDed, run before sorting, and `total` counts the rows they keep.
Cells that do not parse as numbers never match `less`/`greater`. An unknown
column or comparator, a repeated filter key, a non-numeric value for a numeric
comparator, and a query that outlives its time budget are all `HTTP 400`.
Parameters beginning with `_`, and parameters with no `__`, are not filters.

## Layout

| Path | Responsibility |
| --- | --- |
| `datagate.py` | CLI entry point (`start`, `--port`, `--address`) |
| `datagate_core/server.py` | Routes, JSON envelope, CORS headers |
| `datagate_core/controls.py` | Validation of the `_size`/`_sort`/`_shape` family |
| `datagate_core/filtering.py` | Parsing and applying `<column>__<comparator>` filters |
| `datagate_core/projection.py` | Filtering, sorting, pagination and row rendering |
| `datagate_core/timing.py` | The per-query time budget |
| `datagate_core/exporting.py` | CSV serialisation and the download headers |
| `datagate_core/conversion.py` | Ingestion pipeline: fetch → detect → parse → store |
| `datagate_core/uploads.py` | Reading the file part out of a multipart upload |
| `datagate_core/fetching.py` | Source URL validation and retrieval |
| `datagate_core/formats.py` | Recognising CSV, `.xls` and `.xlsx` payloads |
| `datagate_core/decoding.py` | Charset handling and encoding detection |
| `datagate_core/parsing.py` | Delimiter inference and table extraction |
| `datagate_core/spreadsheets.py` | Reading the first worksheet of a workbook |
| `datagate_core/tables.py` | Header/row splitting shared by both readers |
| `datagate_core/inference.py` | Cell typing (numbers vs. text) |
| `datagate_core/store.py` | Dataset ids and the in-memory store |

`AMBIGUITIES.md` records the spec readings this implementation chose.

## Tests

```
.venv/bin/python -m pytest
```
