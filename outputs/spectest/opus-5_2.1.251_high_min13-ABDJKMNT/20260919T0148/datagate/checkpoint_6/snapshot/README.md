# datagate

A small HTTP gateway that converts remote CSV and spreadsheet files into
queryable JSON datasets, and exports them back as CSV.

## Run

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

## Endpoints

- `GET /convert?source=<url>[&charset=<codec>][&force]` → `{"ok": true, "endpoint": "/datasets/<id>"}`
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

### Caching

`/convert` caches by default: a source URL that has already been converted answers
from the stored dataset, with the same `200` envelope as a fresh parse and without
touching the network. The cache is keyed on the source URL alone, so `charset` does
not reopen a hit.

`CACHE_ENABLED` turns it off; see [Configuration](#configuration) for its vocabulary.
With caching off, every request re-downloads, re-parses and replaces the stored
dataset.

`force` is a presence flag on `/convert`: given once, whatever value it carries, it
re-ingests and replaces the cached dataset under the same id. Repeating it is
`HTTP 400`, with or without caching. A re-ingestion that fails answers with the
usual status and error envelope, and leaves the previous dataset queryable.

### Export

`GET /datasets/<id>/export` answers `Content-Type: text/csv` and
`Content-Disposition: attachment; filename="<dataset-id>.csv"`. It honours the
same filters, sorting and pagination as `/datasets/<id>`, including the default
page size, and writes the columns in source order beneath a header row.
`_shape`, `_rowid` and `_total` are still validated but cannot change the bytes.

## Configuration

Settings come from three sources, each overriding the one before it: the built-in
defaults, the `KEY=VALUE` file named by `DATAGATE_CONFIG`, and direct environment
variables. Unusable configuration — a file that cannot be read, a malformed line, a
value outside a setting's vocabulary, or a `STORAGE_DIR` that cannot be created —
fails startup with a message on stderr and a non-zero exit.

| Setting | Type | Default |
| --- | --- | --- |
| `MAX_SOURCE_SIZE` | integer bytes | unset (no maximum) |
| `ORIGIN_ALLOWLIST` | comma-separated domain suffixes | unset (all origins pass) |
| `REQUIRE_TLS` | boolean | `false` |
| `STORAGE_DIR` | path | `./datagate_data` |
| `CACHE_ENABLED` | boolean | `true` |

Booleans are `1`, `true`, `yes`, `on` or `0`, `false`, `no`, `off`, case-insensitive
and trimmed. In the config file, blank lines and lines beginning with `#` are
ignored, a value may contain `=`, a repeated key takes its last assignment, and keys
that are not settings are ignored.

```
# /etc/datagate.conf
MAX_SOURCE_SIZE=5242880
ORIGIN_ALLOWLIST=example.com,cdn.example.org
REQUIRE_TLS=true
STORAGE_DIR=/var/lib/datagate
```

### Maximum source size

`MAX_SOURCE_SIZE` caps the payload both ingestion routes will parse: a file exactly
at the limit is accepted, one byte more is `HTTP 400`. The bytes measured are the
downloaded body for `/convert` and the uploaded part for `/upload`, so multipart
framing does not count against the limit. A `/convert` answered from the cache
downloads nothing and so is not measured.

### Origin allowlist

With `ORIGIN_ALLOWLIST` configured, every request is checked before it is routed: it
must carry a `Referer` whose hostname is one of the listed suffixes or a subdomain of
one, compared case-insensitively on a label boundary — `example.com` admits
`example.com` and `app.example.com`, but not `notexample.com`. Anything else is
`HTTP 403`, including a request for a path that does not exist.

### Endpoint URLs

`/convert` and `/upload` report a relative `/datasets/<id>` by default. Under
`REQUIRE_TLS=true` the same endpoint is absolute — `https://<request host>/datasets/<id>`
— keeping whatever port the caller addressed.

### Storage directory

`STORAGE_DIR` is created at startup if it is missing, parents included, and holds one
JSON document per dataset. A process started over a directory another one filled
serves those datasets from `/datasets/<id>` and treats them as `/convert` cache hits.

## Dataset control parameters

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

## Dataset filters

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
| `datagate_core/config.py` | Resolving the settings from defaults, file and environment |
| `datagate_core/config_file.py` | Parsing the `DATAGATE_CONFIG` `KEY=VALUE` file |
| `datagate_core/access.py` | The `ORIGIN_ALLOWLIST` `Referer` check |
| `datagate_core/limits.py` | The `MAX_SOURCE_SIZE` ceiling |
| `datagate_core/endpoints.py` | Relative versus absolute endpoint URLs |
| `datagate_core/storage.py` | Datasets on disk under `STORAGE_DIR` |
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
| `datagate_core/caching.py` | The `force` re-ingestion flag |

`AMBIGUITIES.md` records the spec readings this implementation chose.

## Tests

```
.venv/bin/python -m pytest
```
