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
python mvault.py serve [<name>]      # browse the vaults in a local web viewer
```

## `sync`

`sync` runs a metadata phase and then a download phase. The metadata phase
appends a timestamped history entry whenever a tracked field
(`title`, `description`, `views`, `likes`, `preview`, `removed`) changes.
Entries are never deleted: disappearing from the source records
`removed: true`, and reappearing records `removed: false`.
Every write to an existing catalog is preceded by a `catalog.bak` copy. It ends
by printing how many entries were added, removed and updated, followed by each
changed entry with its viewer link, grouped the way `digest` groups them.

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
outranking an update; an entry that came back is listed as `reappeared`. Every
line ends with the viewer link that opens the entry,
`http://127.0.0.1:8840/catalog/<name>/<category>/<id>`, using the category the
entry is browsed under in its own version. It reads v1, v2 and v3 catalogs in
their own shape and never writes to the vault, so a legacy vault needs no
migration first. Version 1 has no categories and no removals, so it yields a
single `Entries` group with no removal entries, and its UNIX-epoch history keys
are ordered numerically rather than as text.

## `serve`

`serve` runs the local viewer on `127.0.0.1:8840`, overridable with
`--host=<host>` and `--port=<port>`, and opens a browser on it: on the landing
page, or on the given vault. It reads vaults of any supported version without
migrating them, and writes nothing but its list of recently visited vaults
(`.mvault-recent.json`, beside the vault directories).

| Route | Answer |
|---|---|
| `GET /` | A form naming a vault to open, plus the recently visited vaults, newest first |
| `POST /` | Redirect to `/catalog/<catalog field>`, or back to `/` when the form names no vault |
| `GET /catalog/<name>` | Redirect to the vault's default category |
| `GET /catalog/<name>/<category>` | The category listing, in catalog order |
| `GET /catalog/<name>/<category>/<id>` | The page of that entry |
| `POST /catalog/<name>/<category>/<id>` | Create an annotation on that entry, then redirect to its page at the new timecode |
| `PATCH /catalog/<name>/<category>/<id>` | Update an annotation of that entry, then redirect to its page |
| `DELETE /catalog/<name>/<category>/<id>` | Delete an annotation of that entry, then redirect to its page |
| `GET /vault/<name>/media/<file>` | The named file from `<name>/media/` |
| `GET /vault/<name>/preview/<id>` | The preview image in `<name>/previews/` naming that entry |

A version 1 vault is browsed under the single category `entries`; later versions
under `episodes`, `streams` and `clips`, matched case-sensitively and defaulting
to `episodes`. A category the version does not define redirects to the default
one, and a vault that cannot be read sends the browser back to the landing page,
which then reports the name it could not open. Each listed entry shows its
current title, whether `<name>/media/` holds a file naming it, and, in a version
3 vault, whether its latest observation had it removed from the source.

### The entry page

An entry page shows the entry's current title and description, its publication
date and its dimensions, a link to it on the source platform, and the histories
of `views` and `likes`. It finds the entry only in the category the route names,
so the same id filed under another category is a different page, and an entry
version 3 records as removed from the source still has one. An id that category
does not hold answers `404`.

The source link is `<source>/entry/<id>`, built from the vault's own source URL,
which a version 1 vault derives from its `source_id`:
`https://media.example.com/channel/<source_id>/entry/<id>`.

The vault's media plays on the page when `<name>/media/` holds a file whose name
contains the entry id, addressed through `/vault/<name>/media/<file>` with that
exact filename; the preview image, found the same way in `<name>/previews/`,
becomes its poster. An entry whose media has not been downloaded keeps its
metadata and its charts. A `.part` file is an interrupted download, so it is
neither played nor served.

Each of `views` and `likes` is drawn as an inline SVG chart with a table of the
same numbers, and both are embedded as JSON in a
`<script type="application/json" id="chart-data">` element, as
`{"<field>": [{"timestamp": ..., "value": ...}, ...]}`. Points run oldest first
and their timestamps are always ISO 8601, whichever version the vault is: a
version 1 history is ordered by the numeric value of its UNIX-epoch keys and its
keys are converted to UTC, while ISO 8601 keys are ordered as text and pass
through unchanged. Values are reported as observed, `likes` nulls included. A
field observed only once gets neither a chart nor a payload entry, and an entry
whose histories are all that short still renders its metadata.

### Annotations

An entry page carries the annotations of its entry, in the order they were
created: each one a title, an optional body and the timecode it marks, linking to
the same page with `?timecode=<seconds>`, which opens the media at that second.
The page's forms manage them through the annotation methods of its own route,
which take JSON rather than a form encoding.

| Method | Request body | Answer |
|---|---|---|
| `POST` | `title` and `timecode`, optionally `body` | Redirect to the entry page with `?timecode=<seconds>` |
| `PATCH` | `id` and at least one of `title` or `body` | Redirect to the entry page |
| `DELETE` | `id` | Redirect to the entry page |

A `timecode` is `SS`, `MM:SS` or `HH:MM:SS`, every component a non-negative
integer; leading zeros are allowed and no component is held to a clock bound, so
`"90"` and `"1:30"` are both 90 seconds and `"90:00"` is 5400. It is stored, and
redirected to, as whole seconds. A body no request gave is stored as `null`, and
a `PATCH` leaves out what it does not mean to replace.

Every annotation is written back to the entry's `annotations` list under an id
unique within that entry, and `catalog.bak` holds the catalog as it was before
the write, so the next `GET` of the page shows what was stored. A request the
rules refuse changes nothing: a missing or unparsable field answers `400`, an
`id` the entry does not hold answers `404`, and a vault that cannot be read,
migrated or written answers `500`, each as a rendered page rather than a
traceback.

Annotations exist only in version 3, so annotating a version 1 or 2 vault
migrates the whole catalog first, by the rules of `migrate`, and saves the
migration and the annotation together: the backup holds the catalog from before
both. A version 1 entry is addressed under the category it is browsed as until
then, `entries`, and the redirect lands on the `episodes` page it has moved to;
from then on the vault is a version 3 one, and its `entries` route is retired.

A static route serves one file out of the vault's `media/` or `previews/`
directory and nothing else: a request naming anything but a plain filename is
refused with `403`, and a file the vault does not hold answers `404`. Both
routes send the browser back to the landing page when the vault itself cannot be
opened. Every error answers with a rendered page, never a traceback.

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
pre-migration catalog, and so does annotating an entry through the viewer.
Read-only commands never rewrite the file.

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
| `vault/digest.py` | Classifying and rendering the changes a vault and a sync record |
| `vault/changes.py` | Change kinds and records shared by the sync and the reports |
| `vault/viewer.py` | Viewer links, category routes and listing rows |
| `vault/detail.py` | The entry page model: current values, source link, chart points and annotations |
| `vault/annotations.py` | Annotation records, the timecode grammar and the edits applied to an entry |
| `vault/edits.py` | Applying an annotation edit to a vault, migrating a legacy catalog first |
| `vault/charts.py` | Inline SVG charts of a tracked field's history |
| `vault/assets.py` | Locating the downloaded files the static routes serve |
| `vault/routes.py` | Mapping a viewer request to its response |
| `vault/pages.py` | HTML of the viewer pages |
| `vault/recent.py` | Recently visited vaults, remembered between sessions |
| `vault/server.py` | The viewer HTTP server and its browser entry point |
| `vault/errors.py` | Errors surfaced as CLI failures |
