# datagate

Converts CSV and Excel files into JSON datasets served over HTTP.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

## Configuration

Settings come from three places, each overriding the one before it:

1. built-in defaults
2. the file `DATAGATE_CONFIG` names, if it names one
3. the environment variables themselves

The file holds one `KEY=VALUE` setting per line; blank lines and lines opening with `#`
are ignored, and list values are comma separated:

```
# datagate.conf
MAX_SOURCE_SIZE = 5242880
ORIGIN_ALLOWLIST = example.com, data.example.org
REQUIRE_TLS = true
STORAGE_DIR = /var/lib/datagate
```

| Setting | Value | Default |
| --- | --- | --- |
| `MAX_SOURCE_SIZE` | whole number of bytes | unset, so sources are unbounded |
| `ORIGIN_ALLOWLIST` | domain suffixes | unset, so every origin is accepted |
| `REQUIRE_TLS` | boolean | `false` |
| `STORAGE_DIR` | directory for stored datasets | `datagate-data` |
| `CACHE_ENABLED` | boolean | `true` |

Booleans accept `1`, `true`, `yes` or `on` and `0`, `false`, `no` or `off`, in any case
and with surrounding space ignored. A value outside those spellings, a size that is not
a whole number, a line naming no setting, and a config file that cannot be read all stop
the server from starting.

### Maximum source size

`/convert` and `/upload` reject a file larger than `MAX_SOURCE_SIZE` with HTTP 400; a
file of exactly that size is accepted.

### Origin allowlist

With `ORIGIN_ALLOWLIST` set, every request must carry a `Referer` whose hostname is one
of the listed domains or a subdomain of one -- `app.example.com` passes for
`example.com`, `notexample.com` does not -- and is otherwise answered with HTTP 403.
Matching ignores case. Without the setting, requests are served whatever their `Referer`.

### Endpoint URLs

`/convert` and `/upload` return the new dataset's endpoint as a path, or, under
`REQUIRE_TLS=true`, as the absolute `https://` URL of that path on the request's host.

### Storage

Datasets are written to `STORAGE_DIR`, which is created if it does not exist, one JSON
document per dataset. A server restarted on the same directory still serves everything
converted before it stopped.

## Caching

`/convert` reuses an already-converted source rather than downloading and parsing it
again. `CACHE_ENABLED` turns that off for the whole process.

A single request bypasses the cache with `force`, which re-ingests the source and
replaces the stored dataset. With caching disabled `force` changes nothing, since every
request already re-ingests. Re-ingestion reports its failures exactly as a first
conversion does, and a failed one leaves the dataset already stored queryable.

## Enrichment

`/convert` optionally records what it saw while ingesting a source, so that every query
of the dataset can report it. Enrichment is off unless the request carries exactly
`enrich=yes`; any other value, spelling or a repeated parameter leaves it off, and the
success body is the same either way.

An enriched CSV dataset reports two extra fields when queried:

| Field | Contents |
| --- | --- |
| `dataset_summary` | `filetype`, `row_count` and `column_count` |
| `column_details` | per column name: its `type`, `distinct_count` and `missing_count` |

A column's `type` is `integer` or `float` when every cell in it parsed as that number,
`number` when the column mixes the two, and `text` otherwise. A cell holding no text is
missing, and counts towards neither the type nor the distinct values.

An enriched spreadsheet dataset reports `dataset_summary` alone, with
`filetype: "excel"`: its cells keep the types the workbook recorded, which describes the
workbook rather than the data. A dataset ingested without enrichment reports neither
field at all.

Enrichment is a property of the stored dataset, so it interacts with the cache:

- `enrich=yes` over a cached dataset that has no metadata re-ingests the source and
  upgrades the stored dataset.
- `enrich=yes` over a cached dataset that already has metadata is answered from the
  cache, as any other repeated conversion is.
- A request answered from the cache changes nothing, so it neither adds metadata nor
  takes it away. A request that does re-ingest stores exactly what it asked for,
  recomputed from the source bytes as they are then.
- A failed ingestion reports its error as a first conversion does and leaves the stored
  dataset, metadata and all, untouched.

`enrich` is a `/convert` option: `/upload` stores no metadata, and the parameter is
ignored on the other endpoints.

## Endpoints

- `GET /convert?source=<url>[&charset=<encoding>][&force][&enrich=yes]` — fetches and
  parses the file, returning `{"ok": true, "endpoint": "/datasets/<id>"}`. The id is
  derived from the source URL, so the same URL always yields the same endpoint.

  Results are cached: a source converted before is answered straight from the store,
  with the same body a fresh parse would have returned, unless caching is disabled or
  the request carries `force`. `force` is a presence flag needing no value; giving it
  more than once is rejected with HTTP 400. See [Caching](#caching).

  `enrich=yes` asks for ingestion metadata, which is computed while the source is
  parsed and reported by `/datasets/<id>`. See [Enrichment](#enrichment).

  A source over `MAX_SOURCE_SIZE` is rejected with HTTP 400, and the endpoint is an
  absolute `https://` URL under `REQUIRE_TLS`. See [Configuration](#configuration).
- `POST /upload` — parses a file posted as multipart form data under a `file` or
  `attachment` field, returning the same `{"ok": true, "endpoint": "/datasets/<id>"}`
  body. The id is derived from the file's bytes, so re-uploading the same file always
  yields the same endpoint. A request that is not multipart form data is rejected with
  HTTP 415; one whose body is malformed or carries neither field, with HTTP 400; one
  whose file is over `MAX_SOURCE_SIZE`, also with HTTP 400.
- `GET /datasets/<id>` — returns the stored `columns`, the selected `rows`, the
  `total` row count before pagination, and `query_ms`. A dataset converted with
  `enrich=yes` also returns `dataset_summary` and, for a CSV, `column_details`; see
  [Enrichment](#enrichment).

  Control parameters, none of which may be repeated:

  | Parameter | Default | Meaning |
  | --- | --- | --- |
  | `_size=<n>` | `100` | positive integer; how many rows to return |
  | `_offset=<n>` | `0` | non-negative integer; how many rows to skip first |
  | `_sort=<column>` | — | sort ascending by `<column>` |
  | `_sort_desc=<column>` | — | sort descending by `<column>`; wins over `_sort` |
  | `_shape=lists\|objects` | `lists` | rows as arrays, or as objects with a `rowid` |
  | `_rowid=hide` | — | drop `rowid` from `objects` rows |
  | `_total=hide` | — | drop `total` from the response |

  Sorting is stable. `rowid` is the row's 1-based position in the source file and is
  not listed in `columns`.

  Any other parameter named `<column>__<comparator>` filters on a column, comparing its
  cells against the parameter's value:

  | Comparator | Match |
  | --- | --- |
  | `exact` | the cell's text equals the value, case-sensitively |
  | `contains` | the cell's text contains the value, case-sensitively |
  | `less` | the cell reads as a number strictly below the value |
  | `greater` | the cell reads as a number strictly above the value |

  Column names are matched exactly and case-sensitively, and several filters are ANDed,
  so `?age__greater=36&city__contains=new` keeps only rows satisfying both. A filter may
  not be repeated, `less` and `greater` need a numeric value, and a row whose stored cell
  is not numeric never matches them.

  A query filters, then sorts, then paginates, so `total` counts the filtered rows before
  pagination. A query that exceeds its time budget is rejected.

  Parameters that neither begin with `_` nor contain `__` are ignored.

- `GET /datasets/<id>/export` — the same rows as `/datasets/<id>`, as a CSV attachment
  named `<id>.csv` and served as `text/csv`. Filters, `_sort`/`_sort_desc`, `_size` and
  `_offset` apply exactly as above; `_shape`, `_rowid` and `_total` have nothing to act
  on in a CSV and are ignored. Columns are written in source order.

Errors are JSON: `{"ok": false, "error": "<message>"}`.

## Accepted formats

A source may be a CSV (or other delimited text), an `.xls` workbook or an `.xlsx`
workbook; the format is recognised from the file's own bytes rather than its name, and
anything else is rejected with HTTP 400.

For delimited text the delimiter (`,`, `;` or tab) and, when `charset` is omitted, the
encoding are inferred from content. `charset` applies to text sources only, since a
workbook carries its own encoding.

For a workbook only the first worksheet is read, and it must be tabular — a header row
plus at least one data row — or the request fails with HTTP 400. Worksheet cells keep
their stored type, with dates written as ISO-8601 text and whole numbers as integers.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

## Layout

| Path | Purpose |
| --- | --- |
| `datagate.py` | CLI entry point |
| `datagate/app.py` | routes, response envelope, CORS, endpoint URLs |
| `datagate/fetching.py` | URL validation and download |
| `datagate/uploads.py` | reading the posted file out of a multipart request |
| `datagate/parsing.py` | format dispatch, decoding and delimiter inference |
| `datagate/spreadsheets.py` | `.xls` and `.xlsx` worksheet readers |
| `datagate/tables.py` | the table every format is parsed into |
| `datagate/enrichment.py` | the `enrich=yes` flag and the metadata it computes |
| `datagate/export.py` | rendering selected rows back out as CSV |
| `datagate/query.py` | pagination, sorting and response shape controls |
| `datagate/filtering.py` | column filters and the comparators they apply |
| `datagate/timing.py` | the time budget bounding one query |
| `datagate/values.py` | cell type inference |
| `datagate/store.py` | dataset ids and their storage on disk |
| `datagate/config.py` | defaults, the `DATAGATE_CONFIG` file and the environment |
| `datagate/policy.py` | the origin allowlist and the maximum source size |
| `datagate/caching.py` | the `force` cache bypass |
| `datagate/errors.py` | error type carrying an HTTP status |
