# datagate

Serves remote CSV files as queryable JSON datasets.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

- `GET /convert?source=<url>[&charset=<encoding>]` ingests a remote CSV and
  returns `{"ok": true, "endpoint": "/datasets/<id>"}`. The id is derived from
  the source URL, so the same URL always yields the same endpoint.
- `GET /datasets/<id>` returns the stored `columns` and up to 100 `rows`
  (`?limit=` overrides the page size) plus `query_ms`.

## Layout

| File | Responsibility |
| --- | --- |
| `datagate.py` | CLI entry point (`start` command, port/address defaults) |
| `datagate_app/server.py` | Routes, JSON error envelope, CORS headers |
| `datagate_app/ingestion.py` | `/convert` pipeline: fetch → decode → parse |
| `datagate_app/fetching.py` | URL validation and remote download |
| `datagate_app/decoding.py` | Charset handling and encoding detection |
| `datagate_app/parsing.py` | Delimiter inference, tabular checks, row building |
| `datagate_app/values.py` | Per-cell int/decimal/text inference |
| `datagate_app/store.py` | Dataset ids and in-memory storage |

Interpretation decisions are recorded in `AMBIGUITIES.md`; tests live in
`tests/` and are annotated with the spec phrase each one covers.
