# mvault

Creates local vaults for media-platform metadata and records tracked-field
history by sync timestamp.

```
python mvault.py init <name> <url>   # create <name>/catalog.json for a source URL
python mvault.py sync <name>         # GET the source and record what changed
python mvault.py migrate <name>      # convert a legacy catalog to the current format
```

Catalog versions 1 and 2 are read transparently: every command that loads a vault
migrates a legacy catalog in memory first, and only a command that writes (`sync`,
`migrate`) stores the converted v3 catalog on disk.

## Layout

| Path | Role |
|---|---|
| `mvault.py` | Entry point; delegates to `mvaultlib.cli` |
| `mvaultlib/cli.py` | Argument parsing, exit codes, stderr error reporting |
| `mvaultlib/commands.py` | The `init`, `sync` and `migrate` workflows |
| `mvaultlib/vault.py` | Vault directory, version-aware loading, backed-up writes |
| `mvaultlib/catalog.py` | Version 3 catalog schema and entry ordering |
| `mvaultlib/legacy.py` | Version detection and v1/v2 to v3 conversion |
| `mvaultlib/source.py` | Source fetch and source-entry validation |
| `mvaultlib/entries.py` | Folding one source observation into stored entries |
| `mvaultlib/history.py` | Tracked-field history reads and appends |
| `mvaultlib/timestamps.py` | Canonical datetime text and sync-timestamp allocation |

`AMBIGUITIES.md` records where the spec admitted more than one reading and which
one this implementation follows.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests
```

The tests drive the real CLI as a subprocess against a localhost HTTP server, so
they exercise the shipped entry point rather than importing internals. The one
exception is `sync` on a version 1 vault, whose source URL is a fixed public host
that cannot be pointed at the test server: those tests call the package in-process
with `responses` mocking the HTTP layer.
Python 3.11+ is required (`datetime.fromisoformat` full ISO 8601 parsing).
