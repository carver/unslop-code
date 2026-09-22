# datagate

An HTTP gateway that ingests a tabular file - fetched from a URL or uploaded -
converts it to JSON, and serves it under a stable dataset endpoint.

## Run

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

`--port` defaults to `8001`, `--address` to `127.0.0.1`.

## Endpoints

- `GET /convert?source=<url>[&charset=<encoding>][&force]` -> `{"ok": true, "endpoint": "/datasets/<id>"}`
- `POST /upload` (multipart, field `file` or `attachment`) -> `{"ok": true, "endpoint": "/datasets/<id>"}`
- `GET /datasets/<id>` -> `{"ok": true, "columns": [...], "rows": [...], "total": 2, "query_ms": 0.1}`
- `GET /datasets/<id>/export` -> the same page of rows as CSV

Errors are JSON: `{"ok": false, "error": "<message>"}`.

### Ingestion

Both ingestion routes read CSV, `.xls` and `.xlsx`, recognised from the bytes
themselves rather than from a file name. Only the first worksheet of a workbook
is read, and it must hold a header row plus at least one data row. `charset`
applies to text CSV only; anything datagate cannot read as a table is `HTTP
400`.

`/convert` keys a dataset by its `source` URL string; `/upload` keys it by the
file's bytes, so re-uploading the same file returns the same endpoint. A
non-multipart `POST /upload` is `HTTP 415`; a multipart body carrying neither
`file` nor `attachment` is `HTTP 400`.

### Caching

`/convert` caches by default: a repeat request for a source URL already stored
answers with the same endpoint without re-downloading. `CACHE_ENABLED` in the
environment turns that off - it accepts `1`/`true`/`yes`/`on` and
`0`/`false`/`no`/`off`, case-insensitively, and any other value stops startup.
With caching off, every `/convert` re-downloads, re-parses and replaces the
stored dataset.

`force` on a `/convert` request is a presence flag that bypasses the cache for
that request; its value is ignored, and repeating it is `HTTP 400`. A failed
re-ingestion answers with its usual status and leaves the previously stored
dataset queryable.

### Export

`GET /datasets/<id>/export` returns `text/csv` as an attachment named
`<dataset-id>.csv`. It takes the same filters, `_sort`/`_sort_desc` and
`_size`/`_offset` as the dataset endpoint and writes the resulting page with a
header row in source column order. `_shape`, `_rowid` and `_total` are accepted
and validated, but a CSV has no place to show them.

### Dataset controls

| Parameter | Default | Meaning |
| --- | --- | --- |
| `_size` | `100` | Positive integer; rows per page (`limit` is a deprecated alias) |
| `_offset` | `0` | Non-negative integer; rows to skip before the page |
| `_sort` | - | Sort ascending by the named column |
| `_sort_desc` | - | Sort descending; wins if `_sort` is also present |
| `_shape` | `lists` | `lists` for row arrays, `objects` for row objects with `rowid` |
| `_rowid` | - | `hide` drops `rowid` from `objects` rows |
| `_total` | - | `hide` drops `total` from the response |

Sorting is stable; `total` counts the rows that passed filtering, before
pagination. An invalid value, an unknown sort column, or any repeated control
parameter is `HTTP 400`.

### Filtering

Any parameter of the form `<column>__<comparator>=<value>` filters the rows:

| Comparator | Meaning |
| --- | --- |
| `exact` | Case-sensitive equality with the cell's text |
| `contains` | Case-sensitive substring of the cell's text |
| `less` | Numeric strict less than; non-numeric cells never match |
| `greater` | Numeric strict greater than; non-numeric cells never match |

Filters are ANDed and run before sorting, which runs before pagination. Names
beginning with `_` are controls, and names without `__` are ignored. An unknown
column, an unknown comparator, a repeated filter key, a non-numeric value for
`__less`/`__greater`, or a query that outlives its time budget is `HTTP 400`.

## Layout

| Path | Purpose |
| --- | --- |
| `datagate.py` | CLI entry point |
| `datagate_core/server.py` | Routes, JSON envelope, CORS |
| `datagate_core/ingestion.py` | Picking the reader for incoming bytes |
| `datagate_core/caching.py` | `CACHE_ENABLED` and the `force` bypass flag |
| `datagate_core/spreadsheets.py` | Reading the first worksheet of an `.xls`/`.xlsx` |
| `datagate_core/uploads.py` | Pulling the file out of a multipart upload |
| `datagate_core/exporting.py` | Writing a dataset page as a CSV attachment |
| `datagate_core/controls.py` | Dataset control parameters and their validation |
| `datagate_core/views.py` | Filtering, sorting, pagination and response shaping |
| `datagate_core/filters.py` | Column filters and their comparators |
| `datagate_core/timing.py` | The per-query time budget |
| `datagate_core/fetching.py` | URL validation and retrieval |
| `datagate_core/decoding.py` | Charset handling and detection |
| `datagate_core/tables.py` | Delimiter inference and CSV parsing |
| `datagate_core/values.py` | Cell type inference |
| `datagate_core/store.py` | Dataset ids and in-process storage |
| `AMBIGUITIES.md` | Spec readings chosen where the spec is open |

## Tests

```bash
.venv/bin/python -m pytest
```
