# datagate

Serves remote and uploaded CSV, `.xls` and `.xlsx` files as queryable JSON
datasets, and exports any query back out as CSV.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

- `GET /convert?source=<url>[&charset=<encoding>][&force]` ingests a remote file
  and returns `{"ok": true, "endpoint": "/datasets/<id>"}`. The id is derived
  from the source URL, so the same URL always yields the same endpoint.
- `POST /upload[?charset=<encoding>]` ingests a multipart upload from the field
  `file` or `attachment` and answers with the same envelope. Its id is derived
  from the file bytes, so re-uploading a file re-uses its endpoint.
- `GET /datasets/<id>` returns the stored `columns`, a page of `rows`, the
  pre-pagination `total` and `query_ms`.
- `GET /datasets/<id>/export` returns the same rows as a `text/csv` attachment
  named `<id>.csv`, led by a header row of the source column names. It takes the
  same filters, sort and pagination; `_shape`, `_rowid` and `_total` are still
  validated but cannot change the bytes.

### Formats

CSV, `.xls` and `.xlsx` are accepted on both ingest routes, and the format is
recognised from the payload's own bytes rather than from a filename. Only the
first worksheet of a workbook is read, and it has to be tabular -- a header row
plus at least one data row -- or the request is `HTTP 400`; so is a payload in
any other format. `charset` applies, and is validated, only for text CSV.

A non-multipart `POST /upload` is `HTTP 415`; a malformed multipart body, or one
carrying neither `file` nor `attachment`, is `HTTP 400`.

### Caching

`/convert` caches: once a source URL has been ingested, repeating it answers
from the stored dataset -- the same response, without downloading again.

`CACHE_ENABLED` turns that off for the process. It accepts `1`, `true`, `yes`,
`on` and `0`, `false`, `no`, `off`, case-insensitively and nothing else; an
unrecognised value stops the server before it binds its port. With caching off,
every `/convert` re-downloads, re-parses and replaces what was stored.

`force` bypasses the cache for one request: `/convert?source=<url>&force` always
re-ingests and replaces the cached dataset. It is a presence flag, so giving it
a value, or repeating it, is `HTTP 400`. A re-ingestion that fails reports the
usual error and status, and leaves the previous dataset queryable.

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
| `datagate_app/ingestion.py` | Ingest pipeline: detect format → decode → build table |
| `datagate_app/formats.py` | Format recognition from the payload's signature |
| `datagate_app/fetching.py` | URL validation and remote download |
| `datagate_app/uploads.py` | Reading the file part out of a multipart upload |
| `datagate_app/decoding.py` | Charset handling and encoding detection |
| `datagate_app/spreadsheets.py` | First-worksheet reading for `.xls` and `.xlsx` |
| `datagate_app/parsing.py` | Delimiter inference, tabular checks, row building |
| `datagate_app/controls.py` | Validation of the `/datasets/<id>` control parameters |
| `datagate_app/filtering.py` | Filter parsing, comparators and the query budget |
| `datagate_app/results.py` | Sorting, pagination and row shaping |
| `datagate_app/exporting.py` | Writing a query's rows back out as CSV |
| `datagate_app/values.py` | Per-cell int/decimal/text inference |
| `datagate_app/store.py` | Dataset ids and in-memory storage |
| `datagate_app/caching.py` | `CACHE_ENABLED` startup setting and the `force` flag |

Interpretation decisions are recorded in `AMBIGUITIES.md`; tests live in
`tests/` and are annotated with the spec phrase each one covers.
