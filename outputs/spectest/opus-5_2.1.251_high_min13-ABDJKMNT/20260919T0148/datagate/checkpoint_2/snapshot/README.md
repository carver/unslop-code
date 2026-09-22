# datagate

A small HTTP gateway that converts remote CSV files into queryable JSON datasets.

## Run

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

## Endpoints

- `GET /convert?source=<url>[&charset=<codec>]` → `{"ok": true, "endpoint": "/datasets/<id>"}`
- `GET /datasets/<id>` → `{"ok": true, "columns": [...], "rows": [...], "total": 42, "query_ms": 1.2}`

Errors are always JSON: `{"ok": false, "error": "<message>"}`.

### Dataset control parameters

| Parameter | Values | Effect |
| --- | --- | --- |
| `_size` | positive integer (default `100`) | Rows per response. |
| `_offset` | non-negative integer (default `0`) | Rows skipped first. |
| `_sort` | column name | Sort ascending. |
| `_sort_desc` | column name | Sort descending; wins over `_sort`. |
| `_shape` | `lists` (default) or `objects` | Rows as arrays, or as objects carrying `rowid`. |
| `_rowid` | `hide` | Drop `rowid` from object rows. |
| `_total` | `hide` | Drop `total` from the response. |

Sorting is stable and happens before pagination. An invalid value, an unknown
sort column, or any repeated control parameter is `HTTP 400`.

## Layout

| Path | Responsibility |
| --- | --- |
| `datagate.py` | CLI entry point (`start`, `--port`, `--address`) |
| `datagate_core/server.py` | Routes, JSON envelope, CORS headers |
| `datagate_core/controls.py` | Validation of the `_size`/`_sort`/`_shape` family |
| `datagate_core/projection.py` | Sorting, pagination and row rendering |
| `datagate_core/conversion.py` | Ingestion pipeline: fetch → decode → parse → store |
| `datagate_core/fetching.py` | Source URL validation and retrieval |
| `datagate_core/decoding.py` | Charset handling and encoding detection |
| `datagate_core/parsing.py` | Delimiter inference and table extraction |
| `datagate_core/inference.py` | Cell typing (numbers vs. text) |
| `datagate_core/store.py` | Dataset ids and the in-memory store |

`AMBIGUITIES.md` records the spec readings this implementation chose.

## Tests

```
.venv/bin/python -m pytest
```
