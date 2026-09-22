# mvault

Local vaults for media-platform metadata, with tracked-field history recorded by
sync timestamp.

```
python mvault.py init <name> <url>   # create <name>/catalog.json for a source URL
python mvault.py sync <name> [opts]  # fetch the source, record changes, download media
python mvault.py migrate <name>      # convert a legacy catalog to version 3
python mvault.py digest <name>       # summarize notable changes on stdout
```

`sync` runs a metadata phase and then a download phase. The metadata phase is
persisted before any download runs, so a failed download never costs metadata;
failed downloads are warnings on stderr and the run still succeeds. A run that
includes the metadata phase ends with an added/removed/updated summary.

```
--episodes=<n> --streams=<n> --clips=<n>   cap media downloads per category
--skip-metadata                            download only, against the stored vault
--skip-download                            fetch and persist metadata only
--format=<str>                             media format to request and file extension
```

`digest` reads a vault of any version in place -- it never migrates and never
writes -- and groups each entry once under removals, additions or field updates.

Catalog versions 1 and 2 are read transparently, so no command needs a migrated
vault. `init`, `sync` and `migrate` upgrade an old catalog to the version 3
shape in memory; `migrate`, and any `sync` that runs its metadata phase, also
store the upgrade after backing the original up to `catalog.bak`. `digest`
instead reads each version in its own shape and writes nothing.

## Layout

| Path | Contents |
|---|---|
| `mvault.py` | CLI entry point: argument parsing and exit codes |
| `mvaultlib/catalog.py` | Vault creation, catalog validation, backup-then-write |
| `mvaultlib/entries.py` | Stored entry shape, tracked-field history, ordering |
| `mvaultlib/versions.py` | Version detection and upgrading v1/v2 catalogs to v3 |
| `mvaultlib/migrate.py` | The `migrate` command |
| `mvaultlib/source.py` | Source `GET` and source-document validation |
| `mvaultlib/sync.py` | The `sync` phases, entry merging and the change summary |
| `mvaultlib/downloads.py` | Download phase: candidates, retries, stored file names |
| `mvaultlib/views.py` | Version-aware read-only views used by `digest` |
| `mvaultlib/digest.py` | The `digest` command: change classification and layout |
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
