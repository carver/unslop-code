# mvault

Local vaults for media-platform metadata, with tracked-field history recorded by
sync timestamp.

```
python mvault.py init <name> <url>   # create <name>/catalog.json for a source URL
python mvault.py sync <name> [opts]  # fetch the source, record changes, download media
python mvault.py migrate <name>      # convert a legacy catalog to version 3
python mvault.py digest <name>       # summarize notable changes on stdout
python mvault.py serve [<name>]      # browse vaults in a local web viewer
```

`sync` runs a metadata phase and then a download phase. The metadata phase is
persisted before any download runs, so a failed download never costs metadata;
failed downloads are warnings on stderr and the run still succeeds. A run that
includes the metadata phase ends with an added/removed/updated summary.

```
--episodes=<n> --streams=<n> --clips=<n>   cap media downloads per category
--skip-metadata                            download only, against the stored vault
--skip-download                            fetch and persist metadata only
--format=<str>                             media format to request and file extension
```

`digest` reads a vault of any version in place -- it never migrates and never
writes -- and groups each entry once under removals, additions or field updates.
Every changed-entry line it prints, and every changed-entry line of the
post-sync summary, ends in a viewer link to that entry:
`http://127.0.0.1:8840/catalog/<name>/<category>/<id>`.

`serve` runs that viewer on `127.0.0.1:8840` (`--host` and `--port` move it) and
opens a browser on `/`, or on the given vault's default category page. The
landing page takes a vault name and lists the vaults visited before, newest
first; `/catalog/<name>` redirects to the vault's default category and
`/catalog/<name>/<category>` lists its entries in catalog order, marking which
are downloaded and, for version 3, which have been removed. Like `digest`, the
viewer reads every supported version in place; the only vault it writes to is
one whose entry is annotated.

`/catalog/<name>/<category>/<id>` is one entry's detail page, looked up inside
that category alone -- the same id in another category is a different entry, and
a removed v3 entry still has a page. It shows the entry's current title and
description, its published date and dimensions, a link back to the listing and a
deterministic link to the entry on its source platform: the stored `source` plus
`/entry/<id>` for v2 and v3, and `https://media.example.com/channel/<source_id>`
plus the same tail for v1.

The page also embeds its `views` and `likes` histories as JSON, oldest point
first, and draws each as a line. History keys are normalized across versions:
v1 stores UNIX-epoch strings, ordered numerically and rendered as ISO 8601 UTC,
while v2 and v3 store ISO 8601 text that is ordered lexicographically and passed
through. Recorded `null` likes are charted as `null` rather than dropped.

The same route takes annotations -- titled marks at a whole-second offset into
an entry's media -- as JSON, and answers each with a redirect back to the page:

```
POST   {"title": "chorus", "timecode": "1:30", "body": "key change"}
PATCH  {"id": "<id>", "title": "chorus", "body": "key change"}
DELETE {"id": "<id>"}
```

A `timecode` is `SS`, `MM:SS` or `HH:MM:SS` of non-negative integers, with no
conventional clock bounds -- `90:00` is 5400 seconds -- and is stored as whole
seconds. A create redirects to `?timecode=<seconds>`, which the page uses to
start playback there. Annotations live in the entry's `annotations` list in
creation order and the page renders them in that order, each offset as raw
seconds.

Only version 3 entries have that list, so annotating a v1 or v2 vault migrates
the whole catalog by the `migrate` rules first and persists the migration and
the annotation in one write, leaving `catalog.bak` holding the catalog as it
was before either change. A v1 request addresses its entry through the
pre-migration `entries` category; the redirect, and every later request, uses
the `episodes` the entry moved into.

Stored assets are served beside the pages that reference them.
`/vault/<name>/media/<file>` serves `<vault>/media/<file>` and
`/vault/<name>/preview/<id>` serves the preview image in `<vault>/previews/`
whose saved name contains that id. Both resolve strictly inside their own
directory, so a request carrying a traversal sequence is a `404` rather than a
file the viewer was never asked to publish.

Catalog versions 1 and 2 are read transparently, so no command needs a migrated
vault. `init`, `sync` and `migrate` upgrade an old catalog to the version 3
shape in memory; `migrate`, and any `sync` that runs its metadata phase, also
store the upgrade after backing the original up to `catalog.bak`. `digest`
instead reads each version in its own shape and writes nothing.

## Layout

| Path | Contents |
|---|---|
| `mvault.py` | CLI entry point: argument parsing and exit codes |
| `mvaultlib/catalog.py` | Vault creation, catalog validation, backup-then-write |
| `mvaultlib/entries.py` | Stored entry shape, tracked-field history, ordering |
| `mvaultlib/versions.py` | Version detection and upgrading v1/v2 catalogs to v3 |
| `mvaultlib/migrate.py` | The `migrate` command |
| `mvaultlib/source.py` | Source `GET` and source-document validation |
| `mvaultlib/sync.py` | The `sync` phases, entry merging and the change summary |
| `mvaultlib/downloads.py` | Download phase: candidates, retries, stored file names |
| `mvaultlib/views.py` | Version-aware read-only views used by `digest` and the viewer |
| `mvaultlib/digest.py` | The `digest` command: change classification and layout |
| `mvaultlib/timestamps.py` | Canonical `YYYY-MM-DDTHH:MM:SS` datetime text |
| `mvaultlib/annotations.py` | Timecodes and the create/update/delete of one entry's marks |
| `mvaultlib/viewer/links.py` | Viewer routes, report links and version-aware categories |
| `mvaultlib/viewer/server.py` | The `serve` command: its HTTP routes and redirects |
| `mvaultlib/viewer/pages.py` | HTML for the landing page and the category listing |
| `mvaultlib/viewer/listing.py` | Entry rows: current title, downloaded and removed state |
| `mvaultlib/viewer/detail.py` | One entry's detail state: metadata, assets, charts and marks |
| `mvaultlib/viewer/edits.py` | Annotation writes: auto-migration, single write, redirect |
| `mvaultlib/viewer/charts.py` | `views`/`likes` series, normalized and plotted |
| `mvaultlib/viewer/assets.py` | Stored files the `/vault` endpoints serve, resolved safely |
| `mvaultlib/viewer/recent.py` | Recently visited vaults, stored in the served directory |
| `tests/` | Spec-derived tests, one module per spec section |
| `AMBIGUITIES.md` | Under-specified points and the readings chosen here |

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

Tests drive the real CLI as a subprocess -- against a local HTTP source, and,
for the viewer, against a real `serve` process -- so they cover the documented
behaviour rather than internals.
