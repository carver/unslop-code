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
- `GET /datasets/<id>` -> `{"ok": true, "columns": [...], "rows": [...], "query_ms": 1.2}`
  - at most 100 rows (optional `limit`/`offset` query params); 404 for an unknown id

Errors are always JSON: `{"ok": false, "error": "..."}`. CORS headers are sent on every response.

## Tests

```
./venv/bin/python tests/run_tests.py
```
