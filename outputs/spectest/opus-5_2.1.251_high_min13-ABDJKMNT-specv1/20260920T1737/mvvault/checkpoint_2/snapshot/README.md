# mvault

Local vaults for media-platform metadata, with tracked-field history recorded by
sync timestamp.

```
python mvault.py init <name> <url>   # create <name>/catalog.json for a source URL
python mvault.py sync <name>         # fetch the source and record changes
python mvault.py migrate <name>      # convert a legacy catalog to version 3
```

Catalog versions 1 and 2 are read transparently: every command upgrades an old
catalog to the version 3 shape in memory, so no command needs a migrated vault.
`migrate` -- and any `sync` of a legacy vault -- also stores the upgrade, after
backing the original up to `catalog.bak`.

## Layout

| Path | Contents |
|---|---|
| `mvault.py` | CLI entry point: argument parsing and exit codes |
| `mvaultlib/catalog.py` | Vault creation, catalog validation, backup-then-write |
| `mvaultlib/entries.py` | Stored entry shape, tracked-field history, ordering |
| `mvaultlib/versions.py` | Version detection and upgrading v1/v2 catalogs to v3 |
| `mvaultlib/migrate.py` | The `migrate` command |
| `mvaultlib/source.py` | Source `GET` and source-document validation |
| `mvaultlib/sync.py` | Merging source entries into a catalog |
| `mvaultlib/timestamps.py` | Canonical `YYYY-MM-DDTHH:MM:SS` datetime text |
| `tests/` | Spec-derived tests, one module per spec section |
| `AMBIGUITIES.md` | Under-specified points and the readings chosen here |

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

Tests drive the real CLI as a subprocess against a local HTTP server, so they
cover the documented behaviour rather than internals.
