# mvault

`mvault` keeps a local vault of media-platform metadata and records how the
tracked fields of each entry change from one sync to the next.

## Usage

```
python mvault.py init <name> <url>   # create <name>/catalog.json for a source URL
python mvault.py sync <name>         # fetch the source and record what changed
python mvault.py migrate <name>      # rewrite a legacy catalog in version 3
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

Every write backs the previous catalog up to `<name>/catalog.bak` first.

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
`https://media.example.com/channel/<source_id>`.

## Modules

| File | Responsibility |
|---|---|
| `mvault.py` | Command line entry point |
| `vault.py` | `init`, `sync` and `migrate` behavior |
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
