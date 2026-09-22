# mvault

`mvault` creates local vaults of media-platform metadata and records the
history of tracked fields, keyed by the timestamp of the sync that observed
them.

## Usage

```
python mvault.py init <name> <url>   # create <name>/ with an empty catalog
python mvault.py sync <name>         # fetch <url>, fold it into the catalog, download media
python mvault.py migrate <name>      # rewrite a legacy catalog in the current format
python mvault.py digest <name>       # report the vault's notable changes
python mvault.py serve [<name>]      # browse the vaults here in a web viewer
```

A sync appends a history entry only when a tracked value changed. Entries the
source no longer offers are never deleted; they gain a `removed: true` point,
and a `removed: false` point if they come back. The previous `catalog.json` is
copied to `catalog.bak` before every write.

## Catalog versions

| Version | Shape |
|---|---|
| 1 | Flat `entries` list, short `source_id`, UNIX-epoch history keys, no `removed` or `annotations` |
| 2 | Category arrays, full `source`, ISO 8601 history keys, no `removed` or `annotations` |
| 3 | Version 2 plus `removed` and `annotations`; the format written by `init` and `sync` |

Every command reads all three versions: a legacy catalog is upgraded to
version 3 in memory as it is loaded, so a read-only command never rewrites the
file. A version 1 source URL is derived from its `source_id` as
`https://media.example.com/channel/<source_id>`, its entries all become
episodes, and its epoch history keys are converted to UTC timestamp text.
The `removed` history an upgrade adds holds one point: the entry was present
at the moment of the upgrade.

`migrate` stores that upgrade, backing the original catalog up first; on a
version 3 vault it does nothing at all. `sync` on a legacy vault upgrades,
merges and writes in one step, so its backup holds the pre-migration catalog.

A sync ends by printing how many entries it added, lost and updated, and a
line per entry it changed.

## Downloading

A sync runs in two phases: the metadata phase above, and a download phase that
fetches what the vault is still missing. The catalog is saved between them, so
a download that fails never costs the vault the metadata it just gained — a
failed download is a warning on stderr and the sync carries on with the next
entry, retrying transient failures a few times first.

An entry is a download candidate while `<name>/media/` holds no file whose name
contains its id; candidates are taken in catalog order. Media comes from
`<url>/media/<id>` and lands in `<name>/media/`, its preview comes from
`<url>/preview/<id>` and lands in `<name>/previews/`. An extension comes from
the response content type unless `--format` names one. Each download is written
to a `.part` file that is renamed only when the transfer finished, so a stale
one never passes for stored media.

| Option | Effect |
|---|---|
| `--episodes=N`, `--streams=N`, `--clips=N` | Download at most `N` of that category; without it, every candidate |
| `--skip-metadata` | Download only, against the vault as it stands |
| `--skip-download` | Update the catalog only |
| `--format=EXT` | Ask the source for that media format and store it under that extension |

## Digesting

`digest` prints the notable changes of a vault: entries only ever observed
once are additions, entries whose newest `removed` point is `true` are
removals, and entries whose newest two points of a tracked field differ are
updates, named with the fields that changed. An entry appears once, under the
first of those that fits, grouped by category and closed by a line naming the
vault's source and catalog version.

It reads every catalog version in place rather than upgrading it, so a version
1 vault digests as one `Entries` group under its derived source URL, ordered
by its epoch keys read as numbers, and a version 1 or 2 vault has no removals
to report. `digest` never writes, not even a backup.

Both reports name every changed entry on a line of its own, and every such
line ends in the viewer link that opens the entry,
`http://127.0.0.1:8840/catalog/<name>/<category>/<id>`, under the category the
entry resides in — `entries` for a version 1 vault, and `episodes`, `streams`
or `clips` for later ones. A sync links the entries it changed under the
version it just wrote, so the episodes of a migrated version 1 vault link as
episodes.

## Viewing

`serve` runs a local viewer over the vaults of the working directory and opens
a browser on it: on the landing page, or straight on a named vault. It binds
`127.0.0.1:8840` unless `--host` or `--port` says otherwise, and the browser is
sent to the host as it was given.

| Route | Page |
|---|---|
| `/` | A field to open a vault by name, and the vaults this browser has visited |
| `/catalog/<name>` | Redirects to the vault's default category |
| `/catalog/<name>/<category>` | The category listing |
| `/catalog/<name>/<category>/<id>` | That entry's own page |
| `/vault/<name>/media/<file>` | One media file the vault downloaded |
| `/vault/<name>/preview/<id>` | The preview image the vault saved for an entry |

A version 1 vault offers the single `entries` category and defaults to it;
later versions offer `episodes`, `streams` and `clips` and default to
`episodes`. Categories are matched exactly, and asking for another one
redirects to the default. Entries are listed in catalog order under the title
their history currently holds, read by the key format of the vault's own
version, and each says whether `media/` already holds its media. Version 3
entries the source has dropped are marked removed.

A vault that is not there sends the browser back to the landing page, which
says so; nothing the viewer is asked for answers with a traceback. The viewer
reads a vault in the version it finds, so browsing never migrates or writes.

The vaults a browser has visited are kept in a cookie it sends back, newest
first, each linking to that vault's own default category page. They outlive
the browser being closed, and the viewer itself remembers nothing.

### Entry pages

An entry page shows the title and description the entry's histories currently
hold, its published date, its width and height, and a link to the entry on the
source platform: `<source>/entry/<id>`, where `<source>` is the vault's source
URL — for a version 1 vault the one derived from its `source_id`, so an entry
of `channel-42` links to
`https://media.example.com/channel/channel-42/entry/e1`. A link back to the
listing it came from closes the page.

An entry is looked up in the named category alone, so the same id under another
category is a different page, and one that belongs to no entry of this category
answers `404`. A version 3 entry the source has dropped still has its page.

The page plays the media file the vault downloaded for the entry — the file in
`media/` whose name holds the entry's id, served from `/vault/<name>/media/` under
the name it was saved as — and shows its preview image beside it, from
`/vault/<name>/preview/<id>`. Only the finished files a vault actually stores are
served, so a request for anything else answers `404`, and one spelling a path
rather than a file name answers `403`. A vault with neither file downloaded says
so and keeps the rest of the page as it is.

### Entry charts

The `views` and `likes` histories of an entry are embedded in its page as JSON,
in a `<script type="application/json" id="chart-data">` block: one object per
field, holding every point as a `timestamp` and a `value`, oldest point first,
with the `null` of an unknown like count kept as it is recorded. Each field with
two points or more is also drawn as a line chart, the two apart rather than on
shared axes — a view count and a like count are measures of different scale.

Chart timestamps are ISO 8601 whatever version the vault is: the epoch-second
keys of a version 1 catalog are converted to UTC timestamp text and ordered by
their numeric value, while the timestamp keys of later versions are passed
through and ordered as text. A field observed only once has no line to draw, and
the page is the same page without it.

## Layout

| Module | Responsibility |
|---|---|
| `mvault.py` | Entry point |
| `vault/cli.py` | Argument parsing, command dispatch, error reporting |
| `vault/catalog.py` | Catalog creation, validation, ordering, backed-up writes |
| `vault/sync.py` | Merging a source snapshot into a catalog |
| `vault/download.py` | The download phase: candidates, retries, stored files |
| `vault/digest.py` | Reading any catalog version and grouping its changes |
| `vault/report.py` | The digest report and the post-sync summary |
| `vault/links.py` | The viewer URLs that reports print and the viewer serves |
| `vault/media.py` | The media and preview files a vault stores for its entries |
| `vault/viewer/server.py` | The viewer's HTTP server and the `serve` command |
| `vault/viewer/routes.py` | Request paths and form fields to responses |
| `vault/viewer/vaults.py` | The viewer's version-aware view of a vault |
| `vault/viewer/pages.py` | The HTML the viewer serves |
| `vault/viewer/charts.py` | An entry's count histories as chart data and charts |
| `vault/viewer/assets.py` | The stored files the viewer serves, and from where |
| `vault/viewer/recent.py` | The visited vaults remembered in a browser cookie |
| `vault/entries.py` | Entry records: static fields plus tracked histories |
| `vault/history.py` | Tracked-field history reads and appends |
| `vault/source.py` | HTTP fetch and source schema validation |
| `vault/versions.py` | Schema versions and the upgrade of legacy catalogs |
| `vault/timestamps.py` | Timestamp text, ISO/epoch normalization, `SyncClock` |
| `vault/errors.py` | `VaultError` |

## Development

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt   # standard library only
.venv/bin/python -m unittest discover -s tests
```
