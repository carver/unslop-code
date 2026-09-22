# mvault

Creates local vaults for media-platform metadata and records tracked-field
history by sync timestamp.

```
python mvault.py init <name> <url>   # create <name>/catalog.json for a source URL
python mvault.py sync <name>         # GET the source and record what changed
```

## Layout

| Path | Role |
|---|---|
| `mvault.py` | Entry point; delegates to `mvaultlib.cli` |
| `mvaultlib/cli.py` | Argument parsing, exit codes, stderr error reporting |
| `mvaultlib/commands.py` | The `init` and `sync` workflows |
| `mvaultlib/catalog.py` | Vault directory, catalog schema, ordering, backed-up writes |
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
they exercise the shipped entry point rather than importing internals.
Python 3.11+ is required (`datetime.fromisoformat` full ISO 8601 parsing).
