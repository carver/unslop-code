# mvault

Creates local vaults for media-platform metadata, records tracked-field
history by sync timestamp, downloads the media behind it and summarizes what
changed.

## Usage

```
python mvault.py init <name> <url>     # create <name>/catalog.json for a source URL
python mvault.py sync <name> [options] # fetch the source, record what changed, download media
python mvault.py migrate <name>        # store an older catalog in the current format
python mvault.py digest <name>         # print the notable changes a vault has recorded
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
| `vault/cli.py` | Argument parsing and the `init` / `sync` / `migrate` / `digest` commands |
| `vault/catalog.py` | Catalog creation, validation, ordering, backup and writing |
| `vault/migration.py` | Reading catalogs written by older versions |
| `vault/views.py` | Reading a catalog in the version it was written in |
| `vault/schema.py` | Catalog version, categories and entry field types |
| `vault/errors.py` | The failures reported on stderr |
| `vault/source.py` | Fetching and validating source metadata |
| `vault/sync.py` | Merging a source snapshot into stored entries |
| `vault/download.py` | Fetching media and preview files into the vault |
| `vault/digest.py` | Deciding which recorded changes are notable |
| `vault/report.py` | The text `digest` and `sync` print on stdout |
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

## `sync`

A sync has two phases. The metadata phase fetches the source, merges the
snapshot and stores the catalog; the download phase then fetches the files of
entries that have none yet. The catalog is stored before any download starts,
so failing downloads never cost metadata, and a sync that skipped files
because of them still succeeds. Once the metadata phase has run, sync reports
how many entries it added, removed and updated.

| Option | Effect |
|---|---|
| `--episodes=<n>`, `--streams=<n>`, `--clips=<n>` | Download at most `n` media files of that category; without one, all of them |
| `--skip-metadata` | Skip the source fetch and the catalog write, and download against the stored catalog |
| `--skip-download` | Store metadata only |
| `--format=<str>` | Ask the source for media in that format and give the stored files that extension |

Media goes to `<vault>/media/` and preview images to `<vault>/previews/`, both
named after the entry. An entry counts as downloaded once it has a media file,
so candidates are the entries without one, in catalog order. Downloads are
written to a `.part` file and moved into place, so an interrupted one is
retried by the next run rather than mistaken for a finished file. Without
`--format` the extension comes from the response's `Content-Type`.

A download of content that is permanently gone is reported on stderr and
skipped; one that fails for a temporary-looking reason is retried first. Either
way the rest of the run continues and the sync succeeds.

## `digest`

`digest` prints the notable changes per category, grouped into the entries
that were added, the ones the source dropped, and the ones whose tracked
fields moved on — with the changed field names after the title, where an entry
the source published again reads as `reappeared`. Each entry is reported once,
removals first. The last line names the source and the catalog version the
summary came from.

Unlike the other commands, `digest` reads a catalog in its own version and
never writes one, so it works on a version 1 or 2 vault without migrating it.
Version 1 has no categories, so its entries make up one `Entries` group, and
its UNIX-epoch history keys are ordered as numbers. Versions 1 and 2 have no
`removed` field, so a digest of those cannot report removals.

## Catalog versions

Version 3 is what mvault writes: a `source` URL, the `episodes`, `streams` and
`clips` arrays, and entries carrying `removed` and `annotations`. Version 1,
with a `source_id`, one flat `entries` list and UNIX-epoch history keys, and
version 2, with categories and ISO 8601 history keys but no `removed` or
`annotations`, are still readable: every command upgrades them in memory as it
loads them, and a version 1 source URL is derived as
`https://media.example.com/channel/<source_id>`.

An upgraded catalog is only stored when a command writes anyway: `migrate`,
which does nothing to a version 3 vault, or the metadata phase of `sync`. The
backup written then holds the catalog as it was before the upgrade. Because
that upgrade happens first, the download phase always works from a version 3
catalog and its upgraded source URL.
