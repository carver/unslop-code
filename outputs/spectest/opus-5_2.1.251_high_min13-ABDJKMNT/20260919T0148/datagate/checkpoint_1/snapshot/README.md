# datagate

A small HTTP gateway that converts remote CSV files into queryable JSON datasets.

## Run

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

## Endpoints

- `GET /convert?source=<url>[&charset=<codec>]` → `{"ok": true, "endpoint": "/datasets/<id>"}`
- `GET /datasets/<id>[?limit=N]` → `{"ok": true, "columns": [...], "rows": [...], "query_ms": 1.2}`

Errors are always JSON: `{"ok": false, "error": "<message>"}`.

## Layout

| Path | Responsibility |
| --- | --- |
| `datagate.py` | CLI entry point (`start`, `--port`, `--address`) |
| `datagate_core/server.py` | Routes, JSON envelope, CORS headers |
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
