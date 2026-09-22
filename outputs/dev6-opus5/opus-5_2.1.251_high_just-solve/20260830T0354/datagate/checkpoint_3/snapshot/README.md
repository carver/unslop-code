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

Errors are always JSON: `{"ok": false, "error": "..."}`. CORS headers are sent on every response.

## Tests

```
./venv/bin/python tests/run_tests.py
```
