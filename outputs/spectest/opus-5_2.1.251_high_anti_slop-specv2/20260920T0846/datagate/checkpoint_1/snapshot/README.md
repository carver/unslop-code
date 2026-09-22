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
| `GET /datasets/<id>` | `limit` (optional, default 100) | `{"ok": true, "columns": [...], "rows": [...], "query_ms": 3.2}` |

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
| `store.py` | dataset records and id derivation |
| `test_datagate.py` | pytest suite (`.venv/bin/python -m pytest`) |
