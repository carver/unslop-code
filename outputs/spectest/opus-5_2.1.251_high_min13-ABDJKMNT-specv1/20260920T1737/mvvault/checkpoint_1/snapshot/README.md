# mvault

Local vaults for media-platform metadata, with tracked-field history recorded by
sync timestamp.

```
python mvault.py init <name> <url>   # create <name>/catalog.json for a source URL
python mvault.py sync <name>         # fetch the source and record changes
```

## Layout

| Path | Contents |
|---|---|
| `mvault.py` | CLI entry point: argument parsing and exit codes |
| `mvaultlib/catalog.py` | Vault creation, catalog validation, backup-then-write |
| `mvaultlib/entries.py` | Stored entry shape, tracked-field history, ordering |
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
