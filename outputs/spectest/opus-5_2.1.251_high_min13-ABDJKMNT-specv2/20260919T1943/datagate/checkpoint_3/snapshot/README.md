# datagate

Serves remote CSV files as queryable JSON datasets.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

- `GET /convert?source=<url>[&charset=<encoding>]` ingests a remote CSV and
  returns `{"ok": true, "endpoint": "/datasets/<id>"}`. The id is derived from
  the source URL, so the same URL always yields the same endpoint.
- `GET /datasets/<id>` returns the stored `columns`, a page of `rows`, the
  pre-pagination `total` and `query_ms`.

### Control parameters

| Parameter | Meaning |
| --- | --- |
| `_size` | Rows per page, a positive integer (default `100`) |
| `_offset` | Rows to skip, a non-negative integer (default `0`) |
| `_sort` / `_sort_desc` | Stable sort by column, ascending / descending (`_sort_desc` wins) |
| `_shape` | `lists` (default) for array rows, `objects` for keyed rows with `rowid` |
| `_rowid=hide` / `_total=hide` | Drop `rowid` from object rows / drop `total` |

Sorting runs before pagination. An unusable value, an unknown sort column or a
repeated control parameter is `HTTP 400`.

### Filters

Any other parameter shaped `<column>__<comparator>=<value>` filters the rows:

| Comparator | Match |
| --- | --- |
| `exact` | case-sensitive equality with the cell |
| `contains` | case-sensitive substring of the cell |
| `less` / `greater` | strict numeric comparison; non-numeric cells never match |

Filters are ANDed and run before sorting, so pagination pages the filtered and
sorted rows and `total` counts everything that matched. An unknown column, an
unknown comparator, a repeated filter key, a non-numeric value for `less` or
`greater` and a query that exceeds its time budget are all `HTTP 400`.
Parameters with neither a leading `_` nor a `__` are ignored.

## Layout

| File | Responsibility |
| --- | --- |
| `datagate.py` | CLI entry point (`start` command, port/address defaults) |
| `datagate_app/server.py` | Routes, JSON error envelope, CORS headers |
| `datagate_app/ingestion.py` | `/convert` pipeline: fetch → decode → parse |
| `datagate_app/fetching.py` | URL validation and remote download |
| `datagate_app/decoding.py` | Charset handling and encoding detection |
| `datagate_app/parsing.py` | Delimiter inference, tabular checks, row building |
| `datagate_app/controls.py` | Validation of the `/datasets/<id>` control parameters |
| `datagate_app/filtering.py` | Filter parsing, comparators and the query budget |
| `datagate_app/results.py` | Sorting, pagination and row shaping |
| `datagate_app/values.py` | Per-cell int/decimal/text inference |
| `datagate_app/store.py` | Dataset ids and in-memory storage |

Interpretation decisions are recorded in `AMBIGUITIES.md`; tests live in
`tests/` and are annotated with the spec phrase each one covers.
