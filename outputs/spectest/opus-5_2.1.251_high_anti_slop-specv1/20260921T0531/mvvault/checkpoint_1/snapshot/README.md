# mvault

`mvault` creates local vaults of media-platform metadata and records the
history of tracked fields, keyed by the timestamp of the sync that observed
them.

## Usage

```
python mvault.py init <name> <url>   # create <name>/ with an empty catalog
python mvault.py sync <name>         # fetch <url> and fold it into the catalog
```

A sync appends a history entry only when a tracked value changed. Entries the
source no longer offers are never deleted; they gain a `removed: true` point,
and a `removed: false` point if they come back. The previous `catalog.json` is
copied to `catalog.bak` before every write.

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
| `vault/timestamps.py` | Timestamp text, `published` normalization, `SyncClock` |

## Development

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt   # standard library only
.venv/bin/python -m unittest discover -s tests
```
