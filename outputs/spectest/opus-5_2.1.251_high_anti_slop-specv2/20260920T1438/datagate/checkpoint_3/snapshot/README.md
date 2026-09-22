# datagate

Fetches remote CSV files and serves them back as JSON datasets.

## Run

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

`--port` defaults to `8001`, `--address` to `127.0.0.1`.

## Endpoints

| Route | Purpose |
| --- | --- |
| `GET /convert?source=<url>[&charset=<name>]` | Ingest a remote CSV; answers `{"ok": true, "endpoint": "/datasets/<id>"}` |
| `GET /datasets/<id>` | Return `columns`, `rows`, `total` and `query_ms` |

The dataset id is a hash of the source URL, so converting the same URL twice
yields the same endpoint. Failures answer `{"ok": false, "error": "..."}`:
400 for a bad request (missing or invalid `source`, unusable `charset`,
non-tabular content, an unusable control parameter) and 404 for an unreachable
source or an unknown id.

## Control parameters

`GET /datasets/<id>` accepts these, each at most once; repeating one is a 400.

| Parameter | Effect |
| --- | --- |
| `_size=<n>` | Return at most `n` rows, `n > 0`; defaults to 100 |
| `_offset=<n>` | Skip the first `n` rows, `n >= 0`; defaults to 0 |
| `_sort=<column>` | Sort ascending by `column` |
| `_sort_desc=<column>` | Sort descending by `column`; wins when `_sort` is also given |
| `_shape=lists` | Rows are arrays of values; the default |
| `_shape=objects` | Rows are objects keyed by column name, led by `rowid` |
| `_rowid=hide` | Leave `rowid` out of the rows |
| `_total=hide` | Leave `total` out of the response |

`total` counts the rows left by the filters, before pagination. Sorting is
stable -- rows that compare equal stay in source order -- and runs before
pagination, so `_size` and `_offset` cut into the filtered, sorted table. A `rowid` is
the row's 1-based line number in the source file, counting the header as line
1, and it stays with its row through sorting and pagination; it is not one of
the `columns`.

## Filters

`GET /datasets/<id>` also accepts column filters, written as
`<column>__<comparator>=<value>`; `GET /datasets/<id>?name__contains=ad` keeps
the rows whose `name` holds `ad`.

| Comparator | Keeps a row when its cell |
| --- | --- |
| `exact` | equals the value, as text, case-sensitively |
| `contains` | holds the value as a substring, case-sensitively |
| `less` | reads as a number strictly below the value |
| `greater` | reads as a number strictly above the value |

Column names are matched exactly and case-sensitively, and a column whose own
name contains `__` stays addressable: the comparator is the part after the
last `__`. Several filters are combined with AND, and each may be given only
once. Filtering runs first, so sorting and pagination see only the rows that
were kept.

`less` and `greater` need a numeric value; anything else is a 400. They read
the stored cell as a number too, so cells holding text -- a clock time such as
`08:30`, say -- match neither of them.

Filters are told apart from control parameters by the leading `_`, and from
everything else by the `__`: a parameter with neither, such as `name=ada`, is
ignored. An unknown column, an unknown comparator, a repeated filter, a
non-numeric value for `less` or `greater`, and a query that outlives its time
budget are all answered with a 400.

## Layout

| File | Responsibility |
| --- | --- |
| `datagate.py` | CLI entry point |
| `gateway/app.py` | Routes, CORS headers, error rendering |
| `gateway/fetching.py` | Source URL validation and download |
| `gateway/parsing.py` | Decoding, delimiter inference, CSV parsing |
| `gateway/query.py` | Control parameters of a dataset request |
| `gateway/filters.py` | Column filters: parsing and row matching |
| `gateway/results.py` | Filtering, sorting, pagination and row shaping |
| `gateway/values.py` | Cell-to-JSON type inference |
| `gateway/store.py` | Dataset records and their deterministic ids |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```
