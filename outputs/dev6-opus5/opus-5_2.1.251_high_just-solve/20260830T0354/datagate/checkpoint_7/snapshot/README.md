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

`--port` defaults to `8001`, `--address` to `127.0.0.1`. Everything else is
[configuration](#configuration), read once at startup.

## Configuration

Settings come from three sources, each overriding the one before it:

1. built-in defaults
2. the `KEY=VALUE` file named by the `DATAGATE_CONFIG` environment variable
3. the environment variables themselves

| Setting | Type | Default |
|---|---|---|
| `MAX_SOURCE_SIZE` | integer bytes | unset (no maximum) |
| `ORIGIN_ALLOWLIST` | comma separated domain suffixes | unset (everything passes) |
| `REQUIRE_TLS` | boolean | `false` |
| `STORAGE_DIR` | path | `.datagate-storage` beside `datagate.py` |
| `CACHE_ENABLED` | boolean | `true` |

```
# /etc/datagate.conf -- blank lines and #/; comments are ignored
MAX_SOURCE_SIZE = 5242880
ORIGIN_ALLOWLIST = example.com, cdn.trusted.org
REQUIRE_TLS = yes
STORAGE_DIR = /var/lib/datagate
```

Booleans accept, trimmed and case-insensitively, `1`, `true`, `yes` or `on` for
true and `0`, `false`, `no` or `off` for false. List values are split on commas
and blank entries are dropped; an empty value clears the setting. Keys are
matched case-insensitively and unknown keys are ignored. A config file that
cannot be read, a line that is not `KEY=VALUE`, and any value that is not valid
for its setting are all startup failures: the service reports the problem on
stderr and exits non-zero rather than running on guessed settings.

### Maximum source size

`MAX_SOURCE_SIZE` caps the bytes `/convert` and `/upload` will ingest. A source
whose size is exactly the limit is accepted; a larger one is a `400` with the
usual error envelope, and `/convert` stops downloading as soon as the limit is
passed. With the setting unset there is no maximum.

### Origin allowlist

With `ORIGIN_ALLOWLIST` configured, every request is checked before it is
routed: it must carry a `Referer`, that `Referer` must have a hostname, and the
hostname must match one of the allowed suffixes on a domain boundary. Matching
ignores case, so `example.com` covers `example.com` and `app.EXAMPLE.com` but
neither `notexample.com` nor `example.com.evil.net`. Anything else is a `403`
with the usual error envelope. With no allowlist every request passes.

### TLS-aware endpoint URLs

With `REQUIRE_TLS` false (the default) `/convert` and `/upload` return relative
endpoints such as `/datasets/<id>`. With it true the same endpoints come back as
absolute `https://<request host>/datasets/<id>` URLs, so a caller that arrived
over plain http is still sent on over TLS.

### Storage directory

`STORAGE_DIR` is created if it is missing, and every ingested dataset is written
into it, so datasets stay queryable across a restart that reuses the same
directory. The `/convert` cache itself is not persisted: after a restart the
first request for a source is re-ingested and lands on the same dataset id.

## Endpoints

- `GET /convert?source=<url>[&charset=<charset>][&force][&enrich=yes]` -> `{"ok": true, "endpoint": "/datasets/<id>"}`
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
  - plus `dataset_summary` and `column_details` when the dataset was ingested
    with [enrichment](#enrichment)
- `GET /datasets/<id>/export` -> the same rows as CSV bytes
  - `Content-Type: text/csv`, `Content-Disposition: attachment; filename="<id>.csv"`
  - source column order, and the same filters, sort and pagination as
    `/datasets/<id>`; `_shape`, `_rowid` and `_total` cannot change a CSV body

### Caching

`/convert` caches its results by default, keyed by the source URL (and the
`charset` it was decoded with, since that decides how the same bytes parse). A
repeated request returns the cached dataset id without re-downloading the
source, and its response is byte-for-byte what a fresh parse returns.

`CACHE_ENABLED` turns the cache off; see [Configuration](#configuration) for how
it is spelled and where it can be set. With the cache disabled every `/convert`
request re-downloads and re-parses the source, replacing the stored dataset.

`force` is a presence flag -- its value is ignored -- and bypasses the cache for
one request, re-ingesting the source and replacing the cached dataset. Giving
`force` more than once is a `400`. With the cache disabled `force` changes
nothing, because every request already re-ingests.

`enrich=yes` against a cached dataset that was stored without
[enrichment](#enrichment) re-ingests the source and upgrades what is stored;
once the dataset is enriched the cache answers again. A request that is served
from the cache re-ingests nothing and so leaves the stored enrichment alone,
while every re-ingestion -- forced, uncached or upgrading -- recomputes the
dataset, and its metadata, from the bytes the source serves at that moment.

A re-ingestion that fails reports the same status and error envelope as a first
ingestion would, and leaves the previously stored dataset queryable.

### Enrichment

`/convert` profiles what it ingests when the request carries exactly
`enrich=yes`. Any other state -- no `enrich`, a bare `enrich`, `enrich=YES`,
`enrich=1`, `enrich=no`, an empty value, or the parameter repeated -- ingests
without enrichment rather than failing. The `/convert` response is the usual
`{"ok": true, "endpoint": "/datasets/<id>"}` either way; the metadata shows up
on the dataset:

```json
{
  "ok": true,
  "columns": ["name", "age", "score"],
  "rows": [["Alice", 30, 91.5]],
  "total": 1,
  "query_ms": 0.4,
  "dataset_summary": {"filetype": "csv", "row_count": 1, "column_count": 3},
  "column_details": {
    "name":  {"type": "text",    "distinct_count": 1, "missing_count": 0},
    "age":   {"type": "integer", "distinct_count": 1, "missing_count": 0},
    "score": {"type": "float",   "distinct_count": 1, "missing_count": 0}
  }
}
```

`column_details` is keyed by column name. A column of whole numbers is
`integer`, one of decimals is `float`, one holding both is `number`, and
anything else -- including a column that is entirely empty -- is `text`.
`missing_count` counts the empty cells and `distinct_count` the distinct values
among the rest. Enrichment describes the whole dataset, so filters and
pagination do not change it.

A workbook gets a `dataset_summary` with `"filetype": "excel"` and no
`column_details`. A dataset ingested without enrichment omits both fields
entirely rather than reporting them as `null` or empty, and `rows`, `columns`,
`ok`, `query_ms` and `total` are the same either way.

`enrich` is a `/convert` parameter: `/upload` and `/datasets/<id>` ignore it,
and a dataset keeps whatever enrichment its last ingestion produced. An
enrichment that fails answers with the usual JSON error and leaves the stored
dataset -- enrichment included -- exactly as it was.

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

| Condition | HTTP |
|---|---|
| source larger than `MAX_SOURCE_SIZE` | 400 |
| missing `Referer` while an allowlist is configured | 403 |
| `Referer` not on the allowlist | 403 |
| invalid startup configuration | startup failure, non-zero exit |

## Tests

```
./venv/bin/python tests/run_tests.py
```

The binary spreadsheet fixtures are committed; regenerate them with
`./venv/bin/python tests/make_fixtures.py` after changing their contents.
