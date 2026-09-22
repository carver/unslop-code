# datagate

A small HTTP service that ingests remote CSV files and serves them back as JSON.

## Running

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

`--port` defaults to `8001` and `--address` to `127.0.0.1`.

## Endpoints

### `GET /convert?source=<url>[&charset=<encoding>]`

Downloads the CSV at `source`, parses it, and returns the endpoint it is served from:

```json
{"ok": true, "endpoint": "/datasets/0daefea780c7d65a"}
```

The id is a hash of the `source` URL string, so the same URL always maps to the same endpoint.
`charset` is optional; without it the encoding is detected from the content.

| Condition | Status |
| --- | --- |
| Missing `source`, invalid URL, bad `charset`, non-tabular content | 400 |
| Source unreachable or remote HTTP error | 404 |

### `GET /datasets/<id>`

```json
{"ok": true, "columns": ["name", "age"], "rows": [["Ada", 36]], "query_ms": 0.014}
```

Columns and rows keep their source order, and at most 100 rows are returned. Unknown ids give 404.

Cells become JSON numbers when they are unambiguously an integer or a decimal; everything else —
including time-like values such as `08:30` — stays text.

Every response carries `ok`, errors use `{"ok": false, "error": "..."}`, and all responses
(including errors) carry permissive CORS headers for browser clients.

## Layout

| File | Responsibility |
| --- | --- |
| `datagate.py` | Command line entry point |
| `app.py` | Routes, CORS, JSON error envelope |
| `fetching.py` | Source URL validation and download |
| `csv_parsing.py` | Decoding, delimiter inference, type inference |
| `store.py` | Dataset records and their URL-derived ids |
| `errors.py` | Error type carrying an HTTP status |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

The suite serves CSV fixtures over a real loopback HTTP server and drives the app end to end.
