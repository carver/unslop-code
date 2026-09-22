# mvault

`mvault` creates local vaults of media-platform metadata and records the
history of tracked fields, keyed by the timestamp of the sync that observed
them.

## Usage

```
python mvault.py init <name> <url>   # create <name>/ with an empty catalog
python mvault.py sync <name>         # fetch <url> and fold it into the catalog
python mvault.py migrate <name>      # rewrite a legacy catalog in the current format
```

A sync appends a history entry only when a tracked value changed. Entries the
source no longer offers are never deleted; they gain a `removed: true` point,
and a `removed: false` point if they come back. The previous `catalog.json` is
copied to `catalog.bak` before every write.

## Catalog versions

| Version | Shape |
|---|---|
| 1 | Flat `entries` list, short `source_id`, UNIX-epoch history keys, no `removed` or `annotations` |
| 2 | Category arrays, full `source`, ISO 8601 history keys, no `removed` or `annotations` |
| 3 | Version 2 plus `removed` and `annotations`; the format written by `init` and `sync` |

Every command reads all three versions: a legacy catalog is upgraded to
version 3 in memory as it is loaded, so a read-only command never rewrites the
file. A version 1 source URL is derived from its `source_id` as
`https://media.example.com/channel/<source_id>`, its entries all become
episodes, and its epoch history keys are converted to UTC timestamp text.
The `removed` history an upgrade adds holds one point: the entry was present
at the moment of the upgrade.

`migrate` stores that upgrade, backing the original catalog up first; on a
version 3 vault it does nothing at all. `sync` on a legacy vault upgrades,
merges and writes in one step, so its backup holds the pre-migration catalog.

## Layout

| Module | Responsibility |
|---|---|
| `mvault.py` | Entry point |
| `vault/cli.py` | Argument parsing, command dispatch, error reporting |
| `vault/catalog.py` | Catalog creation, validation, ordering, backed-up writes |
| `vault/sync.py` | Merging a source snapshot into a catalog |
| `vault/entries.py` | Entry records: static fields plus tracked histories |
| `vault/history.py` | Tracked-field history reads and appends |
| `vault/source.py` | HTTP fetch and source schema validation |
| `vault/versions.py` | Schema versions and the upgrade of legacy catalogs |
| `vault/timestamps.py` | Timestamp text, ISO/epoch normalization, `SyncClock` |
| `vault/errors.py` | `VaultError` |

## Development

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt   # standard library only
.venv/bin/python -m unittest discover -s tests
```
