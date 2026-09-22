# datagate

Fetches remote tables -- CSV, `.xls` or `.xlsx` -- or takes them as uploads,
and serves them back as JSON datasets or as CSV downloads.

## Run

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python datagate.py start --port 8001 --address 127.0.0.1
```

`--port` defaults to `8001`, `--address` to `127.0.0.1`.

## Endpoints

| Route | Purpose |
| --- | --- |
| `GET /convert?source=<url>[&charset=<name>][&force]` | Ingest a remote table; answers `{"ok": true, "endpoint": "/datasets/<id>"}` |
| `POST /upload[?charset=<name>]` | Ingest an uploaded table; answers the same body |
| `GET /datasets/<id>` | Return `columns`, `rows`, `total` and `query_ms` |
| `GET /datasets/<id>/export` | Return the same rows as a CSV download |

The dataset id of a converted table is a hash of its source URL, and that of an
uploaded one a hash of its bytes, so ingesting the same table twice yields the
same endpoint either way. Failures answer `{"ok": false, "error": "..."}`:
400 for a bad request (missing or invalid `source`, a multipart upload naming no
file, unusable `charset`, non-tabular content, an unrecognised format, an
unusable control parameter, a `force` carrying a value), 404 for an unreachable
source or an unknown id, and 415 for an upload that is not a multipart form.

## Caching

`/convert` caches by default: a source that has been ingested before is
answered straight from the store, with the same body as the first time and
without downloading it again. Adding `force` re-downloads the source and
replaces the stored dataset with what came back.

`force` is a presence flag, so `?source=<url>&force` is the only way to write
it: giving it a value, `force=1` as much as `force=`, is a 400, and so is
repeating it. When it fails -- an unreachable source, content that no longer
parses -- the failure is reported exactly as a first ingestion would report it,
and the dataset already stored stays where it is and stays readable.

`CACHE_ENABLED` turns the cache off for the whole service. It takes `1`,
`true`, `yes` or `on`, and `0`, `false`, `no` or `off`, in any mix of upper and
lower case; any other value stops the service at startup. With the cache off
every `/convert` request downloads and parses its source again and replaces the
stored dataset, which is what `force` already does per request, so `force`
changes nothing then.

```bash
CACHE_ENABLED=off .venv/bin/python datagate.py start
```

## Uploading

```bash
curl -F file=@table.xlsx 'http://127.0.0.1:8001/upload'
```

The file travels in the form field `file` or `attachment`; either is accepted,
and the request has to be a `multipart/form-data` one.

## Formats

CSV, `.xls` and `.xlsx` are all ingested, by `/convert` and `/upload` alike, and
the format is read from the payload itself rather than from a name or a header.
Only the first worksheet of a workbook is taken, its columns in source order,
and it has to hold a header row and at least one data row like any other source.
A workbook carries its own encoding, so `charset` describes -- and is validated
against -- text CSV only.

## Exporting

`GET /datasets/<id>/export` answers with `Content-Type: text/csv` and a
`Content-Disposition` naming the file `<id>.csv`. The columns keep their source
order, and the rows are the ones `GET /datasets/<id>` would return for the same
filters, sort and pagination. The parameters that shape a JSON response --
`_shape`, `_rowid` and `_total` -- have no CSV equivalent and change nothing.

## Control parameters

`GET /datasets/<id>` accepts these, each at most once; repeating one is a 400.

| Parameter | Effect |
| --- | --- |
| `_size=<n>` | Return at most `n` rows, `n > 0`; defaults to 100 |
| `_offset=<n>` | Skip the first `n` rows, `n >= 0`; defaults to 0 |
| `_sort=<column>` | Sort ascending by `column` |
| `_sort_desc=<column>` | Sort descending by `column`; wins when `_sort` is also given |
| `_shape=lists` | Rows are arrays of values; the default |
| `_shape=objects` | Rows are objects keyed by column name, led by `rowid` |
| `_rowid=hide` | Leave `rowid` out of the rows |
| `_total=hide` | Leave `total` out of the response |

`total` counts the rows left by the filters, before pagination. Sorting is
stable -- rows that compare equal stay in source order -- and runs before
pagination, so `_size` and `_offset` cut into the filtered, sorted table. A `rowid` is
the row's 1-based line number in the source file, counting the header as line
1, and it stays with its row through sorting and pagination; it is not one of
the `columns`.

## Filters

`GET /datasets/<id>` also accepts column filters, written as
`<column>__<comparator>=<value>`; `GET /datasets/<id>?name__contains=ad` keeps
the rows whose `name` holds `ad`.

| Comparator | Keeps a row when its cell |
| --- | --- |
| `exact` | equals the value, as text, case-sensitively |
| `contains` | holds the value as a substring, case-sensitively |
| `less` | reads as a number strictly below the value |
| `greater` | reads as a number strictly above the value |

Column names are matched exactly and case-sensitively, and a column whose own
name contains `__` stays addressable: the comparator is the part after the
last `__`. Several filters are combined with AND, and each may be given only
once. Filtering runs first, so sorting and pagination see only the rows that
were kept.

`less` and `greater` need a numeric value; anything else is a 400. They read
the stored cell as a number too, so cells holding text -- a clock time such as
`08:30`, say -- match neither of them.

Filters are told apart from control parameters by the leading `_`, and from
everything else by the `__`: a parameter with neither, such as `name=ada`, is
ignored. An unknown column, an unknown comparator, a repeated filter, a
non-numeric value for `less` or `greater`, and a query that outlives its time
budget are all answered with a 400.

## Layout

| File | Responsibility |
| --- | --- |
| `datagate.py` | CLI entry point |
| `gateway/app.py` | Routes, CORS headers, error rendering |
| `gateway/caching.py` | Cache setting and the `force` bypass flag |
| `gateway/fetching.py` | Source URL validation, download, upload reading |
| `gateway/ingestion.py` | Format dispatch and header/data row splitting |
| `gateway/parsing.py` | Decoding, delimiter inference, CSV parsing |
| `gateway/spreadsheets.py` | First-worksheet reading of `.xls` and `.xlsx` |
| `gateway/export.py` | CSV rendering of the export response |
| `gateway/query.py` | Control parameters of a dataset request |
| `gateway/filters.py` | Column filters: parsing and row matching |
| `gateway/results.py` | Filtering, sorting, pagination and row shaping |
| `gateway/values.py` | Cell-to-JSON type inference |
| `gateway/store.py` | Dataset records and their deterministic ids |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```
