# mvault

Creates local vaults for media-platform metadata and records tracked-field
history by sync timestamp.

```
python mvault.py init <name> <url>   # create <name>/catalog.json for a source URL
python mvault.py sync <name> [opts]  # record what changed, then fetch missing media
python mvault.py migrate <name>      # convert a legacy catalog to the current format
python mvault.py digest <name>       # summarize a vault's notable changes
```

`sync` runs two phases. The metadata phase fetches the source, folds it into the
catalog's tracked-field histories and saves; the download phase then retrieves
the media and preview files the vault is still missing, into `<name>/media/` and
`<name>/previews/`. Either phase can be skipped, and a download failure only
warns -- the metadata is already on disk by then.

| `sync` option | Effect |
|---|---|
| `--episodes=<n>`, `--streams=<n>`, `--clips=<n>` | Cap that category at the first `n` candidates |
| `--format=<str>` | Request `<id>.<str>` and store it under that extension |
| `--skip-metadata` | Download only, against the vault as it stands |
| `--skip-download` | Metadata only |

`digest` is read-only and format-aware: it reads a v1, v2 or v3 catalog exactly
as stored, without migrating it, and groups each category's entries into
removals, additions and field updates.

Catalog versions 1 and 2 are read transparently: every command that loads a vault
migrates a legacy catalog in memory first, and only a command that writes (`sync`,
`migrate`) stores the converted v3 catalog on disk.

## Layout

| Path | Role |
|---|---|
| `mvault.py` | Entry point; delegates to `mvaultlib.cli` |
| `mvaultlib/cli.py` | Argument parsing, exit codes, stderr error reporting |
| `mvaultlib/commands.py` | The `init`, `sync`, `migrate` and `digest` workflows |
| `mvaultlib/vault.py` | Vault directory, version-aware loading, backed-up writes |
| `mvaultlib/catalog.py` | Version 3 catalog schema and entry ordering |
| `mvaultlib/legacy.py` | Version detection and v1/v2 to v3 conversion |
| `mvaultlib/source.py` | Source fetch and source-entry validation |
| `mvaultlib/entries.py` | Folding one source observation into stored entries |
| `mvaultlib/history.py` | Tracked-field history reads and appends |
| `mvaultlib/timestamps.py` | Canonical datetime text and sync-timestamp allocation |
| `mvaultlib/download.py` | The download phase: candidate selection, retries, file naming |
| `mvaultlib/digest.py` | Format-aware catalog reading and change classification |
| `mvaultlib/report.py` | Digest and post-sync summary rendering |

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
