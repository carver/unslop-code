# AMBIGUITIES

Numbered record of places where the `mvault` spec admits more than one
conforming reading, the interpretation chosen here, and the risk that the
spec author's own implementation (and therefore the hidden tests) reads it
differently.

---

## T1. Location of `catalog.bak`

### Spec Text
> | Backup path | `catalog.bak` |

and

> | Catalog path | `<name>/catalog.json` |

### Alternatives
1. The backup lives beside the catalog, at `<name>/catalog.bak`.
2. The backup is written to the process working directory, at `./catalog.bak`.

### Choice
`<name>/catalog.bak`. The catalog path row spells out the vault prefix
explicitly (`<name>/catalog.json`) while the persistence table names files
relative to the thing being backed up; a backup of a per-vault file that
landed outside the vault would collide between vaults synced from the same
directory.

### Risk: 3

Most likely alternative preferred by the author: none meaningful; a
cwd-relative backup would break multi-vault usage.

---

## T2. Whether `init` writes a backup

### Spec Text
> | Backup trigger | Before every write to existing `catalog.json` |

### Alternatives
1. `init` never produces `catalog.bak`, because it only ever writes a
   catalog into a freshly created directory where none existed.
2. `init` always produces a `catalog.bak`.

### Choice
No backup on `init`. The trigger is explicitly "before every write to
*existing* `catalog.json`", and `init` refuses to run at all when the vault
directory already exists, so no pre-write catalog can exist.

### Risk: 2

Most likely alternative preferred by the author: none; the word "existing"
is decisive.

---

## T3. Normalization of `published` values that carry a timezone or fractional seconds

### Spec Text
> | `published` | string | ISO 8601 datetime or date-only text |

> | Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix |
> | Date-only source values | Normalize to `00:00:00` time component |

### Alternatives
1. Normalize every `published` value to `YYYY-MM-DDTHH:MM:SS`: pad a
   date-only value with `T00:00:00`, and drop any timezone suffix and
   fractional part from a full datetime *without* shifting the clock time.
2. Convert offset-bearing datetimes to UTC first, then drop the suffix
   (so `2024-03-01T12:00:00+02:00` is stored as `2024-03-01T10:00:00`).
3. Only date-only values are touched; anything containing a `T` is stored
   verbatim, suffix included.

### Choice
Alternative 1. The determinism table states one canonical datetime text for
the whole program — `YYYY-MM-DDTHH:MM:SS` without timezone suffix — which
reads as a formatting rule ("render without the suffix"), not as a
timezone-conversion rule; no row anywhere mentions converting to UTC or any
other zone. Truncation also keeps the stored text a prefix of the source
text, which keeps the ordering key (`published`, compared as text) agreeing
with the source's own ordering for same-zone data.

### Risk: 22

Most likely alternative preferred by the author: alternative 3 — the author's
fixtures most likely use plain suffix-free `YYYY-MM-DDTHH:MM:SS` values plus
date-only values, and their code may simply pass through anything containing
a `T`, which is indistinguishable from this choice unless an offset-bearing
fixture is tested.

---

## T4. Scope of the "strictly increasing" sync timestamp check

### Spec Text
> | Collision handling | When a new history entry would reuse an existing or non-newer second, advance to a strictly later second before writing |

> | Sync timestamps | Reflect sync execution time and remain strictly increasing whenever new history entries are appended |

### Alternatives
1. One timestamp per `sync` run, chosen once as
   `max(wall clock now, latest key anywhere in the catalog + 1s)`, and used
   for every history entry appended by that run.
2. A per-field check: each field's new key is compared only against that
   field's own latest key, so a single run can write different timestamps
   to different fields.
3. A per-entry check, scoped to the latest key within one entry.

### Choice
Alternative 1. "Sync timestamps" is phrased as a property of a sync (not of
a field), and a vault-wide monotonic clock is the only reading under which
"remain strictly increasing" holds for the catalog as a whole. It also makes
one sync's appends share a single key, which is what makes "set `removed` to
`false` at sync timestamp" (singular, shared with the other five fields on
first observation) well defined.

### Risk: 12

Most likely alternative preferred by the author: alternative 2 — it differs
only when one field's history already extends past another's, which needs a
hand-crafted catalog to observe.

---

## T5. Whether a successful `sync` that changes nothing still rewrites the catalog

### Spec Text
> | Backup trigger | Before every write to existing `catalog.json` |
> | Success effect | Update catalog with new, changed, removed, and restored entries |

### Alternatives
1. Every successful `sync` writes the catalog (and therefore refreshes
   `catalog.bak`), even when no history entry was appended.
2. `sync` writes only when something actually changed, leaving
   `catalog.json` and `catalog.bak` untouched on a no-op sync.

### Choice
Alternative 1. The spec never describes a "no write" path, and an
unconditional write keeps the ordering contract enforced on every run
(including for catalogs edited by hand). Under this choice a second,
identical sync still produces a `catalog.bak` byte-identical to the current
`catalog.json`, which satisfies alternative 2's observable expectations for
the catalog contents.

### Risk: 25

Most likely alternative preferred by the author: alternative 2 — a test that
asserts no `catalog.bak` appears after a first-ever sync of a freshly
`init`ed vault would distinguish them, since under this choice the initial
empty catalog gets backed up.

---

## T6. What makes a vault "invalid" for `sync`

### Spec Text
> | Missing or invalid vault | Error to stderr including `<name>`; exit non-zero |

### Alternatives
1. Strict: the directory must exist, contain a readable `catalog.json` that
   parses to a JSON object with `version == 3`, a string `source`, and list
   values for `episodes`, `streams` and `clips`.
2. Lenient: only require parseable JSON with a usable `source`; tolerate a
   missing/other `version` and missing category arrays (treating them as
   empty).

### Choice
Alternative 1. The root-schema table states required *values*, not merely
required keys (`version` must be `3`), so a catalog that violates it is not
a "valid vault". Validation happens before the network request, so an
invalid vault is reported as a vault error rather than a fetch failure.

### Risk: 18

Most likely alternative preferred by the author: a middle reading that
accepts any integer `version` — a fixture that corrupts only the version
number would then expect success rather than an error.

### Resolution (legacy-catalog spec)
**Refined.** Versions `1` and `2` are now valid inputs rather than invalid
vaults: the version check accepts `1`, `2` and `3`, and anything else (missing,
non-integer, or outside that set) is still a hard error. The rest of the strict
reading (string `source`, array categories) still applies to the catalog after
in-memory migration.

---

## T7. Matching an existing entry: by `id` alone, or by category and `id`

### Spec Text
> | First observation | Add entry to matching category; ... |
> | `id` | string | Unique identifier |

### Alternatives
1. Entries are matched per category: source `episodes` are reconciled
   against catalog `episodes`, and so on. An id that moves between
   categories is treated as removed from the old one and newly observed in
   the new one.
2. Entries are matched by `id` across all categories, and a category change
   relocates the existing entry (carrying its history with it).

### Choice
Alternative 1. Every update rule is expressed relative to "matching
category", and "Entry absent from current source" is naturally evaluated
per category list. Per-category reconciliation also preserves the
"never delete entry from `catalog.json`" rule literally.

### Risk: 8

Most likely alternative preferred by the author: alternative 2, but only a
fixture that deliberately moves one id between categories can tell them
apart.

---

## T8. Local fields that are not in the stored-field table

### Spec Text
> | Local-only fields | Source data does not include `removed` or `annotations` |

### Alternatives
1. `annotations` is never created by `sync`, but any `annotations` (or other
   local key) already present on a stored entry is preserved across syncs.
2. `sync` creates an `annotations` field on every new entry.
3. `sync` rewrites entries from scratch, dropping unknown local keys.

### Choice
Alternative 1. The `entry` stored-fields table is exhaustive and does not
list `annotations`, so nothing should manufacture it; the mention exists to
say that such local state is never overwritten from source data, which only
has force if existing local state survives a sync.

### Risk: 15

Most likely alternative preferred by the author: alternative 2 — a fixture
asserting `"annotations" in entry` after a first sync would fail here; the
stored-fields table argues against it, and no row specifies what the initial
value would be.

### Resolution (legacy-catalog spec)
**Superseded: alternative 2 is now required.** The legacy-catalog spec says

> | Entries created by `sync` | Written in v3 shape, with `annotations` as `[]` |

and lists `annotations` as part of the native v3 entry shape, so `sync` now
writes `annotations: []` on every entry it creates, and migration adds `[]` to
every legacy entry. Existing `annotations` content is still never overwritten,
which was the original point of this entry.

---

## T9. Duplicate ids inside one source category array

### Spec Text
> | `id` | string | Unique identifier |

### Alternatives
1. Last occurrence in the array wins.
2. First occurrence wins.
3. Duplicates are a source metadata fetch failure.

### Choice
Alternative 1 (last wins). The schema calls ids unique, so duplicates are
undefined input rather than a specified error; folding the array into a map
in order is the ordinary implementation and yields last-wins. Rejecting the
payload would invent an error case the error table does not list.

### Risk: 20

Most likely alternative preferred by the author: alternative 2 — a
`setdefault`-style fold keeps the first occurrence; this is only observable
if a duplicate-id fixture exists at all, which is unlikely.

---

## T10. Booleans supplied where an integer is required

### Spec Text
> Each source entry must contain all nine fields above with the stated types.
> If any source entry is missing a required field or has the wrong type, `sync`
> must fail as a source metadata fetch failure and leave the vault unchanged.

### Alternatives
1. JSON `true`/`false` in `width`, `height`, `views` or `likes` is the wrong
   type and fails, even though Python's `bool` subclasses `int`.
2. Booleans pass the integer check (naive `isinstance(x, int)`).

### Choice
Alternative 1. The schema names the JSON types `integer` and `boolean`
separately (`removed` is the only boolean-valued field, and it is local-only),
so a JSON boolean is not a JSON integer.

### Risk: 30

Most likely alternative preferred by the author: alternative 2 — a plain
`isinstance(value, int)` check is the most common implementation and would
accept `true`; the difference shows only if a boolean-typed fixture exists.

---

## T11. Catalog JSON text formatting

### Spec Text
> | JSON object key order | Not part of the contract |
> | Backup content | Byte-for-byte copy of pre-write `catalog.json` |

### Alternatives
1. Pretty-printed with a fixed indent and a trailing newline.
2. Compact single-line JSON.

### Choice
Alternative 1 (`indent=2`, `ensure_ascii=False`, trailing newline). The spec
only constrains the backup to match the catalog bytes, which any stable
formatting satisfies; a pretty catalog is the friendlier local artifact and
the `init` example in the spec is itself pretty-printed. Tests should parse
the JSON rather than compare text.

### Risk: 5

Most likely alternative preferred by the author: none for parsed
comparisons; only a byte-exact fixture of `catalog.json` would care.

---

## T12. `published` values that are not parseable ISO text

### Spec Text
> | `published` | string | ISO 8601 datetime or date-only text |

### Alternatives
1. Any string is accepted for the type check (the schema demands `string`);
   an unparseable value is stored verbatim and sorts as text.
2. An unparseable `published` is a source metadata fetch failure.

### Choice
Alternative 1. The fetch-failure rule is scoped to a missing field or "the
wrong type", and the stated type is `string` — so `"not a date"` is
type-correct. Storing it verbatim keeps `sync` total, and text ordering still
gives a deterministic entry order.

### Risk: 12

Most likely alternative preferred by the author: alternative 2, if their
normalizer parses eagerly and lets the exception fall into the fetch-failure
handler.

---

## T13. Static fields when a later source payload changes them

### Spec Text
> | Static | `id` | string | Source identifier |
> | Static | `published` | string | Original publication datetime |
> | Static | `width` | integer | Pixel width |
> | Static | `height` | integer | Pixel height |

and the update rules, which mention only tracked fields:

> | Existing entry, changed tracked value | Append new history entry at sync timestamp |

### Alternatives
1. Static fields are written once, on first observation, and later syncs never
   touch them — a source that changes `width` or `published` is ignored for
   those fields.
2. Static fields are refreshed from the source on every sync (overwritten in
   place, with no history kept).

### Choice
Alternative 1. The field group is literally named "Static", `published` is
described as the *original* publication datetime, and the update-rule table
defines a per-field behavior only for tracked fields — a changing static
field has no specified behavior, so the conservative reading is that it is
not re-derived. This also keeps the ordering key stable across syncs.

### Risk: 30

Most likely alternative preferred by the author: alternative 2 — an
implementation that rebuilds the entry's static block from the source entry
on each pass would overwrite silently, and a fixture that bumps `width`
between syncs would then expect the new value.

---

## T14. Chatter on stdout for successful commands

### Spec Text
> | Invocation | Output Stream | Exit Code | Required Result |

(The stream column is specified only for `--help` and for the error rows.)

### Alternatives
1. Successful `init`/`sync` may print a short human-readable summary to
   stdout.
2. Successful commands print nothing at all.

### Choice
Alternative 1, with all diagnostics kept off stdout: errors go to stderr
only, and success output is one line. Nothing in the spec constrains stdout
for successful subcommands, and a silent CLI gives the operator no feedback
that a sync actually ran.

### Risk: 8

Most likely alternative preferred by the author: alternative 2, if a fixture
asserts `stdout == ""` after a successful sync; no row requires that.

---

## T15. When a legacy `sync` persists the migration

### Spec Text
> | Save timing | Save migrated v3 catalog immediately |

> | Trigger | `migrate` command or `sync` on a v1/v2 vault |

and, from the `sync` on Legacy Vaults table:

> | v1 vault | Auto-migrate to v3 in memory, apply sync updates, write v3 catalog to disk |
> | Backup before write | Standard backup rules apply; backup contains the **original** pre-migration catalog |

### Alternatives
1. One write per legacy `sync`: the migration stays in memory, the source is
   fetched, updates are applied, and a single write (preceded by a single
   backup of the original v1/v2 file) persists the result. A `sync` that fails
   — unreachable source, malformed payload — leaves the legacy `catalog.json`
   on disk untouched.
2. Two writes: the migration is saved "immediately" at load time (backing up
   the original), and the sync result is written again at the end (backing up
   the freshly migrated v3 file). A failed fetch still leaves a migrated v3
   catalog on disk.

### Choice
Alternative 1. The sync row says the backup contains the *original*
pre-migration catalog; under alternative 2 the last backup written by the run
holds the already-migrated v3 snapshot, contradicting that row. "Save
immediately" then reads as "the migrated form is what gets persisted by this
run, with no second `migrate` step required", which the single write satisfies.
It also keeps the existing rule that a failed `sync` leaves the vault unchanged.

### Risk: 35

Most likely alternative preferred by the author: alternative 2 — a
`load()`-time "migrate and save" helper is the obvious implementation of the
Migration Persistence table, and a fixture that makes the source fetch fail on
a v1/v2 vault and then asserts the on-disk catalog is v3 would distinguish them.

---

## T16. How strict "malformed v1 or v2 entry data" is

### Spec Text
> | Malformed v1 or v2 entry data | Error to stderr; exit non-zero; leave `catalog.json` unchanged |

together with the Version 1 / Version 2 Entry Schema tables, which list `id`,
`published`, `width`, `height` and five history objects with stated value types.

### Alternatives
1. Strict: an entry must satisfy its version's entry-schema table — all nine
   fields present, `id`/`published` strings, `width`/`height` integers, the five
   history fields objects whose values match the stated types, and (for v1)
   every history key parseable as UNIX epoch seconds. Anything else is
   malformed.
2. Structural only: fail on what the migration code itself cannot process — a
   non-object entry, a history field that is not an object, or a v1 key that
   does not parse as an integer — and silently accept wrong value types or a
   missing `width`.
3. Lenient: accept anything that is a JSON object with an `id`, migrating
   whatever fields are present.

### Choice
Alternative 1. The spec gives a per-version entry schema *and* a dedicated
error row for entry data that does not match it, so the schema table is the
definition of well-formed. Strictness only rejects inputs that already violate
the spec's own tables, so conforming fixtures are unaffected.

### Risk: 35

Most likely alternative preferred by the author: alternative 2 — a migration
written as a dict comprehension over the history fields raises naturally on a
non-object entry, a non-dict history and an unparseable epoch key, but never
inspects `width` or history *values*; a fixture with, say,
`"views": {"1718444400": "many"}` would then be expected to migrate cleanly.

---

## T17. Missing arrays and extra keys in a legacy catalog

### Spec Text
> | Missing categories | Create empty `streams` and `clips` arrays |

> | Categories | Preserve `episodes`, `streams`, and `clips` placement |

> | `entries` | array | All entries in a single flat list |

### Alternatives
1. Missing array-valued keys are filled in: a v1 catalog without `entries`
   migrates to empty categories, and a v2 catalog missing one of the three
   category arrays gets an empty array for it. A key present with a non-array
   value is malformed.
2. Every array named by the version's schema must be present; a v2 catalog
   without `clips` is an error.

### Choice
Alternative 1. The only rule the spec gives about an absent category is "create
empty" (for v1), so extending the same tolerance to v2 is the consistent
reading; a wrong-typed value is still rejected because the schema names the
type. Legacy-only *top-level* keys do not survive: the migrated catalog is
rebuilt as `version`/`source`/`episodes`/`streams`/`clips`, so `source_id` and
`entries` are gone after a v1 migration (the v3 root schema does not list them).

### Risk: 20

Most likely alternative preferred by the author: for the missing-v2-category
case, an error (their v2 reader may index `catalog["clips"]` directly); a
fixture omitting a v2 category is the only way to see the difference. An author
who copies the source dict instead of rebuilding it would also leave a stale
`source_id` key in the migrated catalog.

---

## T18. `version` values below `1`

### Spec Text
> | `version` greater than `3` | Version-related error to stderr; exit non-zero; no migration; no modification |

### Alternatives
1. Any integer outside `{1, 2, 3}` — including `0` and negatives — is a
   version-related error.
2. Only values greater than `3` are errors; `0` or `-1` fall through to some
   other handling (e.g. treated as v1, or as a generic invalid catalog).

### Choice
Alternative 1. The Supported Versions table enumerates exactly `1`, `2`, `3`;
a catalog claiming `0` names no schema the loader can read, and reporting it as
a version error matches the "no migration, no modification" outcome of the
neighbouring rows.

### Risk: 10

Most likely alternative preferred by the author: the same error, though their
message may be phrased as "unsupported" only for `> 3`; a `version: 0` fixture
asserting the word "version" on stderr is the only sensitive case.

---

## T19. Clock used for the migration timestamp

### Spec Text
> | Migration-added timestamp scope | Each migration-added `removed` timestamp must be ISO 8601; cross-entry equality is not required |

> | v1 UNIX-epoch conversion | Convert each epoch-seconds key to `YYYY-MM-DDTHH:MM:SS` in UTC |

### Alternatives
1. The migration timestamp is the local wall clock, formatted
   `YYYY-MM-DDTHH:MM:SS` — the same clock the sync timestamp uses.
2. The migration timestamp is UTC, matching the explicit UTC rule given for
   epoch-key conversion.

### Choice
Alternative 1. The UTC rule is stated only for converting v1 epoch keys, where a
zone is needed to make the conversion deterministic; the migration timestamp row
requires only "ISO 8601". Using the same clock as sync timestamps keeps a
legacy vault's history monotonic when a `sync` immediately follows a migration.

### Risk: 25

Most likely alternative preferred by the author: alternative 2 (a
`datetime.utcnow()`-style stamp). Only observable when the test machine is not
on UTC, and only by a test that compares the stamp against its own clock.

---

## T20. Entry keys not named by the legacy entry schema

### Spec Text
> | `removed` | Add `{<migration-timestamp>: false}` to every entry |
> | `annotations` | Add `[]` to every entry |

### Alternatives
1. Migration preserves every key already on a legacy entry and adds `removed`
   and `annotations` — so a hand-added local key survives.
2. Migration rebuilds each entry from the schema fields only, dropping anything
   unrecognized.

### Choice
Alternative 1. The migration tables are phrased entirely as additions and
conversions ("Add", "Convert", "Move", "Preserve"); nothing licenses discarding
entry data. A legacy entry that already carries `annotations` keeps its
contents, and only a missing or non-array `annotations` becomes `[]`.

### Risk: 12

Most likely alternative preferred by the author: alternative 2, visible only
with a fixture whose legacy entry carries an extra key.

---

## T21. Whether `sync` back-fills `annotations` on entries it did not create

### Spec Text
> | Entries created by `sync` | Written in v3 shape, with `annotations` as `[]` |

### Alternatives
1. Only entries `sync` creates get `annotations: []`; an existing entry is left
   exactly as found (migration is what adds `annotations` to legacy entries).
2. Every entry touched by a sync is normalized to the full v3 shape, so a v3
   entry that somehow lacks `annotations` gains `[]`.

### Choice
Alternative 1. The row is explicitly scoped to entries *created by* `sync`, and
the local-only rule that source data never overwrites `annotations` argues for
leaving existing entries alone. After migration every entry has `annotations`
anyway, so the two readings differ only for a hand-edited v3 catalog.

### Risk: 20

Most likely alternative preferred by the author: alternative 2, if their writer
normalizes each entry on the way out; a fixture with a hand-made v3 entry
missing `annotations` would show it.

---

## T22. The timestamp `sync` uses on a just-migrated legacy vault

### Spec Text
> | v1 vault | Auto-migrate to v3 in memory, apply sync updates, write v3 catalog to disk |

> | Sync timestamps | Reflect sync execution time and remain strictly increasing whenever new history entries are appended |

### Alternatives
1. Two distinct stamps: migration stamps `removed` with its own
   migration-timestamp, and the sync stamp is then advanced to a strictly later
   second (normally migration time + 1s) because the collision rule sees the
   migration key.
2. One stamp for the whole run: the migration reuses the sync timestamp, so the
   migration-added `removed` key and any appended history key are identical.

### Choice
Alternative 1. The spec names a "migration-timestamp" separately from the sync
timestamp, and the collision rule is stated unconditionally, so a migration key
written at the current second forces the sync key one second later. Under both
readings the migration-added `removed` history stays a single `false` entry.

### Risk: 25

Most likely alternative preferred by the author: alternative 2, if their sync
computes its timestamp before loading; a fixture asserting that a value changed
by the same sync shares a key with the migration-added `removed` entry would
distinguish them.

---

## T23. `published` text during a v1 migration

### Spec Text
> | History keys | Convert every UNIX-epoch string key to ISO 8601 format |

(The v1→v3 table mentions no other field conversion.)

### Alternatives
1. `published` is copied verbatim; only history *keys* are converted.
2. `published` is re-normalized through the same rules `sync` applies to source
   values (date-only padded to `T00:00:00`, suffixes dropped).

### Choice
Alternative 1. The migration table enumerates exactly what changes, and
`published` is not on it; the v1 schema already calls it an ISO 8601 datetime.

### Risk: 15

Most likely alternative preferred by the author: alternative 1 as well; a
fixture with a date-only v1 `published` is the only way to see a difference.
