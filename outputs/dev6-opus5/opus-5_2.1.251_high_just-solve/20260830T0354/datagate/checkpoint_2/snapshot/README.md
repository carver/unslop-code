# datagate

Fetches a remote CSV, infers its delimiter and encoding, and serves it as JSON.

## Setup

```
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## Run

```
./venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

`--port` defaults to `8001`, `--address` to `127.0.0.1`.

## Endpoints

- `GET /convert?source=<url>[&charset=<charset>]` -> `{"ok": true, "endpoint": "/datasets/<id>"}`
  - 400: missing `source`, invalid URL, unsupported/malformed `charset`, non-tabular content
  - 404: source unreachable or remote HTTP error
- `GET /datasets/<id>` -> `{"ok": true, "columns": [...], "rows": [...], "total": 250, "query_ms": 1.2}`
  - `total` is the row count *before* pagination; 404 for an unknown id

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

Sorting is stable and applied before pagination. `rowid` is the 1-based row
number in the source file, so it survives sorting and is never listed in
`columns`. The legacy `limit`/`offset` spellings still work when `_size`/
`_offset` are absent.

A control parameter given more than once is a `400`, as is a non-positive or
non-integer `_size`, a negative or non-integer `_offset`, a `_shape` other than
`lists`/`objects`, a `_rowid`/`_total` value other than `hide`, and an empty or
unknown `_sort`/`_sort_desc` column.

Errors are always JSON: `{"ok": false, "error": "..."}`. CORS headers are sent on every response.

## Tests

```
./venv/bin/python tests/run_tests.py
```
