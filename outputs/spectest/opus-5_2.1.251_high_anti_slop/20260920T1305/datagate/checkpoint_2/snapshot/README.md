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

  Sorting is stable and happens before pagination. `rowid` is the row's 1-based
  position in the source file and is not listed in `columns`.

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
| `datagate/values.py` | cell type inference |
| `datagate/store.py` | dataset ids and in-memory storage |
| `datagate/errors.py` | error type carrying an HTTP status |
