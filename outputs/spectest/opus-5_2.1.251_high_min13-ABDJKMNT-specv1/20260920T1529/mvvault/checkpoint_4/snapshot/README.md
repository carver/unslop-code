# mvault

Creates local vaults for media-platform metadata and records tracked-field
history by sync timestamp.

## Usage

```
python mvault.py init <name> <url>   # create <name>/catalog.json for a source URL
python mvault.py sync <name> [opts]  # fetch the source, then download media and previews
python mvault.py migrate <name>      # convert a legacy (v1/v2) catalog to v3 on disk
python mvault.py digest <name>       # print a summary of the vault's notable changes
python mvault.py serve [<name>] [--host=<host>] [--port=<port>]  # browse vaults
python mvault.py --help
```

## `sync` phases

A sync runs a metadata phase (fetch the source, fold it into the catalog, save
it, print an added/removed/updated summary) and then a download phase, which
fetches `<source>/media/<id>` into `<name>/media/` and `<source>/preview/<id>`
into `<name>/previews/` for every entry that has no media file yet. Metadata is
saved before downloads begin, so a failed download never costs a run its
history; failures are warnings on stderr and the run still exits `0`.

| Option | Effect |
|---|---|
| `--episodes=<n>`, `--streams=<n>`, `--clips=<n>` | Cap that category's media downloads at the first `n` candidates. |
| `--format=<str>` | Request `<source>/media/<id>.<str>` and store it with that extension. |
| `--skip-metadata` | Download only, against the vault as it stands. |
| `--skip-download` | Fetch and persist metadata only. |

## The viewer

`serve` starts a local browser viewer for the vaults in the working directory,
binding `127.0.0.1:8840` unless `--host` or `--port` says otherwise, and opens
a browser on the landing page — or, with a vault name, on that vault's default
category page. Like `digest`, it reads v1, v2 and v3 catalogs in their own
layout, so a vault needs no migration to be browsed.

| Route | Answer |
|---|---|
| `GET /` | A form that opens a vault by name, plus the vaults visited before. |
| `POST /` | Redirects to `/catalog/<catalog field>`, or back to `/`. |
| `GET /catalog/<name>` | Redirects to the version's default category. |
| `GET /catalog/<name>/<category>` | The category's entries in catalog order. |
| `GET /catalog/<name>/<category>/<id>` | The same listing, that entry surfaced. |

A listing marks each entry downloaded or not by whether `<vault>/media/` holds
a filename containing its id, and marks v3 entries whose latest `removed` value
is true. A vault the directory does not hold sends the visitor back to `/`,
which says so. Visits are remembered most-recent-first, in a long-lived cookie
and in `.mvault-recent.json` beside the vaults.

`digest` and the post-sync summary print a viewer link,
`http://127.0.0.1:8840/catalog/<name>/<category>/<id>`, beside every changed
entry's title.

`digest` is read-only and version-aware: it reports v1, v2 and v3 catalogs in
their own layout — v1 under a single `Entries` group with numerically ordered
epoch keys, v2 and v3 per category — without migrating anything.

## Layout

| Path | Role |
|---|---|
| `mvault.py` | Entry point; delegates to `mvaultlib.cli`. |
| `mvaultlib/cli.py` | Argument parsing, dispatch, error-to-exit-code mapping. |
| `mvaultlib/vault.py` | Vault lifecycle commands (`init`, `migrate`). |
| `mvaultlib/sync.py` | The `sync` phases: merging source entries, and the summary. |
| `mvaultlib/download.py` | The download phase: candidates, retries, stored files. |
| `mvaultlib/digest.py` | Classifying and reporting notable changes (`digest`). |
| `mvaultlib/views.py` | Reading a catalog in its own version's layout, unmigrated. |
| `mvaultlib/server.py` | The `serve` command: the viewer's HTTP routes. |
| `mvaultlib/pages.py` | The viewer's HTML pages. |
| `mvaultlib/recents.py` | The viewer's memory of visited vaults. |
| `mvaultlib/viewer.py` | Categories, routes and links shared by viewer and reports. |
| `mvaultlib/catalog.py` | Catalog schema, load/validate, ordering, backed-up writes. |
| `mvaultlib/versions.py` | Version detection and in-memory upgrade of v1/v2 catalogs. |
| `mvaultlib/source.py` | HTTP fetch and source-document validation. |
| `mvaultlib/history.py` | Tracked-field history reads and appends. |
| `mvaultlib/timestamps.py` | The single `YYYY-MM-DDTHH:MM:SS` datetime format. |
| `mvaultlib/errors.py` | User-facing error types. |

Catalog versions 1 and 2 are read transparently: every command that needs v3
data upgrades them in memory, and only a command that writes (`sync`, or
`migrate` itself) persists the version 3 result. `digest` is the exception — it
reads each version in its own layout and never upgrades at all. Each catalog write first copies the previous
`catalog.json` to `catalog.bak`, so a migration's backup holds the pre-migration
catalog.

Tracked fields (`title`, `description`, `views`, `likes`, `preview`, `removed`)
are stored as `{timestamp: value}` objects and only grow when a value changes;
entries are never deleted, only marked `removed`.

## Development

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest
```

Interpretation decisions for under-specified behaviour are recorded in
`AMBIGUITIES.md`.
