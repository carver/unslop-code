# datagate

A small HTTP service that ingests CSV files and Excel workbooks — fetched from a URL or
uploaded — and serves them back as JSON or CSV.

## Running

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

`--port` defaults to `8001` and `--address` to `127.0.0.1`.

### Configuration

Settings come from three places, each overriding the one before it: the built-in defaults, the
file named by `DATAGATE_CONFIG`, then the environment variables themselves.

| Setting | Default | Effect |
| --- | --- | --- |
| `MAX_SOURCE_SIZE` | unset | Largest ingested file, in bytes; unset means no maximum |
| `ORIGIN_ALLOWLIST` | unset | Comma-separated domain suffixes allowed to call the service |
| `REQUIRE_TLS` | `false` | Whether ingestion endpoints are reported as absolute `https://` URLs |
| `STORAGE_DIR` | `datagate-data` | Directory the ingested datasets are kept in |
| `CACHE_ENABLED` | `true` | Whether `/convert` may answer from already-converted sources |

The config file holds one `KEY=VALUE` per line; blank lines and lines starting with `#` are
ignored, and list values are comma-separated:

```
# /etc/datagate.conf
MAX_SOURCE_SIZE=10485760
ORIGIN_ALLOWLIST=example.com, reports.example.org
REQUIRE_TLS=on
STORAGE_DIR=/var/lib/datagate
```

```bash
DATAGATE_CONFIG=/etc/datagate.conf .venv/bin/python datagate.py start
```

Booleans are read case-insensitively and accept `1`, `true`, `yes`, `on` and `0`, `false`, `no`,
`off`. A value outside those, a size that is not a whole number of bytes, a line that is not
`KEY=VALUE`, a setting datagate does not have, and a `DATAGATE_CONFIG` file that cannot be read
are all configuration mistakes: the service reports them and refuses to start.

#### Maximum source size

`MAX_SOURCE_SIZE` applies to both ingestion endpoints. A file exactly at the limit is accepted and
one above it is a 400; a cached `/convert` answers from the store without fetching anything, so
the limit applies when the source is actually downloaded.

#### Origin allowlist

With `ORIGIN_ALLOWLIST` set, every request — including ones no route would have served — has to
carry a `Referer` whose hostname is an allowed domain or a subdomain of one, or it is a 403.
Matching is case-insensitive and stops at a label boundary, so `example.com` covers
`docs.example.com` but neither `notexample.com` nor `example.com.elsewhere.org`. A suffix may be
written with or without its leading dot. Without an allowlist every request passes, `Referer` or
not.

#### Endpoint URLs

`/convert` and `/upload` report where a dataset is served from. By default that is a path on this
service, such as `/datasets/0daefea780c7d65a`. With `REQUIRE_TLS` on it is an absolute URL on the
requested host instead — `https://data.example.com/datasets/0daefea780c7d65a` — which keeps a
client that arrived over plain HTTP from following it back over plain HTTP.

#### Storage

`STORAGE_DIR` is created if it does not exist. Every ingested dataset is written there as JSON
named after its id, so a service restarted against the same directory still serves — and still
answers `/convert` from — everything earlier runs ingested.

## Endpoints

### `GET /convert?source=<url>[&charset=<encoding>][&force][&enrich=yes]`

Downloads the file at `source`, parses it, and returns the endpoint it is served from:

```json
{"ok": true, "endpoint": "/datasets/0daefea780c7d65a"}
```

The id is a hash of the `source` URL string, so the same URL always maps to the same endpoint.
`charset` is optional and applies to CSV text only; without it the encoding is detected from the
content.

#### Caching

A source that has already been converted is answered from the store rather than downloaded again,
with the same response a fresh parse gives. `force` — a presence flag, with or without a value —
downloads and parses the source again and replaces the stored dataset. The replacement only
happens once the new content has parsed, so a source that has since broken or vanished leaves the
previous dataset queryable and reports its usual error.

With `CACHE_ENABLED` off, every `/convert` downloads and parses the source again and replaces the
stored dataset, which is what `force` already asks for, so `force` changes nothing.

#### Enrichment

`enrich=yes` describes the source as it is ingested and stores the description alongside the
table, so every later read of `/datasets/<id>` reports it too. Only that exact value asks for it:
a different value, no value at all, the parameter repeated, and the parameter absent are all
simply not the request, and leave enrichment off rather than failing. The reply is the usual one
either way — enrichment changes what the dataset endpoint reports, not what `/convert` answers.

Enrichment is a `/convert` option; `/upload` ignores it, and so does `/datasets/<id>`.

A conversion answered from the cache is not re-ingested and so describes nothing new, which is
what decides how `enrich` and the cache meet:

| Request | Stored dataset | Outcome |
| --- | --- | --- |
| `enrich=yes` | converted without enrichment | Ingested again, and stored with its description |
| `enrich=yes` | already described | Answered from the store, description intact |
| no `enrich` | already described | Answered from the store, description intact |
| no `enrich`, with `force` | already described | Ingested again, and stored without a description |

Every re-ingestion — `force`, an upgrade, or any conversion at all with `CACHE_ENABLED` off —
describes the bytes it has just downloaded, so a source that has grown since it was first
converted is reported at its current size. A source that fails to parse or describe reports its
usual error and replaces nothing, so a dataset stored with its description keeps it.

| Condition | Status |
| --- | --- |
| Missing `source`, invalid URL, bad `charset`, repeated `force`, unreadable or non-tabular content, source above `MAX_SOURCE_SIZE` | 400 |
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
| Malformed multipart body, neither `file` nor `attachment` present, unreadable content, file above `MAX_SOURCE_SIZE` | 400 |
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

#### Enrichment metadata

A dataset converted with `enrich=yes` also reports what that conversion recorded. `dataset_summary`
covers every format, and CSV datasets add `column_details`, one entry per column in source order,
keyed by column name:

```json
{"ok": true, "columns": ["name", "age"], "rows": [["Ada", 36]],
 "dataset_summary": {"filetype": "csv", "row_count": 1, "column_count": 2},
 "column_details": {
   "name": {"type": "text", "distinct_count": 1, "missing_count": 0},
   "age": {"type": "integer", "distinct_count": 1, "missing_count": 0}},
 "total": 1, "query_ms": 0.019}
```

`filetype` is `csv` for delimited text and `excel` for either workbook format, and the counts
cover the whole dataset rather than the page being read, so filters and pagination do not move
them. A column is `integer` or `float` when every value it holds is one and `number` when it
mixes the two; anything else is `text`. Blank cells are counted as `missing_count` and left out
of both the type and `distinct_count`, so a column of numbers with a few gaps is still a number
column. A workbook types every cell on its own rather than by column, so an enriched workbook
reports the summary alone.

A dataset converted without `enrich=yes` leaves both fields out entirely — they are absent, not
null or empty — and enrichment changes nothing else: `ok`, `columns`, `rows`, `total` and
`query_ms` read exactly as they do without it.

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
(including errors) carry permissive CORS headers for browser clients. A request blocked by the
origin allowlist gets that same envelope with a 403.

## Layout

| File | Responsibility |
| --- | --- |
| `datagate.py` | Command line entry point |
| `app.py` | Routes, uploads, CORS, JSON error envelope |
| `config.py` | Settings: defaults, the `DATAGATE_CONFIG` file, the environment |
| `caching.py` | The `/convert` `force` flag |
| `enrichment.py` | The `/convert` `enrich` flag and the metadata it records |
| `origins.py` | The `Referer` origin allowlist |
| `limits.py` | The maximum source size |
| `fetching.py` | Source URL validation and download |
| `ingestion.py` | Format detection and the grid-to-dataset split |
| `csv_parsing.py` | Decoding, delimiter inference, type inference |
| `spreadsheets.py` | First-worksheet reading of `.xls` and `.xlsx` workbooks |
| `exporting.py` | CSV rendering of an exported page |
| `querying.py` | Control parameters: pagination, sorting, response shape |
| `filtering.py` | Filter parameters: comparators and the filtered row scan |
| `store.py` | Dataset records, content-derived ids, and the storage directory |
| `errors.py` | Error type carrying an HTTP status |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

The suite serves CSV and workbook fixtures over a real loopback HTTP server and drives the app
end to end.
