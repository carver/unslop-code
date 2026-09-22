# mvault

Creates local vaults for media-platform metadata and records the history of
tracked fields by sync timestamp.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

```sh
python mvault.py init <name> <url>   # create <name>/catalog.json for a source URL
python mvault.py sync <name>         # fetch the source and update the catalog
```

`sync` appends a timestamped history entry whenever a tracked field
(`title`, `description`, `views`, `likes`, `preview`, `removed`) changes.
Entries are never deleted: disappearing from the source records
`removed: true`, and reappearing records `removed: false`.
Every write to an existing catalog is preceded by a `catalog.bak` copy.

## Layout

| File | Contents |
|---|---|
| `mvault.py` | CLI entry point and subcommand handlers |
| `vault/catalog.py` | Catalog schema, validation, ordering, persistence |
| `vault/source.py` | Source HTTP fetch and entry validation |
| `vault/syncing.py` | Merging fetched entries into a catalog |
| `vault/history.py` | Timestamp text and tracked-field histories |
| `vault/errors.py` | Errors surfaced as CLI failures |
