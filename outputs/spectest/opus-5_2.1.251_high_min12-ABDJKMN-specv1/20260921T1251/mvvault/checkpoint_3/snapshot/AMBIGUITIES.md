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

### Annotation (later spec increment: `sync` phases)

The download-phase spec orders the metadata phase as "Load vault, optionally
fetch source metadata, update catalog history, persist metadata" and adds
"| Save timing | Metadata phase persists before successful `sync` returns |".
Persistence is listed *after* the fetch and is tied to a *successful* run,
which is alternative 1: one write, at the end of the metadata phase, and no
write at all when a failed fetch aborts the run. Revised risk: **20**.

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

---

## T24. Whether previews are tied to media candidates and to the per-category limit

### Spec Text
> | Preview | `<source>/preview/<entry_id>` | `<vault>/previews/` | Filename contains entry `id` |

> | Candidate selection | Only entries without a corresponding media file in `<vault>/media/` are candidates |

> | `--episodes=<n>` | non-negative integer | Maximum number of episode media downloads |

### Alternatives
1. One candidate list per category, selected by missing media; each selected
   candidate gets both its media and its preview fetched.
2. Previews are an independent pass: every entry missing a preview file in
   `<vault>/previews/` is fetched, uncapped, regardless of media state.
3. The preview is fetched only when the entry's media download succeeded.

### Choice
Alternative 1, with the preview skipped when `<vault>/previews/` already holds
a file whose name contains the id. Candidate selection is defined once, in
terms of media only, and the limits are described as caps on *media*
downloads; that only makes sense if the preview rides along with the media
candidate rather than forming a second, separately-capped population. Skipping
an already-present preview keeps repeat runs idempotent.

### Risk: 35

Most likely alternative preferred by the author: alternative 3 - guarding the
preview fetch behind a successful media fetch is a natural single-function
`download_entry()` shape, and a fixture where media 404s but the preview is
available would show a preview file under my reading and none under theirs.

---

## T25. How `<source>` is joined with `/media/<entry_id>`

### Spec Text
> | Media | `<source>/media/<entry_id>` | `<vault>/media/` | Filename contains entry `id` |

### Alternatives
1. Literal text concatenation: strip trailing `/` from `source`, then append
   `/media/<entry_id>`. A source of `https://host/api/source.json` yields
   `https://host/api/source.json/media/e1`.
2. `urllib.parse.urljoin(source, "media/" + entry_id)`, which discards the last
   path segment and yields `https://host/api/media/e1`.
3. Percent-encode the entry id before appending it.

### Choice
Alternative 1, without percent-encoding. The spec writes the remote path as a
literal template around `<source>`, and `urljoin` would silently drop part of
the configured source URL - surprising for a value the user set with `init`.
Ids in the schema are opaque strings, but every fixture-shaped id is already
URL-safe, so encoding would only change behavior for inputs that are not
tested.

### Risk: 15

Most likely alternative preferred by the author: alternative 1 as well; the
`urljoin` reading only diverges when the source URL ends in a file-like
segment, which their own fixtures may or may not do.

---

## T26. Extension derivation when `Content-Type` is unhelpful

### Spec Text
> | Media extension without override | Derive from HTTP `Content-Type` |

### Alternatives
1. Map the media type through a table plus `mimetypes.guess_extension`, so
   `audio/mpeg` becomes `mp3` and `image/jpeg` becomes `jpg`.
2. Take the subtype literally: `audio/mpeg` becomes `mpeg`, `image/jpeg`
   becomes `jpeg`.
3. Store no extension at all when the type is unknown.

### Choice
Alternative 1, falling back to the subtype (minus an `x-` prefix or a `+xml`
suffix) and finally to `bin` when nothing maps. "Derive from `Content-Type`"
describes a mapping, not a string slice, and `mimetypes` is the standard
library's answer to exactly this question. `Content-Type` parameters after `;`
are dropped before mapping.

### Risk: 35

Most likely alternative preferred by the author: alternative 2 -
`content_type.split("/")[-1]` is a one-liner, and the readings only agree for
`video/mp4`; a fixture serving `audio/mpeg` or `image/jpeg` would separate
them (`e1.mp3` vs `e1.mpeg`, `e1.jpg` vs `e1.jpeg`).

---

## T27. What counts as a partial-download artifact

### Spec Text
> | Candidate selection | ... A file matches if the name contains entry `id`, apart from partial downloads  |

> | Partial artifacts | Stale partial-download artifacts must not block a later successful download |

### Alternatives
1. A specific staging suffix, chosen by the implementation, is partial - and
   only that suffix.
2. A family of well-known staging names is treated as partial: `.part`,
   `.partial`, `.tmp`, `.download`, `.crdownload`, and dot-prefixed names.

### Choice
Alternative 2. Downloads are staged through `<vault>/media/<id>.part` and
renamed into place, so the local writer only ever produces `.part`; but the
rule exists to stop a *stale* artifact from masking a missing download, and a
stale artifact may have been left by a previous version of the tool. Accepting
the whole family is a superset of any single-suffix reading, so a fixture that
plants a partial under a different name still behaves as the spec requires.

### Risk: 12

Most likely alternative preferred by the author: alternative 1 with `.part`;
that only differs from this choice if a hidden fixture plants a file like
`e1.tmp` and expects it to count as a *complete* media file.

---

## T28. Retry count, and which download failures are transient

### Spec Text
> | Transient download failure | Retry, then warn to stderr after retries exhausted; continue with remaining entries |

> | Permanent download failure | Warning to stderr; continue with remaining entries |

### Alternatives
1. Three attempts total (two retries), no backoff sleep; HTTP 5xx plus 408,
   425 and 429 plus socket/DNS errors are transient, every other HTTP status
   is permanent.
2. Two attempts total (one retry), same classification.
3. Retry everything, including 404, since the spec does not say which failures
   are transient.

### Choice
Alternative 1. The spec distinguishes the two failure classes by name, so the
classification has to come from the HTTP status: 4xx means the server answered
definitively, 5xx and transport errors do not. Three attempts is the common
default and leaves the retry visible (more than one request) without making a
failing sync slow. No sleep is inserted, so a run against a dead asset stays
fast.

### Risk: 40

Most likely alternative preferred by the author: alternative 2 - one retry is
the smallest thing that satisfies "retry", and a fixture counting requests
against a permanently-503 asset would read 2 rather than 3.

---

## T29. Whether removed entries are download candidates

### Spec Text
> | Candidate selection | Only entries without a corresponding media file in `<vault>/media/` are candidates; A file matches if the name contains entry `id`, apart from partial downloads  |

### Alternatives
1. Every catalog entry without local media is a candidate, including entries
   whose latest `removed` value is `true`.
2. Entries currently marked `removed: true` are excluded, since their media is
   no longer offered by the source.

### Choice
Alternative 1. The selection rule is stated purely in terms of local file
presence, with no reference to `removed`; and archiving media for an entry
that has just disappeared upstream is the behavior a vault tool exists for.
A removed entry whose media really is gone simply produces a permanent-failure
warning, which the spec already tolerates.

### Risk: 25

Most likely alternative preferred by the author: alternative 2 - a fixture
that removes an entry from the source and then checks that `sync` does not
warn about it would distinguish the readings.

---

## T30. Whether the per-category limit counts attempts or successes

### Spec Text
> | Per-category limit | Download first `N` candidates in candidate order |

> | Per-category limit selection | First `N` candidates in candidate order |

### Alternatives
1. Take the first `N` candidates and attempt them; failures consume budget.
2. Keep attempting candidates until `N` media files have been stored
   successfully.

### Choice
Alternative 1. Both determinism rows phrase the limit as a slice of the
candidate list ("first `N` candidates"), not as a target number of files, and
a slice is computable before any request is made.

### Risk: 15

Most likely alternative preferred by the author: alternative 2, which would
show up in a fixture where the first candidate 404s and `--episodes=1` is
given: one file under that reading, none under this one.

---

## T31. `--skip-metadata` on a v1 or v2 vault

### Spec Text
> | `--skip-metadata` | flag | Skip source fetch and metadata update; run download phase against existing vault state |

> Because `sync` auto-migrates v1 and v2 vaults to v3 during the metadata phase, the download phase always operates against a v3 catalog.

### Alternatives
1. The migration happens in memory for the download phase's benefit, but
   nothing is written: with no metadata phase there is no metadata save, so a
   legacy `catalog.json` stays legacy on disk.
2. Loading a legacy vault always rewrites it as v3, even on a download-only
   run.

### Choice
Alternative 1. The quoted sentence attributes the migration to the *metadata
phase*, which `--skip-metadata` skips; and the persistence table ties every
save to the metadata phase. A download-only run therefore touches no catalog
at all, matching `digest`'s read-only stance toward vault files.

### Risk: 30

Most likely alternative preferred by the author: alternative 2, if their
loader migrates and saves in one step (see T15) - a fixture running
`sync --skip-metadata` on a v2 vault and then reading `version` would separate
them.

---

## T32. Digest category, group, and entry ordering

### Spec Text
> | Digest category order | Deterministic |

> | Digest group order | Deterministic |

> | Digest entry order | Deterministic |

### Alternatives
1. Categories in catalog order (`Episodes`, `Streams`, `Clips`); groups in the
   documented precedence order (Removals, Additions, Field updates); entries in
   catalog order within their group.
2. Entries sorted by title or by id; groups in some other fixed order such as
   Additions first.

### Choice
Alternative 1. "Deterministic" only forbids incidental ordering, so the orders
already named elsewhere in the spec are the ones to reuse: the category order
of the catalog schema, the priority order of the group-precedence table, and
the candidate/catalog order the download rules lean on for entries.

### Risk: 20

Most likely alternative preferred by the author: groups in
Additions/Removals/Field-updates order, which changes nothing about which
entries appear, only the order of the printed sections.

---

## T33. Which names appear in the field-update suffix

### Spec Text
> | Field-update suffix | Changed field names in parentheses after title |

> | Reappearance after removal (v3 only) | Indicate reappearance alongside any other changed fields |

### Alternatives
1. Only source-tracked field names (`title`, `description`, `views`, `likes`,
   `preview`) are listed, in tracked-field order, and a reappearance is shown
   as a separate `reappeared` marker at the head of the same parenthesis.
2. `removed` is treated as an ordinary changed field name and printed as
   `removed` when it flips back to `false`.
3. Reappearance is printed as its own group or its own line rather than inside
   the suffix.

### Choice
Alternative 1. The reappearance row says to indicate reappearance "alongside
any other changed fields", which places it in the same list as the field names
while distinguishing it from them - and "reappeared" reads to a human, where a
bare `removed` would say the opposite of what happened.

### Risk: 35

Most likely alternative preferred by the author: alternative 2, since
`removed` is a tracked field like any other and falls out of a generic
changed-field loop; a fixture asserting on the suffix text of a restored entry
would separate them.

---

## T34. What the post-sync "updated" count includes

### Spec Text
> | Counts reported | Added, removed, updated |

### Alternatives
1. `added` = entries first seen this run; `removed` = entries newly marked
   `removed: true`; `updated` = existing entries with any tracked-field change,
   including entries restored from `removed: true`.
2. Restorations are counted as additions (the entry is "back").
3. Restorations are counted in neither, so a restored entry is invisible.

### Choice
Alternative 1. Three buckets are offered for four things the sync engine
already distinguishes (new, changed, removed, restored), and a restoration is
a change to a tracked field of an entry that already existed - so it belongs
with updates. Counting it as an addition would double-count an entry that was
already added in an earlier run.

### Risk: 25

Most likely alternative preferred by the author: alternative 2, which a
fixture that removes an entry and then restores it upstream would separate
(`1 added, 0 removed, 0 updated` vs `0 added, 0 removed, 1 updated`).

---

## T35. What the digest trailing line says

### Spec Text
> | Trailing line | Metadata about the digest run |

> | Source reference | The trailing line includes the resolved source URL for the loaded vault version |

> | Digest trailing line | Deterministic format |

### Alternatives
1. Vault name, catalog version, resolved source URL, and the generation time.
2. The source URL alone.
3. Counts of the reported changes instead of the version.

### Choice
Alternative 1. Only the source URL is mandated; "metadata about the digest
run" invites the version actually loaded (which changes how everything above
was computed) and the run time. The determinism row constrains the *format*,
not the values, and the "Wall-clock usage outside digest trailing line" row
implies wall-clock is expected to appear precisely here.

### Risk: 10

Most likely alternative preferred by the author: a trailing line without a
timestamp, which matters only to a test that asserts two digest runs produce
byte-identical stdout.

---

## T36. Whether `--format` affects the preview

### Spec Text
> | `--format=<str>` | string | Override media download format and output extension |

> | Media with format override | `<source>/media/<entry_id>.<format>` | `<vault>/media/` | Extension = format string |

### Alternatives
1. The override applies to media only: the preview URL is never suffixed and
   the preview extension always comes from its own `Content-Type`.
2. The override applies to every downloaded asset.

### Choice
Alternative 1. Both rows name media explicitly, and the sources-and-targets
table gives the format-suffixed remote path only for the media row while
leaving the preview row unsuffixed.

### Risk: 12

Most likely alternative preferred by the author: alternative 1 as well; the
tables are hard to read any other way.

---

## T37. `--episodes=0`

### Spec Text
> | `--episodes=<n>` | non-negative integer | Maximum number of episode media downloads |

> | Omitted limit | No limit for that category |

### Alternatives
1. `0` is a real maximum: no media is downloaded for that category.
2. `0` is treated as "unset" and means no limit.

### Choice
Alternative 1. Zero is explicitly inside the accepted value range, and the
"no limit" behavior is attached to the option being *omitted*, not to any
particular value.

### Risk: 5

Most likely alternative preferred by the author: none meaningful; a falsy-check
bug would produce alternative 2, but the spec does not support it.

---

## T38. How strict `digest` is about catalog contents

### Spec Text
> | Input | Existing vault of any supported version |

> | `digest` on vault with unsupported version | stderr | non-zero | Message includes version value |

### Alternatives
1. `digest` validates only what it needs: the vault exists, the catalog parses,
   and the version is supported. Entries with missing or oddly-typed tracked
   fields are treated as having no history for those fields.
2. `digest` runs the same entry validation as `sync`/`migrate` and errors on
   malformed legacy entries.

### Choice
Alternative 1. The error table lists exactly two `digest` failures - missing
vault and unsupported version - and the command is described as a read-only
report over "tracked-field history". A reporting command that refuses to
report because one entry lacks a field would be less useful than one that
reports what it can.

### Risk: 20

Most likely alternative preferred by the author: alternative 2, if `digest`
shares a loader with the other commands; a fixture with a malformed legacy
entry would separate the readings.

---

## T39. stdout of a `sync` run without a metadata phase

### Spec Text
> | Trigger | Successful `sync` run that includes metadata phase |

> | Output stream | stdout |

### Alternatives
1. A download-only run prints a short completion line, with no change counts.
2. A download-only run prints nothing at all on stdout.

### Choice
Alternative 1. The trigger row withholds the *change summary* from runs
without a metadata phase; it does not require silence, and the existing
commands all acknowledge success on stdout. The line deliberately contains no
added/removed/updated counts so it cannot be mistaken for the summary.

### Risk: 10

Most likely alternative preferred by the author: alternative 2, which only
matters to a test asserting empty stdout for `--skip-metadata`.

---

## T40. "Warning per affected entry" when both assets fail

### Spec Text
> | Permanently unavailable content during download | stderr | `0` | Warning per affected entry; continue |

### Alternatives
1. One warning per failed *asset*, so an entry whose media and preview both
   fail produces two warnings.
2. Exactly one warning per entry, aggregating both assets.

### Choice
Alternative 1. Media and preview are separate downloads with separate URLs and
separate failure reasons, and a per-asset warning names which one is missing.
"Per affected entry" is there to say the run does not stop at the first
failure, not to cap the line count.

### Risk: 15

Most likely alternative preferred by the author: alternative 1 as well; a test
would have to count stderr lines exactly to notice the difference.
