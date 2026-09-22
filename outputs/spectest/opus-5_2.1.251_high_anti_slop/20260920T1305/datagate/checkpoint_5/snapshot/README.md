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

## Caching

`/convert` reuses an already-converted source rather than downloading and parsing it
again. `CACHE_ENABLED` turns that off for the whole process, and accepts only these
values, in any case:

| Value | Meaning |
| --- | --- |
| `1`, `true`, `yes`, `on` | cache conversions (the default when unset) |
| `0`, `false`, `no`, `off` | re-download and re-parse on every request |

Any other value, including an empty one, stops the server from starting.

A single request bypasses the cache with `force`, which re-ingests the source and
replaces the stored dataset. With caching disabled `force` changes nothing, since every
request already re-ingests. Re-ingestion reports its failures exactly as a first
conversion does, and a failed one leaves the dataset already stored queryable.

## Endpoints

- `GET /convert?source=<url>[&charset=<encoding>][&force]` — fetches and parses the
  file, returning `{"ok": true, "endpoint": "/datasets/<id>"}`. The id is derived from
  the source URL, so the same URL always yields the same endpoint.

  Results are cached: a source converted before is answered straight from the store,
  with the same body a fresh parse would have returned, unless caching is disabled or
  the request carries `force`. `force` is a presence flag needing no value; giving it
  more than once is rejected with HTTP 400. See [Caching](#caching).
- `POST /upload` — parses a file posted as multipart form data under a `file` or
  `attachment` field, returning the same `{"ok": true, "endpoint": "/datasets/<id>"}`
  body. The id is derived from the file's bytes, so re-uploading the same file always
  yields the same endpoint. A request that is not multipart form data is rejected with
  HTTP 415; one whose body is malformed or carries neither field, with HTTP 400.
- `GET /datasets/<id>` — returns the stored `columns`, the selected `rows`, the
  `total` row count before pagination, and `query_ms`.

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
| `datagate/app.py` | routes, response envelope, CORS |
| `datagate/fetching.py` | URL validation and download |
| `datagate/uploads.py` | reading the posted file out of a multipart request |
| `datagate/parsing.py` | format dispatch, decoding and delimiter inference |
| `datagate/spreadsheets.py` | `.xls` and `.xlsx` worksheet readers |
| `datagate/tables.py` | the `(columns, rows)` table every format is parsed into |
| `datagate/export.py` | rendering selected rows back out as CSV |
| `datagate/query.py` | pagination, sorting and response shape controls |
| `datagate/filtering.py` | column filters and the comparators they apply |
| `datagate/timing.py` | the time budget bounding one query |
| `datagate/values.py` | cell type inference |
| `datagate/store.py` | dataset ids and in-memory storage |
| `datagate/caching.py` | the `CACHE_ENABLED` setting and the `force` bypass |
| `datagate/errors.py` | error type carrying an HTTP status |
