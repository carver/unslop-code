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
| `GET /datasets/<id>` | Return `columns`, up to 100 `rows` and `query_ms` |

The dataset id is a hash of the source URL, so converting the same URL twice
yields the same endpoint. Failures answer `{"ok": false, "error": "..."}`:
400 for a bad request (missing or invalid `source`, unusable `charset`,
non-tabular content) and 404 for an unreachable source or an unknown id.

## Layout

| File | Responsibility |
| --- | --- |
| `datagate.py` | CLI entry point |
| `gateway/app.py` | Routes, CORS headers, error rendering |
| `gateway/fetching.py` | Source URL validation and download |
| `gateway/parsing.py` | Decoding, delimiter inference, CSV parsing |
| `gateway/values.py` | Cell-to-JSON type inference |
| `gateway/store.py` | Dataset records and their deterministic ids |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```
