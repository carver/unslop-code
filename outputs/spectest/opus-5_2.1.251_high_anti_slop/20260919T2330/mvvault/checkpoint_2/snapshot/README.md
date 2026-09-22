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
python mvault.py migrate <name>      # convert a legacy catalog to version 3
```

`sync` appends a timestamped history entry whenever a tracked field
(`title`, `description`, `views`, `likes`, `preview`, `removed`) changes.
Entries are never deleted: disappearing from the source records
`removed: true`, and reappearing records `removed: false`.
Every write to an existing catalog is preceded by a `catalog.bak` copy.

## Catalog versions

Version 3 is the native format: category arrays (`episodes`, `streams`,
`clips`), a full `source` URL, ISO 8601 history keys, and a `removed` history
plus `annotations` on every entry. Version 1 (flat `entries` list, `source_id`,
UNIX-epoch history keys) and version 2 (category arrays, ISO 8601 keys, no
`removed`) are still readable: every command converts them to version 3 in
memory when it loads the vault, so nothing has to be migrated beforehand.

A version 1 source URL is derived from its `source_id` as
`https://media.example.com/channel/<source_id>`, and its entries all become
`episodes`. Migration records `removed` as a single `false` observation taken
at migration time and adds an empty `annotations` list.

`migrate` writes the converted catalog back to disk, after backing the original
up to `catalog.bak`; on a version 3 vault it does nothing. `sync` on a legacy
vault migrates as part of its normal write, so the backup it leaves holds the
pre-migration catalog. Read-only commands never rewrite the file.

## Layout

| File | Contents |
|---|---|
| `mvault.py` | CLI entry point and subcommand handlers |
| `vault/catalog.py` | Catalog schema, validation, ordering, persistence |
| `vault/versions.py` | Version detection and migration of legacy catalogs |
| `vault/source.py` | Source HTTP fetch and entry validation |
| `vault/syncing.py` | Merging fetched entries into a catalog |
| `vault/history.py` | Timestamp text and tracked-field histories |
| `vault/errors.py` | Errors surfaced as CLI failures |
