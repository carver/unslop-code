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

A sync ends by printing how many entries it added, lost and updated.

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
