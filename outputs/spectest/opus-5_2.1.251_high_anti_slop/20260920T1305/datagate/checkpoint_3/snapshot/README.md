# datagate

Converts remote CSV files into JSON datasets served over HTTP.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

## Endpoints

- `GET /convert?source=<url>[&charset=<encoding>]` — fetches and parses the CSV,
  returning `{"ok": true, "endpoint": "/datasets/<id>"}`. The id is derived from the
  source URL, so the same URL always yields the same endpoint. The delimiter (`,`,
  `;` or tab) and, when `charset` is omitted, the encoding are inferred from content.
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

Errors are JSON: `{"ok": false, "error": "<message>"}`.

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
| `datagate/parsing.py` | decoding, delimiter inference, table building |
| `datagate/query.py` | pagination, sorting and response shape controls |
| `datagate/filtering.py` | column filters and the comparators they apply |
| `datagate/timing.py` | the time budget bounding one query |
| `datagate/values.py` | cell type inference |
| `datagate/store.py` | dataset ids and in-memory storage |
| `datagate/errors.py` | error type carrying an HTTP status |
