# mvault

`mvault` keeps a local vault of media-platform metadata and records how the
tracked fields of each entry change from one sync to the next.

## Usage

```
python mvault.py init <name> <url>   # create <name>/catalog.json for a source URL
python mvault.py sync <name>         # fetch the source and record what changed
```

## Vault layout

`<name>/catalog.json` holds the `episodes`, `streams` and `clips` categories.
Each entry keeps `id`, `published`, `width` and `height` as static values, plus
one history object per tracked field (`title`, `description`, `views`, `likes`,
`preview`, `removed`). A history maps a `YYYY-MM-DDTHH:MM:SS` sync timestamp to
the value the field took from that moment on, so the newest key holds the
current value. Entries are never deleted; disappearing from the source records
`removed: true`, and reappearing records `removed: false`.

Every write backs the previous catalog up to `<name>/catalog.bak` first.

## Modules

| File | Responsibility |
|---|---|
| `mvault.py` | Command line entry point |
| `vault.py` | `init` and `sync` behavior |
| `catalogs.py` | Catalog schema, ordering and persistence |
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
