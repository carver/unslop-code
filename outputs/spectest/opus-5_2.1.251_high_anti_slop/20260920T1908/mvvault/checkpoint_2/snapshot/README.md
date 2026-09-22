# mvault

Creates local vaults for media-platform metadata and records tracked-field
history by sync timestamp.

## Usage

```
python mvault.py init <name> <url>   # create <name>/catalog.json for a source URL
python mvault.py sync <name>         # fetch the source and record what changed
python mvault.py migrate <name>      # store an older catalog in the current format
```

## Setup

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Layout

| Module | Responsibility |
|---|---|
| `mvault.py` | Entry point |
| `vault/cli.py` | Argument parsing and the `init` / `sync` / `migrate` commands |
| `vault/catalog.py` | Catalog creation, validation, ordering, backup and writing |
| `vault/migration.py` | Reading catalogs written by older versions |
| `vault/schema.py` | Catalog version, categories and entry field types |
| `vault/errors.py` | The failures reported on stderr |
| `vault/source.py` | Fetching and validating source metadata |
| `vault/sync.py` | Merging a source snapshot into stored entries |
| `vault/history.py` | Tracked-field history reads and appends |
| `vault/timestamps.py` | Datetime text formatting and normalization |

## Notes

Each tracked field (`title`, `description`, `views`, `likes`, `preview`,
`removed`) is stored as a map of `YYYY-MM-DDTHH:MM:SS` timestamp to the value
observed then; the current value is the one under the latest key. A value is
only appended when it differs from the current one, and a key that would
collide with an existing second advances to the next second. Entries are never
deleted: one that leaves the source gets `removed: true`, and one that returns
gets `removed: false`. `catalog.json` is copied to `catalog.bak` before every
write over an existing file.

## Catalog versions

Version 3 is what mvault writes: a `source` URL, the `episodes`, `streams` and
`clips` arrays, and entries carrying `removed` and `annotations`. Version 1,
with a `source_id`, one flat `entries` list and UNIX-epoch history keys, and
version 2, with categories and ISO 8601 history keys but no `removed` or
`annotations`, are still readable: every command upgrades them in memory as it
loads them, and a version 1 source URL is derived as
`https://media.example.com/channel/<source_id>`.

An upgraded catalog is only stored when a command writes anyway: `migrate`,
which does nothing to a version 3 vault, or `sync`. The backup written then
holds the catalog as it was before the upgrade.
