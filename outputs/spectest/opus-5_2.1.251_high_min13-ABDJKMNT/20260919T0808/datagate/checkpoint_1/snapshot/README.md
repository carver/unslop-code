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
- `GET /datasets/<id>[?limit=<n>]` -> `{"ok": true, "columns": [...], "rows": [...], "query_ms": 0.1}`

Errors are JSON: `{"ok": false, "error": "<message>"}`.

## Layout

| Path | Purpose |
| --- | --- |
| `datagate.py` | CLI entry point |
| `datagate_core/server.py` | Routes, JSON envelope, CORS |
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
