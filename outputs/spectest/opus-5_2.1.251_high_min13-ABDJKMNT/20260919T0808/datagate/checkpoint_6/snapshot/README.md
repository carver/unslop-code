# datagate

An HTTP gateway that ingests a tabular file - fetched from a URL or uploaded -
converts it to JSON, and serves it under a stable dataset endpoint.

## Run

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

`--port` defaults to `8001`, `--address` to `127.0.0.1`.

## Configuration

Settings come from three sources, each overriding the one before it: built-in
defaults, the file named by `DATAGATE_CONFIG`, then direct environment
variables. The file is `KEY=VALUE` lines - blank lines and `#` comments are
ignored, list values are comma-separated:

```
# datagate.conf
MAX_SOURCE_SIZE=10485760
ORIGIN_ALLOWLIST=example.com, partner.test
REQUIRE_TLS=on
```

| Setting | Type | Default | Meaning |
| --- | --- | --- | --- |
| `MAX_SOURCE_SIZE` | integer bytes | unset | Largest source `/convert` and `/upload` will ingest |
| `ORIGIN_ALLOWLIST` | domain suffixes | unset | Domains a request's `Referer` may come from |
| `REQUIRE_TLS` | boolean | `false` | Advertise dataset endpoints as absolute `https://` URLs |
| `STORAGE_DIR` | path | `./datagate-data` | Where datasets are kept between restarts |
| `CACHE_ENABLED` | boolean | `true` | Whether `/convert` may answer from a stored dataset |

Booleans are strict: `1`/`true`/`yes`/`on` or `0`/`false`/`no`/`off`, trimmed
and case-insensitive. An invalid value, a malformed config line, or a
`DATAGATE_CONFIG` that cannot be read stops startup with a message naming the
setting.

### Maximum source size

`MAX_SOURCE_SIZE` is enforced on the bytes `/convert` downloads and the bytes
`/upload` receives. A source exactly at the limit is accepted; one over it is
`HTTP 400`. Leaving the setting unset imposes no maximum.

### Origin allowlist

With `ORIGIN_ALLOWLIST` configured, every request is checked before it reaches a
route. It must carry a `Referer` whose hostname equals one of the suffixes or
sits beneath it - `example.com` covers `app.example.com` but not
`notexample.com` - compared case-insensitively. A missing `Referer` and an
unlisted one are both `HTTP 403`. Without the setting, every request passes.

### Endpoint URLs

`/convert` and `/upload` return a relative `/datasets/<id>` endpoint. Under
`REQUIRE_TLS=true` they return the same path as an absolute `https://` URL on
the host the request named.

### Storage

`STORAGE_DIR` is created at startup if it is missing, and holds one JSON file
per dataset. Pointing a restarted server at the same directory brings back every
dataset it stored, so `/datasets/<id>` keeps working and `/convert` still
answers from cache.

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
answers with the same endpoint without re-downloading, including after a restart
that reuses `STORAGE_DIR`. Setting `CACHE_ENABLED` to a false value turns that
off, and every `/convert` then re-downloads, re-parses and replaces the stored
dataset.

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
| `datagate_core/server.py` | Routes, the origin gate, JSON envelope, CORS |
| `datagate_core/config.py` | Settings, their defaults and their precedence |
| `datagate_core/config_file.py` | Reading the `DATAGATE_CONFIG` file |
| `datagate_core/access.py` | `ORIGIN_ALLOWLIST` and domain-suffix matching |
| `datagate_core/limits.py` | The `MAX_SOURCE_SIZE` ceiling |
| `datagate_core/ingestion.py` | Picking the reader for incoming bytes |
| `datagate_core/caching.py` | The per-request `force` cache bypass flag |
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
| `datagate_core/store.py` | Dataset ids and the on-disk store |
| `datagate_core/persistence.py` | Reading and writing a stored dataset file |
| `AMBIGUITIES.md` | Spec readings chosen where the spec is open |

## Tests

```bash
.venv/bin/python -m pytest
```
