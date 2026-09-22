# mvault

Creates local vaults for media-platform metadata and records tracked-field
history by sync timestamp.

## Usage

```
python mvault.py init <name> <url>   # create <name>/catalog.json for a source URL
python mvault.py sync <name>         # fetch the source and fold it into the catalog
python mvault.py migrate <name>      # convert a legacy (v1/v2) catalog to v3 on disk
python mvault.py --help
```

## Layout

| Path | Role |
|---|---|
| `mvault.py` | Entry point; delegates to `mvaultlib.cli`. |
| `mvaultlib/cli.py` | Argument parsing, dispatch, error-to-exit-code mapping. |
| `mvaultlib/vault.py` | Vault lifecycle commands (`init`, `migrate`). |
| `mvaultlib/sync.py` | Merging source entries into the catalog (`sync`). |
| `mvaultlib/catalog.py` | Catalog schema, load/validate, ordering, backed-up writes. |
| `mvaultlib/versions.py` | Version detection and in-memory upgrade of v1/v2 catalogs. |
| `mvaultlib/source.py` | HTTP fetch and source-document validation. |
| `mvaultlib/history.py` | Tracked-field history reads and appends. |
| `mvaultlib/timestamps.py` | The single `YYYY-MM-DDTHH:MM:SS` datetime format. |
| `mvaultlib/errors.py` | User-facing error types. |

Catalog versions 1 and 2 are read transparently: every command upgrades them in
memory, and only a command that writes (`sync`, or `migrate` itself) persists
the version 3 result. Each catalog write first copies the previous
`catalog.json` to `catalog.bak`, so a migration's backup holds the pre-migration
catalog.

Tracked fields (`title`, `description`, `views`, `likes`, `preview`, `removed`)
are stored as `{timestamp: value}` objects and only grow when a value changes;
entries are never deleted, only marked `removed`.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

Interpretation decisions for under-specified behaviour are recorded in
`AMBIGUITIES.md`.
