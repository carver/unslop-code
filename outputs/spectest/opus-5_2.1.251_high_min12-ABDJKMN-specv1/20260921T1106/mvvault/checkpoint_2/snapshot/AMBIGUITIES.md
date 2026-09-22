# AMBIGUITIES

Numbered record of spec under-specification, the interpretation chosen for this
implementation, and the risk that the spec author's own implementation (and
therefore the hidden tests) reads it differently.

## T1 — Location of `catalog.bak`

### Spec Text
> | Backup path | `catalog.bak` |

and

> | Catalog path | `<name>/catalog.json` |

### Alternatives
1. `<name>/catalog.bak`, i.e. next to the catalog inside the vault directory.
2. `catalog.bak` relative to the process working directory.

### Choice
`<name>/catalog.bak`. The backup is described in the `catalog.json`
Persistence section as a copy of the vault's catalog, and the catalog path is
given as vault-relative; a working-directory backup would collide between
vaults.

### Risk: 3
Author most likely prefers: the same vault-relative path.

## T2 — Scope of the collision / "strictly increasing" rule

### Spec Text
> | Collision handling | When a new history entry would reuse an existing or
> non-newer second, advance to a strictly later second before writing |

> | Sync timestamps | Reflect sync execution time and remain strictly
> increasing whenever new history entries are appended |

### Alternatives
1. One timestamp per sync run: take the current second, and if it is not
   strictly newer than the newest history key anywhere in the catalog, advance
   to `newest + 1s`. Every field appended in that run shares it.
2. Per-field: each field's new key is compared only with that field's own
   existing keys, so different fields in one run can get different seconds.
3. Per-entry: compared only against that entry's keys.

### Choice
Alternative 1. The update rules speak of a single "sync timestamp" for all six
tracked fields of a first observation, which only holds if the timestamp is
computed once per run; and "strictly increasing" is a statement about sync
timestamps as a sequence, which is a catalog-wide property.

### Risk: 22
Author most likely prefers: same single-timestamp-per-sync model, but possibly
comparing only against keys of the entries being touched (indistinguishable
except when a catalog holds a future-dated key on an untouched entry).

## T3 — Whether an existing `catalog.bak` counts as vault data

### Spec Text
> | Existing directory | Error to stderr including `<name>`; exit non-zero; no
> modification of existing data |

### Alternatives
1. `init` refuses whenever the path exists at all (directory **or** file).
2. `init` refuses only when the path is an existing directory, and would
   otherwise fail some other way on a plain file.

### Choice
Alternative 1: any existing path is refused with the vault-name error. A plain
file at `<name>` cannot become a vault, and this keeps the "no modification"
guarantee absolute.

### Risk: 12
Author most likely prefers: `os.path.exists` check as well; a test with a plain
file at the vault path is unlikely either way.

## T4 — What makes a vault "invalid" for `sync`

### Spec Text
> | Missing or invalid vault | Error to stderr including `<name>`; exit
> non-zero |

### Alternatives
1. Strict: `<name>/catalog.json` must exist, parse as a JSON object, carry
   `version == 3`, a string `source`, and all three category arrays whose
   items are objects with string `id`s. Anything else is an invalid vault.
2. Lenient: only require a parseable JSON object; treat missing categories as
   empty and ignore `version`.

### Choice
Alternative 1 (strict), minus deep validation of stored history objects. The
root schema table states required fields and types, so a catalog violating it
is not a "valid vault"; failing loudly also protects the user's data from a
half-understood file being rewritten.

### Risk: 30
Author most likely prefers: strict on missing/unparseable catalog and missing
categories, but possibly lenient about `version` (a `version: 2` catalog might
be expected to sync, or to fail — this is the riskiest sub-case).

> **Resolved by the multi-version spec.** The `version` sub-case is now
> specified: `1` and `2` load (via in-memory migration), `version` greater
> than `3`, non-integer or missing is an error. The strict reading of the rest
> of the root schema is unchanged. See T14–T23.

## T5 — Source response missing a whole category

### Spec Text
> | Source response shape | JSON object with `episodes`, `streams`, and `clips`
> arrays |

> If any source entry is missing a required field or has the wrong type, `sync`
> must fail as a source metadata fetch failure and leave the vault unchanged.

### Alternatives
1. A response lacking one of the three arrays (or where one is not an array) is
   a source metadata fetch failure.
2. A missing category is treated as an empty array, which would mark every
   stored entry in that category as removed.

### Choice
Alternative 1. The spec states the response shape as a requirement and demands
strictness about entry shape; silently treating a malformed payload as "all
entries removed" would destroy history fidelity on a partial-outage response.

### Risk: 28
Author most likely prefers: the same strict reading, though `payload.get(cat,
[])` is a common shortcut that would make case 2 the observed behavior.

## T6 — Normalizing `published` values with timezone or fractional parts

### Spec Text
> | `published` | string | ISO 8601 datetime or date-only text |

> | Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix |
> | Date-only source values | Normalize to `00:00:00` time component |

### Alternatives
1. Parse, drop any timezone offset without shifting the clock, drop fractional
   seconds, and re-render as `YYYY-MM-DDTHH:MM:SS`.
2. Convert offset-aware values to UTC first, then drop the suffix.
3. Store the source text verbatim except for the date-only case.

### Choice
Alternative 1 — `datetime.fromisoformat(...).replace(tzinfo=None)` then format.
"without timezone suffix" reads as a text-shape rule rather than a conversion
rule, and it matches the most direct implementation. Values that cannot be
parsed at all are stored verbatim (they still sort deterministically by text).

### Risk: 25
Author most likely prefers: the same drop-the-suffix behavior; `Z`-suffixed
fixtures agree under readings 1 and 2, so only a non-UTC offset fixture would
separate them.

## T7 — Static fields when the source changes them

### Spec Text
> | Static | `published` | string | Original publication datetime |
> | Static | `width` | integer | Pixel width |

### Alternatives
1. Static fields are written at first observation and never updated.
2. Static fields are overwritten from the source on every sync (untracked, so
   no history, but always current).

### Choice
Alternative 1. "Static" and "Original publication datetime" both point at
first-observation values, and keeping them fixed keeps catalog ordering stable.

### Risk: 30
Author most likely prefers: possibly overwriting, since a loop that rebuilds an
entry's static fields each sync is an easy implementation; a fixture that
changes `width` between syncs would expose the difference.

## T8 — Whether a no-op sync rewrites `catalog.json`

### Spec Text
> | Backup trigger | Before every write to existing `catalog.json` |

> | Existing entry, unchanged tracked value | No new history entry for that
> field |

### Alternatives
1. `sync` always rewrites the catalog (and therefore always refreshes
   `catalog.bak`), even when no history changed.
2. `sync` skips the write when nothing changed, leaving `catalog.bak` alone.

### Choice
Alternative 1. The "no new history entry" rule constrains history content, not
whether a write happens, and an unconditional write is the straightforward
implementation. Content is identical either way; only `catalog.bak` and file
mtimes differ.

### Risk: 18
Author most likely prefers: the same unconditional write; a test asserting that
`catalog.bak` is absent after a no-change second sync would be needed to
distinguish them.

## T9 — Argument passed to `urllib.request.urlopen`

### Spec Text
> | Source request | HTTP `GET` to vault `source` URL, made with
> `urllib.request` |

### Alternatives
1. `urllib.request.urlopen(url_string)` — a GET by default.
2. `urllib.request.urlopen(urllib.request.Request(url, method="GET"))`.

### Choice
Alternative 1. Both issue a GET; passing the bare URL string is friendlier to
tests that monkeypatch `urlopen` and inspect the argument as a string. The
response is read with `.read()` and closed defensively rather than via `with`,
so simple fake response objects work.

### Risk: 10
Author most likely prefers: the bare-string call; a fixture asserting on
`Request.full_url` would prefer reading 2.

## T10 — Duplicate `removed: true` appends for entries that stay absent

### Spec Text
> | Entry absent from current source | Append `removed: true` at sync
> timestamp |

### Alternatives
1. Append only when the current `removed` value is not already `true` (treating
   `removed` like any other tracked field under the "unchanged value" rule).
2. Append on every sync while the entry is absent.

### Choice
Alternative 1. `removed` is listed as a tracked field, and the unchanged-value
rule applies to tracked fields generally; repeating identical values would
contradict "identical values produce no new history entry".

### Risk: 8
Author most likely prefers: the same change-only append.

## T11 — Where source-entry validation stops

### Spec Text
> Each source entry must contain all nine fields above with the stated types.

### Alternatives
1. Validate every entry in all three categories up front; on any violation, do
   not write anything (vault byte-for-byte unchanged).
2. Validate lazily and fail midway, possibly after a partial write.

### Choice
Alternative 1 — validate the whole payload before any mutation, because the
spec requires a failing sync to "leave the vault unchanged". Extra fields
beyond the nine (e.g. `annotations`) are ignored rather than rejected.

### Risk: 7
Author most likely prefers: the same up-front validation; the divergence would
only show if extra source fields were meant to be an error.

## T12 — Timezone basis of the sync timestamp

### Spec Text
> | Sync timestamps | Reflect sync execution time and remain strictly
> increasing whenever new history entries are appended |

> | Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix |

### Alternatives
1. Local wall-clock time (`datetime.now()`), truncated to the second.
2. UTC (`datetime.now(timezone.utc)` rendered naive).

### Choice
Alternative 1. The text carries no timezone, so the naive local clock is the
literal "execution time"; in the usual UTC test environment the two coincide.

### Risk: 15
Author most likely prefers: `datetime.now()` as well; a fixture running under a
non-UTC `TZ` and comparing against UTC would separate them.

## T13 — Same `id` appearing in more than one category

### Spec Text
> | First observation | Add entry to matching category |

### Alternatives
1. Identity is (category, id): the same id in `episodes` and `clips` is two
   independent entries.
2. Identity is id alone, catalog-wide.

### Choice
Alternative 1. "Matching category" and the per-category arrays imply entries
are keyed within their category; the source is free to reuse ids across
content types.

### Risk: 6
Author most likely prefers: per-category identity, since each category array is
naturally processed on its own.

## T14 — Whether a v1/v2 migration is persisted when the rest of the command fails

### Spec Text
> | Save timing | Save migrated v3 catalog immediately |

> | v1 vault | Auto-migrate to v3 in memory, apply sync updates, write v3
> catalog to disk |

> | Backup before write | Standard backup rules apply; backup contains the
> **original** pre-migration catalog |

> | Read-only access | Loading a v1 or v2 catalog for a read-only operation
> does **not** rewrite `catalog.json` |

### Alternatives
1. `sync` on a legacy vault performs exactly one write, at the end: migrate in
   memory, apply updates, then back up the original and write v3. A sync that
   aborts earlier (fetch failure, malformed source) leaves the legacy
   `catalog.json` and no `catalog.bak` behind.
2. Loading a legacy catalog persists the migration right away (a first write
   with `catalog.bak` = original), and the sync result is then a second write
   (whose `catalog.bak` = the migrated-but-unsynced catalog).

### Choice
Alternative 1. The `sync` row says "auto-migrate **in memory** ... write v3
catalog to disk" (one write), and the final `catalog.bak` is required to hold
the *original* pre-migration catalog, which reading 2 destroys with its second
backup. "Save immediately" then describes the `migrate` command, where the
migration is the whole command. This also keeps the read-only guarantee
absolute.

### Risk: 30
Author most likely prefers: the same single-write model; the divergence only
shows on a legacy vault whose sync fails (reading 2 would leave it migrated on
disk).

## T15 — What counts as "malformed v1 or v2 entry data"

### Spec Text
> | Malformed v1 or v2 entry data | Error to stderr; exit non-zero; leave
> `catalog.json` unchanged |

### Alternatives
1. Strict structural validation before any write: every entry is an object
   with a string `id`; every present history field is an object whose values
   match the declared types (`views` integer, `likes` integer or `null`, the
   rest strings); v1 history keys parse as integer epoch seconds; v2 history
   keys parse as ISO 8601; `source_id`/`source` and the category containers
   have the declared types.
2. Convert opportunistically and only fail where conversion itself raises —
   in practice only a non-integer v1 epoch key.
3. Full schema validation including *required* presence of all nine entry
   fields.

### Choice
Alternative 1, with missing fields tolerated (a v1 entry lacking `preview` is
migrated without it rather than rejected). It covers every case where the
stored data cannot be interpreted under the declared schema, while not
inventing a presence requirement the migration tables never state — they say
what to convert, not what must exist.

### Risk: 40
Author most likely prefers: something closer to reading 2 — a converter that
only raises on the epoch-key conversion — so a fixture with, say, a
string-valued `views` history may be expected to migrate rather than fail.

## T16 — Exact epoch-key conversion rules

### Spec Text
> | v1 UNIX-epoch conversion | Convert each epoch-seconds key to
> `YYYY-MM-DDTHH:MM:SS` in UTC |

### Alternatives
1. `int(key)` interpreted as UTC seconds, rendered without timezone suffix;
   keys that are not integer strings (`"1718444400.5"`, `"yesterday"`) are
   malformed entry data.
2. Accept fractional epoch strings by truncating, and/or fall back to leaving
   an unparseable key in place.

### Choice
Alternative 1. The spec calls the keys "string representations of UNIX epoch
seconds", so whole seconds is the declared domain, and an unconvertible key is
exactly the "malformed v1 entry data" case above. `0` maps to
`1970-01-01T00:00:00`; negative values are accepted (pre-epoch, still UTC).

### Risk: 15
Author most likely prefers: `int(key)` + `utcfromtimestamp` as well; only an
odd fixture (fractional or negative epoch) could separate the readings.

## T17 — Root fields outside the v3 schema

### Spec Text
> | Entries | Move every object from `entries` to `episodes` |
> | `source_id` | Convert to `source` using ... |

### Alternatives
1. The migrated catalog is rebuilt with exactly the v3 root schema
   (`version`, `source`, `episodes`, `streams`, `clips`); `source_id`,
   `entries` and any other unknown root key disappear.
2. Unknown root keys are carried through, and only `source_id`/`entries` are
   removed.

### Choice
Alternative 1. "Convert to `source`" and "move to `episodes`" describe a
change of representation, not an addition, and the v3 root schema enumerates
its fields. Unknown keys *inside* an entry are, by contrast, preserved —
nothing asks for them to be dropped.

### Risk: 20
Author most likely prefers: the same rebuilt root; a fixture carrying an extra
root key (or asserting `source_id` is gone) is what would separate them.

## T18 — Whether `migrate` on a v3 vault rewrites `catalog.json`

### Spec Text
> | Effect on v3 | No-op; no backup written |

> | v3 reload | No additional history entry, no semantic modification, no
> backup write |

### Alternatives
1. Nothing is written at all: `catalog.json` keeps its exact bytes and no
   `catalog.bak` appears.
2. The catalog is re-serialized (semantically identical) but the backup step is
   skipped.

### Choice
Alternative 1. "No-op" is the stronger statement, and skipping the backup while
still rewriting would leave no recovery path for a write that goes wrong.

### Risk: 10
Author most likely prefers: the same, since "no backup written" is only easy to
guarantee by not writing.

## T19 — `version` values below `1`

### Spec Text
> | `version` greater than `3` | Version-related error to stderr; exit
> non-zero; no migration; no modification |

### Alternatives
1. Any integer version outside `{1, 2, 3}` — including `0` and negatives — is a
   version error.
2. Only `> 3` is an error; `0` or negative falls through to some other failure
   (or is treated as v1).

### Choice
Alternative 1. The Supported Versions table enumerates the whole supported set;
anything else is unsupported, and the error class ("version-related") is the
informative one.

### Risk: 8
Author most likely prefers: the same, though a `version: 0` fixture is unlikely
to appear at all.

## T20 — Whether migration touches static fields

### Spec Text
> | `id` | string | Unique identifier |
> | `published` | string | ISO 8601 datetime |

and the migration tables, which list only `source`, entry placement, history
keys, `removed`, `annotations` and `version`.

### Alternatives
1. `id`, `published`, `width` and `height` are copied verbatim by migration —
   no re-normalization of `published`.
2. `published` is normalized the way `sync` normalizes source values (date-only
   gaining `00:00:00`, timezone suffix dropped).

### Choice
Alternative 1. The migration tables are exhaustive about what changes, and a
legacy `published` is already stated to be ISO 8601; rewriting it would be a
"semantic modification" the determinism section warns against.

### Risk: 20
Author most likely prefers: verbatim copying too; only a legacy fixture with a
date-only or `Z`-suffixed `published` would show the difference.

## T21 — Backfilling `annotations` on existing v3 entries

### Spec Text
> | `annotations` | Add `[]` to every entry |   (migration only)

> | Entries created by `sync` | Written in v3 shape, with `annotations` as
> `[]` |

### Alternatives
1. `annotations` is added by migration and by entry creation only; a v3 entry
   already on disk that lacks `annotations` is left exactly as it is.
2. Every load backfills `annotations: []` into any entry missing it.

### Choice
Alternative 1. The two rules that add `annotations` are both about *new* data
(a migrated entry, a created entry); the v3 reload rule forbids semantic
modification, so a native catalog is passed through untouched. Existing
`annotations` values are likewise preserved, never reset — migration only adds
the field to v1/v2 entries, which by definition do not have one.

### Risk: 25
Author most likely prefers: also preserving; but an implementation that
normalizes entries on load would backfill, which a fixture with a hand-written
v3 entry missing `annotations` would expose.

## T22 — The migration timestamp itself

### Spec Text
> | Migration-added timestamp scope | Each migration-added `removed` timestamp
> must be ISO 8601; cross-entry equality is not required |

### Alternatives
1. One timestamp computed once per migration run and shared by every entry
   (equality is not required, but it is harmless and deterministic), taken from
   the local wall clock like the sync timestamp.
2. A fresh `datetime.now()` per entry.

### Choice
Alternative 1: one timestamp per run, `datetime.now()` truncated to the second,
formatted `YYYY-MM-DDTHH:MM:SS` (consistent with T12). When `sync` follows a
migration in the same run, the sync timestamp is still forced strictly newer
than every key in the catalog, so the migration-added `removed: false` is never
overwritten.

### Risk: 5
Author most likely prefers: the same; the spec explicitly declines to test
cross-entry equality, so only the ISO shape is checkable.

## T23 — Entry order after migration

### Spec Text
> | Entries | Move every object from `entries` to `episodes` |
> | Categories | Preserve `episodes`, `streams`, and `clips` placement |

### Alternatives
1. Migration preserves the on-disk order of entries within each category; the
   published-descending sort is applied only by `sync`, which already sorts.
2. Migration also re-sorts every category into the catalog's canonical
   ordering.

### Choice
Alternative 1. "Move" and "preserve placement" are order-neutral phrasings of a
structural change, and the determinism section forbids other semantic
modification on migration.

### Risk: 25
Author most likely prefers: possibly reading 2, if their migration funnels
through the same normalizer `sync` uses; a v1 fixture whose `entries` are not
already in published-descending order would separate them.
