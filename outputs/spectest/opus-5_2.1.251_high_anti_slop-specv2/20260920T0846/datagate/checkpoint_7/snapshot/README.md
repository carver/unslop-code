# datagate

Converts remote and uploaded tables — CSV, `.xls`, `.xlsx` — into queryable
JSON datasets, and exports them back out as CSV.

## Setup

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

## Configuration

Settings are read once at startup from three sources, each overriding the one
before it: the built-in defaults, the file `DATAGATE_CONFIG` names, and the
environment variables themselves.

| Setting | Value | Default |
| --- | --- | --- |
| `MAX_SOURCE_SIZE` | whole number of bytes | unset: sources may be any size |
| `ORIGIN_ALLOWLIST` | comma separated domain suffixes | unset: every origin passes |
| `REQUIRE_TLS` | boolean | `false` |
| `STORAGE_DIR` | directory datasets are kept in | a `datagate-datasets` directory under the system temporary directory |
| `CACHE_ENABLED` | boolean | `true` |

A config file holds one `KEY=VALUE` setting per line, with commas separating
the entries of a list; blank lines and `#` comments are ignored, and
whitespace around a key or a value is not part of it:

```
# /etc/datagate.conf
MAX_SOURCE_SIZE = 5242880
ORIGIN_ALLOWLIST = example.com, reports.internal
REQUIRE_TLS = true
```

Booleans accept `1`, `true`, `yes` or `on` and `0`, `false`, `no` or `off`, in
any capitalisation and with surrounding whitespace. Any other value, a config
file line that is not a setting, and a `DATAGATE_CONFIG` that cannot be read
are all configuration mistakes rather than requests that can be answered, so
they stop the server from starting.

### Source size

`MAX_SOURCE_SIZE` caps what `/convert` and `/upload` will ingest. A source of
exactly the limit is accepted and a larger one is a 400, leaving any dataset
converted earlier from that source untouched.

### Allowed origins

With `ORIGIN_ALLOWLIST` set, every request — whatever route it names — has to
carry a `Referer` whose hostname is, or sits under, one of the listed
suffixes; anything else is a 403. Matching ignores capitalisation and stops at
a domain boundary, so `example.com` covers `example.com` and
`eu.example.com` but not `notexample.com`.

### Endpoint URLs

`/convert` and `/upload` answer with a relative `/datasets/<id>` endpoint. Under
`REQUIRE_TLS` they answer with the absolute `https://` URL of that endpoint on
the host the request named.

### Storage

Datasets are written to `STORAGE_DIR`, which is created if it does not exist,
one JSON record per dataset. A server started over a directory an earlier run
used serves the datasets of that run, cache included.

## Endpoints

| Route | Parameters | Result |
| --- | --- | --- |
| `GET /convert` | `source` (required URL), `charset` (optional), `force` (optional flag), `enrich` (optional) | `{"ok": true, "endpoint": "/datasets/<id>"}` |
| `POST /upload` | multipart field `file` or `attachment`, `charset` (optional) | `{"ok": true, "endpoint": "/datasets/<id>"}` |
| `GET /datasets/<id>` | the controls and filters below (all optional) | `{"ok": true, "columns": [...], "rows": [...], "total": 42, "query_ms": 3.2}`, plus the enrichment fields when the dataset carries them |
| `GET /datasets/<id>/export` | the same controls and filters | the rows as a `text/csv` attachment named `<id>.csv` |

An upload must be a `multipart/form-data` request — anything else is a 415 —
carrying the file under either accepted field name; a body that carries neither,
or that is malformed enough to parse to nothing, is a 400.

`/export` writes the source columns, in source order, above the rows the
dataset route would have returned: filters, sorting and pagination all apply.
`_shape`, `_rowid` and `_total` describe a JSON body, so a CSV file ignores
them.

### Caching

A conversion is cached: asking for a source that has already been converted
returns its endpoint straight away, with the same body a fresh parse would
have produced and without downloading the source again. `force` re-downloads
and re-parses the source, replacing the stored rows; it is a presence flag, so
`?source=...&force` forces a re-read while giving it a value, as in `force=1`
or `force=`, is a 400, as is repeating it.

With `CACHE_ENABLED` off, every conversion re-downloads and replaces the stored
rows, and `force` changes nothing beyond still being validated. A re-ingestion
that fails reports the error it would have reported on a first conversion, and
leaves the previously stored dataset queryable.

### Enrichment

`/convert` describes what it ingests when the request carries exactly one
`enrich=yes`; every other spelling — `enrich=YES`, `enrich=no`, a bare
`enrich`, the parameter twice — is not that request and leaves enrichment off
rather than failing. The conversion answers with its usual endpoint either
way, and `enrich` means nothing on `/upload` or on the dataset routes.

A dataset converted with enrichment reports two more fields, alongside
unchanged `ok`, `columns`, `rows`, `total` and `query_ms`; one converted
without it reports neither field at all:

```json
{
  "dataset_summary": {"filetype": "csv", "row_count": 3, "column_count": 2},
  "column_details": {
    "name": {"type": "text", "distinct_count": 3, "missing_count": 0},
    "score": {"type": "integer", "distinct_count": 2, "missing_count": 1}
  }
}
```

A column is `integer` or `float` when every value it holds is one, `number`
when it holds both and `text` otherwise; blank cells are its missing values,
and count towards neither its type nor its distinct values. A workbook is
summarised as `filetype: "excel"` and is not profiled column by column, so an
enriched spreadsheet dataset carries `dataset_summary` alone.

Enrichment reads the ingested table, so `enrich=yes` over a dataset stored
without metadata re-reads the source and upgrades what is stored, while one
that already carries metadata is served from the cache. A request that
re-ingests stores the enrichment it asked for — `force` alone therefore drops
metadata the dataset had — and a request served from the cache leaves the
stored state as it found it. An enriched re-ingestion that fails answers with
the usual JSON error and leaves the previous dataset, metadata included,
exactly as it was.

### Dataset controls

| Parameter | Values | Effect |
| --- | --- | --- |
| `_size` | positive integer, default 100 | how many rows to return; a size past the end returns the rest |
| `_offset` | non-negative integer, default 0 | how many rows to skip first |
| `_sort` | column name | sort ascending by that column |
| `_sort_desc` | column name | sort descending; outranks `_sort` when both are given |
| `_shape` | `lists` (default) or `objects` | rows as value arrays, or as column-keyed objects |
| `_rowid` | `hide` | drop `rowid` from object rows |
| `_total` | `hide` | drop `total` from the response |

Sorting is stable and runs before pagination, `total` counts the rows before
it, and `rowid` is the row's 1-based line in the source file, counting the
header as line one. Repeating any control, or giving it a value outside the
table above, is a 400.

### Column filters

Any parameter shaped `<column>__<comparator>=<value>` filters the rows:

| Comparator | Keeps a row when its value... |
| --- | --- |
| `exact` | equals the value, case-sensitively |
| `contains` | holds the value as a substring, case-sensitively |
| `less` | reads as a number below the value |
| `greater` | reads as a number above the value |

Column names must match exactly, and several filters all have to hold at once,
as in `?role__contains=eng&score__greater=10`. Filtering happens before
sorting, so `total` and pagination both describe the matching rows. Values
that are not numbers — text, blanks — never match `less` or `greater`, and a
non-numeric filter value for either is a 400, as are an unknown column, an
unknown comparator, a repeated filter and a query that outlives its time
budget. Names starting with `_` are controls, and names without a `__`
suffix are neither filter nor control and are ignored.

Errors are JSON: `{"ok": false, "error": "..."}` — 400 for bad requests,
content that describes no table and sources past `MAX_SOURCE_SIZE`, 403 for a
missing or disallowed `Referer` while an allowlist is configured, 404 for
unreachable sources and unknown datasets or routes, 415 for an upload that is
not multipart. All responses
carry permissive CORS headers.

## Behaviour

- CSV, `.xls` and `.xlsx` payloads are all accepted, and the format is read
  off the bytes rather than off a file name or a URL. Anything that is neither
  a readable workbook nor a delimited table is a 400.
- Only a workbook's first worksheet is ingested, in its own column order, and
  it needs a header row and at least one data row like any other source.
- The dataset id is a hash of the source URL for a conversion and of the file
  bytes for an upload, so the same source always maps to the same endpoint and
  re-ingesting it refreshes its rows in place.
- `charset` only describes text CSV, and is only validated there: a workbook
  brings its own encoding and ignores the parameter.
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
| `config.py` | settings, their defaults, the config file and the environment |
| `app.py` | routes, error envelope, CORS |
| `access.py` | the origin allowlist and the source size limit |
| `fetcher.py` | source URL validation and download |
| `uploads.py` | multipart upload reading and content fingerprinting |
| `tabular.py` | format dispatch, decoding, delimiter detection, type inference, CSV output |
| `sheets.py` | first-worksheet reading for `.xls` and `.xlsx` workbooks |
| `query.py` | dataset query controls: paging, sorting, response shape |
| `filters.py` | `column__comparator` filters and the query time budget |
| `cache.py` | the `force` request flag and what `/convert` re-reads |
| `enrichment.py` | the `enrich=yes` trigger and the metadata it computes |
| `store.py` | dataset records, id derivation and storage on disk |
| `test_datagate.py` | pytest suite (`.venv/bin/python -m pytest`) |
