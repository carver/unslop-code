# datagate

Fetches or accepts an upload of a CSV, `.xls` or `.xlsx` file, infers a CSV's
delimiter and encoding, and serves the table as JSON or CSV.

## Setup

```
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## Run

```
./venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

`--port` defaults to `8001`, `--address` to `127.0.0.1`. The `CACHE_ENABLED`
environment variable (default true) is read at startup; see [Caching](#caching).

## Endpoints

- `GET /convert?source=<url>[&charset=<charset>][&force]` -> `{"ok": true, "endpoint": "/datasets/<id>"}`
  - 400: missing `source`, invalid URL, unsupported/malformed `charset`, repeated
    `force`, unsupported format, non-tabular content
  - 404: source unreachable or remote HTTP error
- `POST /upload` (multipart form, field `file` or `attachment`) -> `{"ok": true, "endpoint": "/datasets/<id>"}`
  - the id is derived from the file bytes, so re-uploading the same bytes returns
    the same endpoint
  - 400: malformed multipart, neither `file` nor `attachment`, unsupported format,
    non-tabular content
  - 415: the request is not `multipart/form-data`
- `GET /datasets/<id>` -> `{"ok": true, "columns": [...], "rows": [...], "total": 250, "query_ms": 1.2}`
  - `total` is the row count *before* pagination; 404 for an unknown id
- `GET /datasets/<id>/export` -> the same rows as CSV bytes
  - `Content-Type: text/csv`, `Content-Disposition: attachment; filename="<id>.csv"`
  - source column order, and the same filters, sort and pagination as
    `/datasets/<id>`; `_shape`, `_rowid` and `_total` cannot change a CSV body

### Caching

`/convert` caches its results by default, keyed by the source URL (and the
`charset` it was decoded with, since that decides how the same bytes parse). A
repeated request returns the cached dataset id without re-downloading the
source, and its response is byte-for-byte what a fresh parse returns.

`CACHE_ENABLED` turns the cache off. It accepts, case-insensitively, `1`,
`true`, `yes` or `on` for true and `0`, `false`, `no` or `off` for false; any
other value fails startup. With the cache disabled every `/convert` request
re-downloads and re-parses the source, replacing the stored dataset.

`force` is a presence flag -- its value is ignored -- and bypasses the cache for
one request, re-ingesting the source and replacing the cached dataset. Giving
`force` more than once is a `400`. With the cache disabled `force` changes
nothing, because every request already re-ingests.

A re-ingestion that fails reports the same status and error envelope as a first
ingestion would, and leaves the previously stored dataset queryable.

### Formats

`/convert` and `/upload` accept CSV, `.xls` and `.xlsx`. The container is decided
by content rather than by file name. Only the first worksheet of a workbook is
ingested, and it must be tabular -- a header row plus at least one data row --
or the request is a `400`. Fully empty rows and trailing empty columns are
dropped; dates, times and booleans are rendered deterministically. `charset`
applies only to text CSV sources; anything that is neither CSV nor a supported
workbook is a `400`.

### Control parameters

| Parameter | Default | Meaning |
|---|---|---|
| `_size` | `100` | positive integer; rows to return. Larger than the row count returns all rows. |
| `_offset` | `0` | non-negative integer; rows to skip. |
| `_sort=<column>` | -- | sort ascending by `<column>`. |
| `_sort_desc=<column>` | -- | sort descending by `<column>`; wins when both are given. |
| `_shape` | `lists` | `lists` -> `rows` is arrays; `objects` -> `rows` is objects plus a `rowid`. |
| `_rowid=hide` | -- | omit `rowid` from `objects` rows. |
| `_total=hide` | -- | omit `total` from the response. |
| `_timeout_ms` | `5000` | non-negative integer; wall-clock budget for the query. |

Sorting is stable and applied before pagination. `rowid` is the 1-based row
number in the source file, so it survives filtering and sorting and is never
listed in `columns`. The legacy `limit`/`offset` spellings still work when
`_size`/`_offset` are absent.

A control parameter given more than once is a `400`, as is a non-positive or
non-integer `_size`, a negative or non-integer `_offset`, a `_shape` other than
`lists`/`objects`, a `_rowid`/`_total` value other than `hide`, an empty or
unknown `_sort`/`_sort_desc` column, and a negative or non-integer `_timeout_ms`.
Exceeding the time budget is also a `400`.

### Filter parameters

Rows are filtered with `<column>__<comparator>=<value>`:

| Comparator | Meaning |
|---|---|
| `exact` | case-sensitive string equality |
| `contains` | case-sensitive substring |
| `less` | numeric strict less (`float` parse of the stored and filter values) |
| `greater` | numeric strict greater |

```
/datasets/<id>?city__contains=Ber&score__greater=0&_sort=name
```

Multiple filters are ANDed. Column names are matched exactly and
case-sensitively, and the comparator is taken from the *last* `__` in the
parameter name, so a column that itself contains `__` still works.

Filtering happens before sorting, pagination runs on the filtered and sorted
rows, and `total` counts the filtered rows before pagination.

Rows whose stored value is not numeric never match `__less`/`__greater`. A
non-numeric *filter* value for those comparators is a `400`, as is an unknown
comparator, an unknown column, and a filter key given more than once.

Parameters beginning with `_` are control parameters and are never filters.
Parameters with neither a leading `_` nor a `__` are ignored rather than
rejected.

Errors are always JSON: `{"ok": false, "error": "..."}` -- except for a successful
`/export`, whose body is CSV. CORS headers are sent on every response.

## Tests

```
./venv/bin/python tests/run_tests.py
```

The binary spreadsheet fixtures are committed; regenerate them with
`./venv/bin/python tests/make_fixtures.py` after changing their contents.
