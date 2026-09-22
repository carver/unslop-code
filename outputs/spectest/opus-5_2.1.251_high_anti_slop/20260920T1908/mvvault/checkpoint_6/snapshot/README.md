# mvault

Creates local vaults for media-platform metadata, records tracked-field
history by sync timestamp, downloads the media behind it, summarizes what
changed and serves a local viewer to browse the result.

## Usage

```
python mvault.py init <name> <url>        # create <name>/catalog.json for a source URL
python mvault.py sync <name> [options]    # fetch the source, record what changed, download media
python mvault.py migrate <name>           # store an older catalog in the current format
python mvault.py digest <name>            # print the notable changes a vault has recorded
python mvault.py serve [<name>] [options] # browse this directory's vaults in a browser
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
| `vault/cli.py` | Argument parsing and the `init` / `sync` / `migrate` / `digest` / `serve` commands |
| `vault/catalog.py` | Catalog creation, validation, ordering, backup and writing |
| `vault/migration.py` | Reading catalogs written by older versions |
| `vault/annotations.py` | Timecodes, and the annotations an entry carries |
| `vault/views.py` | Reading a catalog in the version it was written in |
| `vault/schema.py` | Catalog version, categories and entry field types |
| `vault/errors.py` | The failures reported on stderr |
| `vault/source.py` | Fetching and validating source metadata |
| `vault/sync.py` | Merging a source snapshot into stored entries |
| `vault/download.py` | Fetching media and preview files into the vault |
| `vault/digest.py` | Deciding which recorded changes are notable |
| `vault/changes.py` | The change set `digest` and `sync` both report |
| `vault/report.py` | The text `digest` and `sync` print on stdout |
| `vault/viewer/server.py` | The viewer's HTTP routes and the `serve` loop |
| `vault/viewer/pages.py` | The HTML the viewer serves |
| `vault/viewer/listing.py` | What the viewer shows about a category's entries |
| `vault/viewer/detail.py` | What the viewer shows about one entry |
| `vault/viewer/annotations.py` | The annotations an entry's page shows, and the forms that edit them |
| `vault/viewer/charts.py` | The `views` and `likes` charts of an entry, and the data behind them |
| `vault/viewer/assets.py` | The stored vault files the viewer reads about and serves |
| `vault/viewer/recents.py` | The vaults a browser has opened, kept in a cookie |
| `vault/viewer/links.py` | Viewer addresses, in reports and between pages |
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

Every entry line ends in the link that opens that entry in the viewer,
`http://127.0.0.1:8840/catalog/<name>/<category>/<id>`, with the category the
entry lives in under the catalog's own version. The summary `sync` prints
after its metadata phase lists the same lines above its counts; because sync
upgrades a catalog before merging, the entries of a version 1 vault are linked
as `episodes`.

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
which does nothing to a version 3 vault, the metadata phase of `sync`, or an
annotation written through the viewer, which needs the version 3 layout. The
backup written then holds the catalog as it was before the upgrade. Because
that upgrade happens first, the download phase always works from a version 3
catalog and its upgraded source URL.

## `serve`

`serve` runs a viewer for the vaults of the working directory on
`127.0.0.1:8840` and opens a browser on it — on the landing page, or on the
default category page of `<name>` when one is given. `--host=<host>` and
`--port=<port>` move it elsewhere; the links printed by `digest` and `sync`
always name the default address.

| Route | Answer |
|---|---|
| `GET /` | A form taking a vault name, and the vaults this browser has opened |
| `POST /` | Redirects to `/catalog/<catalog field>`, or back to `/` without one |
| `GET /catalog/<name>` | Redirects to the vault's default category |
| `GET /catalog/<name>/<category>` | The category's entries, in catalog order |
| `GET /catalog/<name>/<category>/<id>` | That entry's own page |
| `POST /catalog/<name>/<category>/<id>` | Adds an annotation to that entry |
| `PATCH /catalog/<name>/<category>/<id>` | Changes one annotation of that entry |
| `DELETE /catalog/<name>/<category>/<id>` | Drops one annotation of that entry |
| `GET /vault/<name>/media/<file>` | A media file the vault downloaded |
| `GET /vault/<name>/preview/<id>` | The preview image the vault downloaded for an entry |

Like `digest`, the viewer reads every catalog in the version it is stored in,
so a version 1 or version 2 vault is browsable without migrating it. Writing
an annotation is the one thing that stores a catalog, and migrates an older
one on the way. The version decides the categories: version 1 has the single
`entries`, later versions have `episodes`, `streams` and `clips`, and the
first of them is the default the bare `/catalog/<name>` route redirects to.
Category names are matched exactly; one this version does not have falls back
to that default.

A listing names each entry by its current title and marks whether its media is
on disk, which is true when some file in `<vault>/media/` carries the entry id.
Entries a version 3 catalog records as removed are marked as such. Nothing
about a vault is trusted to exist: a name with no readable catalog behind it
sends the browser back to the landing page, which says so.

Visiting a vault records it in a year-long cookie, so the landing page shows
where this browser has been, most recent first, even in a later session. Each
of those links points at the same default category page `/catalog/<name>`
would redirect to, and a vault that has since disappeared drops off the list.

### Entry pages

An entry's own page states its current title and description — the values
under the latest key of each history — its publication date, its dimensions,
the annotations kept on it, and the address it has on the source platform,
which is `<source>/entry/<id>` for every version. A version 1 vault gets there through the source URL derived
from its `source_id`, so its entries link to
`https://media.example.com/channel/<source_id>/entry/<id>`.

An id is only looked up in the category its address names: the same id in
another category of the same vault is a different entry with a different page,
and one this category does not hold answers `404`. An entry a version 3
catalog records as removed keeps its page and says the source no longer lists
it. A category this catalog version does not have falls back to the default
one, exactly as the listing route does, and a vault that cannot be read sends
the browser back to the landing page.

The page shows the files the vault has downloaded for the entry, which are the
saved files whose names carry its id: the preview image, and the media file as
a player pointed at `/vault/<name>/media/<file>`. An entry whose media has not
been downloaded keeps everything else, and says the file is missing.

### Charts

`views` and `likes` are plotted over the moments they were observed at, and the
points behind both lines are embedded in the page as JSON so they can be read
without looking at the picture. They are embedded as recorded: a `likes`
observation the source did not report stays `null` rather than becoming a zero,
and it breaks the line rather than being drawn through. A field observed only
once has no course to draw and is left out; the rest of the page does not
depend on it.

Points run oldest first, ordered the way the stored version's keys order —
version 1 epoch keys as numbers, later ISO 8601 keys as text. Their timestamps
read the same whatever version wrote them: a version 1 key is rendered as the
UTC moment its epoch seconds name, and a later one already carries ISO 8601
text and is passed through.

### Annotations

An entry's page lists the annotations kept on it — a note at a point in its
media, with a timecode, a title and an optional body — in the order they were
created, each one seeking the player to the moment it marks. Opening the page
with `?timecode=<seconds>` seeks to that moment too, which is where a new
annotation lands its writer.

The forms under the list write through the entry's own address, which takes
JSON: `POST` adds an annotation from a `title`, a `timecode` and an optional
`body`, `PATCH` names an annotation by `id` and replaces the `title` or `body`
it states, leaving out what it omits, and `DELETE` names one by `id`. Each
answers by redirecting to the entry's page — a creation to the `timecode` it
stored — so the page that follows the redirect shows what was written. A
request missing a field it needs, or carrying a timecode or a body that is not
one, is refused as a bad request; one naming an annotation the entry does not
hold answers `404`; and nothing is written either way.

A timecode is written as `SS`, `MM:SS` or `HH:MM:SS` and stored as whole
seconds, so `90` and `1:30` are the same moment and `1:01:30` is `3690`.
Components carry leading zeros and are not held to clock bounds, so `90:00` is
`5400` seconds rather than an error.

Only version 3 entries have an `annotations` list, so annotating a version 1
or version 2 vault migrates the whole catalog the way `migrate` does, and
stores the migration and the annotation with one write: the backup left behind
holds the catalog from before both. A version 1 vault is annotated through the
`entries` category it is still stored under, but its entries become `episodes`
in the same request, so the redirect names `episodes` and everything after it
goes through `episodes` as well. A migration that fails answers `500` and
leaves the catalog as it was.

### Stored files

`/vault/<name>/media/<file>` serves a downloaded media file by name, and
`/vault/<name>/preview/<id>` serves the preview image saved for an entry, which
is the image whose name carries that id. Both answer with the MIME type the
file's extension implies — the one it was downloaded as. A file that is not
there answers `404`.

The last segment of either address names one file of the directory it is looked
up in. One decorated into a path, however it was encoded, is refused with `403`
rather than resolved, so nothing outside `media/` and `previews/` is reachable.
Every refusal, on these routes and on the catalog ones, answers with a page
saying what was asked for rather than with a traceback.
