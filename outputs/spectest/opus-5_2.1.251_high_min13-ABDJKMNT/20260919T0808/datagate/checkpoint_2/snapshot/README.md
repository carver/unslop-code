# datagate

An HTTP gateway that fetches a remote CSV file, converts it to JSON, and serves
it under a stable dataset endpoint.

## Run

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

`--port` defaults to `8001`, `--address` to `127.0.0.1`.

## Endpoints

- `GET /convert?source=<url>[&charset=<encoding>]` -> `{"ok": true, "endpoint": "/datasets/<id>"}`
- `GET /datasets/<id>` -> `{"ok": true, "columns": [...], "rows": [...], "total": 2, "query_ms": 0.1}`

Errors are JSON: `{"ok": false, "error": "<message>"}`.

### Dataset controls

| Parameter | Default | Meaning |
| --- | --- | --- |
| `_size` | `100` | Positive integer; rows per page (`limit` is a deprecated alias) |
| `_offset` | `0` | Non-negative integer; rows to skip before the page |
| `_sort` | - | Sort ascending by the named column |
| `_sort_desc` | - | Sort descending; wins if `_sort` is also present |
| `_shape` | `lists` | `lists` for row arrays, `objects` for row objects with `rowid` |
| `_rowid` | - | `hide` drops `rowid` from `objects` rows |
| `_total` | - | `hide` drops `total` from the response |

Sorting is stable and runs before pagination; `total` always counts every stored
row. An invalid value, an unknown sort column, or any repeated control parameter
is `HTTP 400`.

## Layout

| Path | Purpose |
| --- | --- |
| `datagate.py` | CLI entry point |
| `datagate_core/server.py` | Routes, JSON envelope, CORS |
| `datagate_core/controls.py` | Dataset control parameters and their validation |
| `datagate_core/views.py` | Sorting, pagination and response shaping |
| `datagate_core/fetching.py` | URL validation and retrieval |
| `datagate_core/decoding.py` | Charset handling and detection |
| `datagate_core/tables.py` | Delimiter inference and CSV parsing |
| `datagate_core/values.py` | Cell type inference |
| `datagate_core/store.py` | Dataset ids and in-process storage |
| `AMBIGUITIES.md` | Spec readings chosen where the spec is open |

## Tests

```bash
.venv/bin/python -m pytest
```
