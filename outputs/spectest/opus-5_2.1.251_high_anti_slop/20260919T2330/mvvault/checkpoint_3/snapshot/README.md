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
python mvault.py sync <name>         # fetch the source, update the catalog, download media
python mvault.py digest <name>       # print the notable changes recorded in a vault
python mvault.py migrate <name>      # convert a legacy catalog to version 3
```

## `sync`

`sync` runs a metadata phase and then a download phase. The metadata phase
appends a timestamped history entry whenever a tracked field
(`title`, `description`, `views`, `likes`, `preview`, `removed`) changes.
Entries are never deleted: disappearing from the source records
`removed: true`, and reappearing records `removed: false`.
Every write to an existing catalog is preceded by a `catalog.bak` copy. It ends
by printing how many entries were added, removed and updated.

The download phase fetches `<source>/media/<id>` into `<name>/media/` and
`<source>/preview/<id>` into `<name>/previews/`, for every entry that has no
stored media yet, in catalog order. The media extension comes from the response
`Content-Type`. Each file is written to a `.part` file and renamed once it is
complete, so a partial download never passes for stored media. Entries the
source cannot serve are reported on stderr and skipped; transient failures are
retried first. Downloads never affect the exit code, and the catalog is always
saved before they start.

| Option | Effect |
|---|---|
| `--episodes=<n>`, `--streams=<n>`, `--clips=<n>` | Download at most `n` media files of that category; without the option, that category has no limit |
| `--skip-metadata` | Download only, against the catalog as it stands |
| `--skip-download` | Update the catalog only |
| `--format=<str>` | Request `<source>/media/<id>.<str>` and store it with `<str>` as its extension |

## `digest`

`digest` prints the notable changes a vault has recorded, grouped by category
and then by kind: entries seen only once (added), entries whose latest `removed`
observation took them out of the source (removed), and entries with a tracked
field whose two latest values differ (updated, listing the changed field names).
An entry appears once, a removal outranking an addition and an addition
outranking an update; an entry that came back is listed as `reappeared`. It
reads v1, v2 and v3 catalogs in their own shape and never writes to the vault,
so a legacy vault needs no migration first. Version 1 has no categories and no
removals, so it yields a single `Entries` group with no removal entries, and its
UNIX-epoch history keys are ordered numerically rather than as text.

## Catalog versions

Version 3 is the native format: category arrays (`episodes`, `streams`,
`clips`), a full `source` URL, ISO 8601 history keys, and a `removed` history
plus `annotations` on every entry. Version 1 (flat `entries` list, `source_id`,
UNIX-epoch history keys) and version 2 (category arrays, ISO 8601 keys, no
`removed`) are still readable: the writing commands convert them to version 3
in memory when they load the vault, and `digest` reads each version in its own
shape, so nothing has to be migrated beforehand.

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
| `vault/versions.py` | Version detection, version-native views and migration |
| `vault/source.py` | Source HTTP fetch and entry validation |
| `vault/syncing.py` | Merging fetched entries into a catalog |
| `vault/history.py` | Timestamp text and tracked-field histories |
| `vault/downloads.py` | Media and preview downloads into the vault directory |
| `vault/digest.py` | Classifying and rendering the notable changes of a vault |
| `vault/errors.py` | Errors surfaced as CLI failures |
