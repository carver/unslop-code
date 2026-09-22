# datagate

Converts remote CSV files into queryable JSON datasets.

## Setup

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

## Endpoints

| Route | Parameters | Result |
| --- | --- | --- |
| `GET /convert` | `source` (required URL), `charset` (optional) | `{"ok": true, "endpoint": "/datasets/<id>"}` |
| `GET /datasets/<id>` | the controls below (all optional) | `{"ok": true, "columns": [...], "rows": [...], "total": 42, "query_ms": 3.2}` |

### Dataset controls

| Parameter | Values | Effect |
| --- | --- | --- |
| `_size` | positive integer, default 100 | how many rows to return; a size past the end returns the rest |
| `_offset` | non-negative integer, default 0 | how many rows to skip first |
| `_sort` | column name | sort ascending by that column |
| `_sort_desc` | column name | sort descending; outranks `_sort` when both are given |
| `_shape` | `lists` (default) or `objects` | rows as value arrays, or as column-keyed objects |
| `_rowid` | `hide` | drop `rowid` from object rows |
| `_total` | `hide` | drop `total` from the response |

Sorting is stable and runs before pagination, `total` counts the rows before
it, and `rowid` is the row's 1-based line in the source file, counting the
header as line one. Repeating any control, or giving it a value outside the
table above, is a 400.

Errors are JSON: `{"ok": false, "error": "..."}` — 400 for bad requests or
non-tabular content, 404 for unreachable sources and unknown datasets/routes.
All responses carry permissive CORS headers.

## Behaviour

- The dataset id is a hash of the source URL, so a source always maps to the
  same endpoint and re-converting refreshes its rows in place.
- Without an explicit `charset`, a BOM or a clean UTF-8 decode decides the
  encoding; otherwise the bytes are read as latin-1.
- The delimiter (`,`, `;`, tab or `|`) is inferred by picking the one that
  splits the file into the widest consistent table.
- Integers and decimals become JSON numbers; times such as `08:30` and every
  other value stay text.

## Layout

| File | Responsibility |
| --- | --- |
| `datagate.py` | CLI entry point |
| `app.py` | routes, error envelope, CORS |
| `fetcher.py` | source URL validation and download |
| `tabular.py` | decoding, delimiter detection, type inference |
| `query.py` | dataset query controls: paging, sorting, response shape |
| `store.py` | dataset records and id derivation |
| `test_datagate.py` | pytest suite (`.venv/bin/python -m pytest`) |
