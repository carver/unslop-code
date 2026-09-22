# mvault

`mvault` keeps a local vault of media-platform metadata, records how the
tracked fields of each entry change from one sync to the next, downloads
the media behind those entries and browses the result in a local viewer.

## Usage

```
python mvault.py init <name> <url>   # create <name>/catalog.json for a source URL
python mvault.py sync <name>         # record what changed, then download what is missing
python mvault.py migrate <name>      # rewrite a legacy catalog in version 3
python mvault.py digest <name>       # summarize the notable changes a vault recorded
python mvault.py serve [<name>]      # browse the vaults of this directory
```

## Vault layout

`<name>/catalog.json` holds the `episodes`, `streams` and `clips` categories.
Each entry keeps `id`, `published`, `width` and `height` as static values, plus
one history object per tracked field (`title`, `description`, `views`, `likes`,
`preview`, `removed`). A history maps a `YYYY-MM-DDTHH:MM:SS` sync timestamp to
the value the field took from that moment on, so the newest key holds the
current value. Entries are never deleted; disappearing from the source records
`removed: true`, and reappearing records `removed: false`. Each entry also
carries an `annotations` list, which is yours to fill in and which mvault only
ever passes through.

Downloaded files live beside the catalog: media under `<name>/media/` and
preview images under `<name>/previews/`, each named after the entry it belongs
to. Every catalog write backs the previous catalog up to `<name>/catalog.bak`
first.

## `sync`

A sync runs in two phases. The metadata phase fetches the source, folds it into
the catalog and saves the result; the download phase then fetches the media and
preview file of every entry the vault does not hold yet. The catalog is on disk
before the first byte of media is requested, so unreachable media never costs
the vault what it just learned. Downloads that fail are reported on stderr and
skipped, and the run still succeeds.

| Option | Effect |
|---|---|
| `--episodes=<n>` | download at most `n` episode media files |
| `--streams=<n>` | download at most `n` stream media files |
| `--clips=<n>` | download at most `n` clip media files |
| `--skip-metadata` | download only, against the catalog as it stands |
| `--skip-download` | record metadata only |
| `--format=<str>` | ask the source for one format and store the file under it |

Candidates are the entries of a category, in catalog order, that no file in
`<name>/media/` is named after; a limit takes the first `n` of them. Leftovers
of an interrupted download end in `.part`, so they neither count as a held file
nor survive the next attempt. Without `--format` the extension of a downloaded
file follows the `Content-Type` of the response. A sync closes by reporting how
many entries it added, removed and updated, and then names each of them beside
the viewer address it can be read at.

## `digest`

`digest` prints the notable changes the histories of a vault hold, grouped by
category and then by kind: entries that have just been removed, entries that
have only ever been observed once, and entries whose tracked fields took a new
value, listed with the names of the fields that moved and with a note when an
entry came back after a removal. Each entry is reported once, under the first
of those kinds that fits it. Every reported entry carries the viewer address
it can be read at, on the line of its title. The closing line names the vault,
the catalog version it was read in and the source it tracks.

A digest reads whichever version the catalog is written in and never writes to
the vault, so it works on a legacy vault without migrating it first. Version 1
and version 2 catalogs have no `removed` history, so no removals are reported
for them, and version 1 keeps all of its entries in a single `Entries` group.

## `serve`

`serve` runs a viewer for the vaults of the working directory on
`127.0.0.1:8840` and opens a browser on it: on the landing page, or, when a
vault is named, on the page that vault opens with. `--host=<host>` and
`--port=<port>` move it elsewhere, and the browser follows. The viewer reads
every catalog version where it lies, so a legacy vault needs no migration to
be browsed, and it never writes to a vault.

| Route | Page |
|---|---|
| `/` | Ask for a vault by name, and offer the ones visited before, newest first |
| `/catalog/<name>` | Redirects to the category the vault version opens on |
| `/catalog/<name>/<category>` | The entries of one category, in catalog order |
| `/catalog/<name>/<category>/<id>` | The same listing, with that entry marked out |

A version 1 vault keeps its entries under `entries`; version 2 and 3 vaults
use `episodes`, `streams` and `clips`. Category names are matched exactly, and
one that the vault version does not know opens its default category instead.
Each listed entry shows its current title, whether the vault holds the media
behind it and, for a version 3 vault, whether the source has dropped it. A
vault the viewer cannot read sends the visitor back to the landing page, which
says which name it was.

The vaults the landing page offers are the ones the viewer was browsed for
before, kept in `.mvault-recent.json` beside them, so a later browser session
still finds them.

The addresses printed by `digest` and `sync` point into this viewer, so a
report read in a terminal opens in a server started next to it.

## Catalog versions

Catalogs declare the version they were written in, and every command reads all
of them:

| Version | Layout |
|---|---|
| 1 | one flat `entries` list, a short `source_id`, UNIX-epoch history keys, no `removed` or `annotations` |
| 2 | the three categories and a full `source`, ISO 8601 history keys, no `removed` or `annotations` |
| 3 | the layout above; written by this release |

An older catalog is upgraded in memory as it is loaded, so reading a vault
leaves its file alone. `sync` writes the result back, and `migrate` upgrades a
vault on its own; both back the original catalog up before writing it, and
`migrate` leaves a vault that is already at version 3 untouched. A version 1
vault names its platform rather than its feed, so its source URL is
`https://media.example.com/channel/<source_id>` -- the URL a sync of such a
vault fetches its metadata and its media from.

## Modules

| File | Responsibility |
|---|---|
| `mvault.py` | Command line entry point |
| `vault.py` | `init`, `sync` and `migrate` behavior |
| `merging.py` | Folding fetched source entries into a catalog |
| `downloads.py` | Media and preview downloads |
| `digest.py` | `digest` behavior: classifying and reporting changes |
| `server.py` | `serve` behavior: the viewer HTTP server |
| `routes.py` | What the viewer answers to each request |
| `pages.py` | The HTML the viewer serves |
| `recents.py` | Vaults the viewer was browsed for before |
| `viewer.py` | Viewer addresses, shared by the server and the reports |
| `views.py` | Read-only views over a catalog of any version |
| `catalogs.py` | Catalog schema, ordering and persistence |
| `migrations.py` | Version detection and upgrade of legacy catalogs |
| `history.py` | Tracked-field history objects |
| `source.py` | Source download and schema validation |
| `timestamps.py` | Canonical datetime text |
| `errors.py` | User-facing failure type |

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest test_mvault
```

`requirements.txt` is empty: mvault uses only the standard library.
