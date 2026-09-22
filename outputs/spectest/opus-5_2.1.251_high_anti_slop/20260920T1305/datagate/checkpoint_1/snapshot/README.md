# datagate

Converts remote CSV files into JSON datasets served over HTTP.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

## Endpoints

- `GET /convert?source=<url>[&charset=<encoding>]` — fetches and parses the CSV,
  returning `{"ok": true, "endpoint": "/datasets/<id>"}`. The id is derived from the
  source URL, so the same URL always yields the same endpoint. The delimiter (`,`,
  `;` or tab) and, when `charset` is omitted, the encoding are inferred from content.
- `GET /datasets/<id>[?limit=<n>]` — returns the stored `columns` and `rows` in source
  order plus `query_ms`; at most 100 rows unless `limit` says otherwise.

Errors are JSON: `{"ok": false, "error": "<message>"}`.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

## Layout

| Path | Purpose |
| --- | --- |
| `datagate.py` | CLI entry point |
| `datagate/app.py` | routes, response envelope, CORS |
| `datagate/fetching.py` | URL validation and download |
| `datagate/parsing.py` | decoding, delimiter inference, table building |
| `datagate/values.py` | cell type inference |
| `datagate/store.py` | dataset ids and in-memory storage |
| `datagate/errors.py` | error type carrying an HTTP status |
