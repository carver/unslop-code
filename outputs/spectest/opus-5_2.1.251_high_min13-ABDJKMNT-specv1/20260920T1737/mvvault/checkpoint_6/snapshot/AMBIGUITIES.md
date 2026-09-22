# Ambiguities

Numbered record of spec under-specification, the reading chosen for this
implementation, and the risk that the spec author's own implementation (and the
hidden tests written against it) reads it differently.

## T1: Location of `catalog.bak`

### Spec Text
> | Backup path | `catalog.bak` |

### Alternatives
1. The backup lives inside the vault directory: `<name>/catalog.bak`, next to
   `<name>/catalog.json`.
2. The backup is written to the process working directory as `catalog.bak`.

### Choice
`<name>/catalog.bak`. Every other path in the spec (`<name>/catalog.json`) is
vault-relative and the backup is described as a copy of "pre-write
`catalog.json`", so it belongs beside the file it shadows. A working-directory
backup would collide between vaults.

### Risk: 4
If wrong, the author writes `catalog.bak` into the current working directory.

## T2: Normalizing publication text that carries a timezone or sub-second part

### Spec Text
> | Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix |
> | Date-only source values | Normalize to `00:00:00` time component |

### Alternatives
1. Normalize every `published` value to `YYYY-MM-DDTHH:MM:SS`: date-only text
   gains `T00:00:00`, and `Z`/`+01:00` suffixes and fractional seconds are
   dropped (wall-clock text kept, no timezone conversion).
2. Only date-only values are touched; any other string is stored verbatim, so
   `2024-05-01T10:00:00Z` stays with its `Z`.
3. Offsets are converted to UTC before the suffix is dropped.

### Choice
Alternative 1. The determinism table states the datetime text format for the
program as a whole ("without timezone suffix", "No locale-sensitive
formatting anywhere"), so a stored `published` that still ends in `Z` would
violate it. Conversion to UTC (3) is rejected because nothing in the spec
mentions timezone arithmetic, and shifting the hour would also silently change
entry ordering. Unparseable text is stored unchanged.

### Risk: 30
If wrong, the author most likely special-cases only the date-only form and
stores every other `published` string exactly as received.

## T3: Static fields when an existing entry is seen again with different values

### Spec Text
> | Static | `published` | string | Original publication datetime |
> | Existing entry, unchanged tracked value | No new history entry for that field |

### Alternatives
1. Static fields (`id`, `published`, `width`, `height`) are captured at first
   observation and never rewritten.
2. Static fields are overwritten from the source on every sync; only tracked
   fields carry history.

### Choice
Alternative 1. The field group is literally named "Static" and `published` is
documented as the *original* publication datetime; the sync update rules only
ever describe writing history for tracked fields.

### Risk: 28
If wrong, the author refreshes the static fields from the source each sync, so
a fixture that changes `width` or `published` between syncs expects the new
value (and a re-sorted catalog).

## T4: Source response missing one of the three category arrays

### Spec Text
> | Source response shape | JSON object with `episodes`, `streams`, and `clips` arrays |
> Source metadata fetch failure ... malformed source entries are included in this case

### Alternatives
1. A response lacking any of the three arrays (or holding a non-array there) is
   a source metadata fetch failure; the vault is left unchanged.
2. A missing array is treated as empty, so every stored entry of that category
   is marked `removed: true`.

### Choice
Alternative 1. The response shape is stated as a requirement, and the failure
row explicitly stretches "fetch failure" to cover malformed payload content
rather than silently reinterpreting it. Marking a whole category removed on a
truncated payload would also destroy information the source never denied.

### Risk: 30
If wrong, the author reads each category with a defaulted empty list and marks
that category's entries removed.

## T5: Scope of the strictly-increasing sync timestamp

### Spec Text
> | Collision handling | When a new history entry would reuse an existing or non-newer second, advance to a strictly later second before writing |
> | Sync timestamps | Reflect sync execution time and remain strictly increasing whenever new history entries are appended |

### Alternatives
1. One timestamp per sync run, chosen as `max(now, newest timestamp anywhere in
   the catalog + 1s)`, used for every append in that run.
2. Per-field resolution: each history dict advances independently, so fields
   written in the same run can land on different seconds.
3. Per-entry resolution.

### Choice
Alternative 1. A single run-wide timestamp keeps one sync legible as one point
in time, and taking the maximum over the whole catalog is what makes sync
timestamps "strictly increasing" across runs rather than merely within one
field. Per-field advancement (2) would let two fields of the same entry
disagree about when the sync happened.

### Risk: 22
If wrong, the author advances each history dict independently against its own
newest key, which differs when two syncs land in the same second and a field
was skipped by the earlier one.

## T6: Whether a sync that changes nothing still rewrites the catalog

### Spec Text
> | Backup trigger | Before every write to existing `catalog.json` |

### Alternatives
1. A successful sync always rewrites `catalog.json`, so `catalog.bak` always
   appears (and is refreshed) after the first sync.
2. A sync that produces no new history entry skips the write entirely, leaving
   no backup behind.

### Choice
Alternative 1. The spec ties the backup to writes without ever describing a
"no-op sync" branch, and always writing also guarantees the ordering rule is
applied to the stored file. Content is unchanged either way, so the only
observable difference is the presence of `catalog.bak`.

### Risk: 14
If wrong, the author skips the write when nothing changed and a fixture asserts
`catalog.bak` is absent after an idempotent second sync.

## T7: What makes a vault "invalid"

### Spec Text
> | `sync` with invalid vault | stderr | non-zero | Message includes vault name |

### Alternatives
1. Invalid means: no `catalog.json`, unparseable JSON, a non-object root, a
   missing/mistyped `source`, a missing/mistyped category array, or a `version`
   that is not the integer `3`.
2. Only unreadable or unparseable catalogs count; anything that parses is
   accepted and repaired as needed.

### Choice
Alternative 1, minus repair. The root schema table gives required types for all
five fields, so a catalog violating it cannot be synced coherently. `version`
is checked against `3` because the schema fixes it as a required value and no
migration path is described.

### Risk: 20
If wrong, the author validates only the three category arrays (or nothing
beyond JSON parsing) and accepts a catalog whose `version` differs.

### Note (multi-version spec)
Superseded in part: `version` is now accepted when it is `1`, `2` or `3`, and a
v1/v2 catalog is upgraded in memory before the root schema is checked. Every
other validation in this entry still applies to the upgraded catalog.

## T8: Booleans supplied where an integer is required

### Spec Text
> If any source entry is missing a required field or has the wrong type, `sync`
> must fail as a source metadata fetch failure

### Alternatives
1. `true`/`false` is the wrong type for `width`, `height`, `views` and `likes`
   and triggers the failure.
2. Python's `bool` subclasses `int`, so a naive `isinstance` check accepts it.

### Choice
Alternative 1. JSON distinguishes booleans from numbers, and the schema names
those fields integer; accepting `true` as a view count would store a boolean in
a tracked history documented as holding integers.

### Risk: 12
If wrong, the author used a bare `isinstance(value, int)` and a fixture feeding
`"views": true` expects the sync to succeed.

## T9: An id that moves between categories

### Spec Text
> | First observation | Add entry to matching category |
> | Entry absent from current source | Append `removed: true` at sync timestamp |

### Alternatives
1. Categories are independent namespaces: the old category's copy is marked
   removed and a fresh entry is created in the new category.
2. The entry object is relocated between categories, carrying its history.

### Choice
Alternative 1. Matching is described per category ("Add entry to matching
category"), and "absent from current source" is naturally evaluated within the
category the entry is stored in. Relocation is never mentioned, and it would
have to invent a rule for the `removed` history across the move.

### Risk: 15
If wrong, the author matches ids across the whole catalog and moves the entry.

## T10: Unknown fields already present in a stored entry

### Spec Text
> | Local-only fields | Source data does not include `removed` or `annotations` |

### Alternatives
1. Fields the spec does not manage (notably `annotations`) are preserved as-is
   through a sync.
2. Each entry is rebuilt from the documented field list, dropping anything else.

### Choice
Alternative 1. `annotations` is named as a local-only field even though nothing
creates it, which only makes sense if locally added data survives syncing. The
implementation never creates `annotations` itself.

### Risk: 10
If wrong, the author rebuilds entries and drops unknown keys.

### Note
Extra fields on *source* entries are ignored rather than stored: the stored
field table is exhaustive.

### Note (multi-version spec)
Partly superseded: "Entries created by `sync` | Written in v3 shape, with
`annotations` as `[]`" now requires `sync` to create `annotations`, so a new
entry gets `[]` rather than no field at all. Existing `annotations` are still
carried through untouched -- see [T21].

## T11: How `urllib.request` is called

### Spec Text
> | Source request | HTTP `GET` to vault `source` URL, made with `urllib.request` |

### Alternatives
1. `urllib.request.urlopen(url)` with the plain URL string, read inside a
   `with` block.
2. `urlopen(Request(url))`, which a test double would receive as an object.

### Choice
Alternative 1, and the body is decoded with `json.loads(response.read())` so a
double returning `bytes` or `str` both work. The tests in this repo drive a
real local HTTP server, which is agnostic to the choice.

### Risk: 12
If wrong, the author's test double inspects a `Request` object (e.g.
`request.full_url`) and receives a string instead.

## T12: Unknown subcommand and wrong argument counts

### Spec Text
> | `python mvault.py` | stderr | non-zero | Usage text |

### Alternatives
1. Any malformed invocation (unknown subcommand, missing or extra positional
   arguments) behaves like the no-subcommand case: usage text on stderr,
   non-zero exit.
2. Only the bare invocation is specified; others are free.

### Choice
Alternative 1, implemented with `argparse` so malformed invocations exit `2`
with usage on stderr. Application errors exit `1`.

### Risk: 5
If wrong, the author uses a different non-zero code, which the spec does not
constrain ("non-zero").

## T13: Duplicate ids inside one source category

### Spec Text
> | `id` | string | Unique identifier |

### Alternatives
1. Ids are declared unique, so on a duplicate the later occurrence is simply
   applied to the same entry (last one wins) without erroring.
2. A duplicate id is malformed source data and is a fetch failure.

### Choice
Alternative 1. Uniqueness is stated as a property of the source data, not as a
validation rule, and the failure list enumerates missing fields and wrong types
only.

### Risk: 12
If wrong, the author rejects duplicates as a source metadata fetch failure.

## T14: How deeply a stored catalog is validated before syncing

### Spec Text
> | `sync` with invalid vault | stderr | non-zero | Message includes vault name |
> | Tracked | `title` | history object | Values are strings |

### Alternatives
1. "Invalid" covers stored entries too: each entry must carry the four static
   fields with the documented types and six non-empty history objects whose
   keys parse as ISO 8601 datetimes.
2. Only the catalog root is checked; a structurally broken entry surfaces later
   as a crash (or is silently repaired).

### Choice
Alternative 1. The stored-field table is part of what makes a vault "valid",
and validating up front is what lets every failure be reported as a named-vault
error on stderr instead of a traceback. Unknown extra keys on an entry are
still accepted (see T10).

### Risk: 18
If wrong, the author validates only the catalog root, so a hand-written fixture
entry that omits, say, `removed` would be synced (and repaired) rather than
rejected.


## T15: Catalog versions below `1`

### Spec Text
> | `version` greater than `3` | Version-related error to stderr; exit non-zero; no migration; no modification |

### Alternatives
1. The supported set is exactly `{1, 2, 3}`, so `0`, `-1` and any other integer
   outside it is the same version-related error as `4`.
2. Only values strictly greater than `3` are errors, and `0` or a negative
   version falls through to some other handling (a generic schema error, or a
   crash).

### Choice
Alternative 1. The Supported Versions table enumerates `1`, `2` and `3`, and
nothing describes what a version `0` catalog would even look like; rejecting it
as a version error is the only reading that keeps "all supported versions"
meaningful. The message names the version either way.

### Risk: 12
If wrong, the author only checks `version > 3` and a `version: 0` fixture
produces a different (non-version) error message -- but still a non-zero exit.

## T16: A version 2 catalog missing one of the three category arrays

### Spec Text
> | `episodes` | array | Episode entries |
> | `streams` | array | Stream entries |
> | `clips` | array | Clip entries |
> | Missing categories | Create empty `streams` and `clips` arrays |

### Alternatives
1. A v2 catalog that omits a category is read as if that category were empty,
   exactly as the v1 rule fills in the categories v1 cannot express.
2. Omitting a category violates the v2 catalog schema, so the load fails the
   way a malformed v3 catalog does.

### Choice
Alternative 1. The migration path is naturally written as "read each of the
three categories, add the local fields, write them back", which defaults a
missing one to empty; the error table lists only *entry* data as the malformed
case for v1 and v2, never a missing category array. A stricter reading would
also make the v1 and v2 paths disagree about the same absent field.

### Risk: 35
If wrong, the author requires all three arrays in a v2 catalog and a fixture
that omits `clips` expects a non-zero exit.

## T17: Entry order in a catalog written by `migrate`

### Spec Text
> | Entries | Move every object from `entries` to `episodes` |
> | Categories | Preserve `episodes`, `streams`, and `clips` placement |

### Alternatives
1. `migrate` preserves the order it found: moving and preserving are described
   as position-neutral operations, and no sort is mentioned anywhere in the
   migration rules.
2. `migrate` applies the catalog ordering rule (newest `published` first, ties
   by smaller `id`), because that is a property of every stored catalog.

### Choice
Alternative 1. Both migration tables are written as field-level edits, and
"move every object" reads as a transfer rather than a rebuild. A later `sync`
sorts the catalog anyway, so the two readings differ only for a vault that is
migrated and never synced.

### Risk: 25
If wrong, the author reuses the catalog writer that sorts, and a fixture whose
v1 `entries` are in source order expects them re-sorted by `published`.

## T18: Version 2 history keys that are not already canonical

### Spec Text
> | `title` | history object | ISO 8601 string keys; string values |
> | History keys | Convert every UNIX-epoch string key to ISO 8601 format |

### Alternatives
1. v2 keys are copied verbatim, since the conversion rule is stated only for
   v1 and the v2 migration table does not mention history keys at all.
2. v2 keys are re-rendered as `YYYY-MM-DDTHH:MM:SS`, so `2024-06-15T09:40:00Z`
   loses its `Z` and a fractional part is dropped.

### Choice
Alternative 1. The v2-to-v3 table lists exactly four changes (`source`,
categories, `removed`, `annotations`, plus the version field) and history keys
are not among them; both versions already declare ISO 8601 keys, so there is
nothing the spec asks to convert.

### Risk: 18
If wrong, the author normalizes every key on load and a fixture with a `Z`
suffix expects the suffix gone after migration.

## T19: The value of the migration timestamp

### Spec Text
> | `removed` | Add `{<migration-timestamp>: false}` to every entry |
> | Migration-added timestamp scope | Each migration-added `removed` timestamp must be ISO 8601; cross-entry equality is not required |

### Alternatives
1. One timestamp per run, taken from the wall clock at load time in the same
   local-time format every other mvault datetime uses.
2. A timestamp derived from the catalog (for example one second after the
   newest existing history key), so migration output is reproducible.
3. A UTC timestamp, matching the UTC rule used for v1 epoch keys.

### Choice
Alternative 1. The spec deliberately refuses to pin the value ("cross-entry
equality is not required"), which only makes sense if it is read from the
clock; `sync` already stamps its history with local wall-clock time, so
migration matching that keeps one vault on one clock. The UTC rule is stated
narrowly, for converting epoch *keys*.

### Risk: 8
If wrong, the author stamps migrations in UTC, which differs only in a test
environment whose local time is not UTC.

## T20: What counts as "malformed v1 or v2 entry data"

### Spec Text
> | Malformed v1 or v2 entry data | Error to stderr; exit non-zero; leave `catalog.json` unchanged |

### Alternatives
1. A legacy entry must satisfy its documented schema: the four static fields
   with the documented types, and five non-empty history objects whose keys are
   epoch seconds (v1) or ISO 8601 datetimes (v2). Anything else is malformed.
2. Only what actually breaks the conversion is malformed -- in practice a v1
   key that is not a number -- and everything else is copied through.
3. Values are type-checked too (`views` integers, `title` strings).

### Choice
Alternative 1, which is the same depth the v3 loader already validates at
(see [T14]), applied after the entry is upgraded. Value types are not checked
(3), because the v3 loader does not check them either and no rule asks for it.

### Risk: 30
If wrong, the author converts leniently and a fixture with, say, a v1 entry
missing `height` migrates successfully instead of failing.

## T21: `annotations` on entries that do not have it

### Spec Text
> | `3` | Native format | Category arrays; full `source`; ISO 8601 history keys; `removed`; `annotations` |
> | Entries created by `sync` | Written in v3 shape, with `annotations` as `[]` |

### Alternatives
1. `annotations` is added by migration and by newly created entries, but a
   stored v3 entry that lacks it is still loadable, and `sync` does not
   backfill `[]` onto entries it did not create.
2. Every v3 entry must carry `annotations`, so a hand-written v3 entry without
   it is invalid.
3. `sync` repairs any entry lacking `annotations` by adding `[]`.

### Choice
Alternative 1. The version-handling error table names malformed *v1 or v2*
entry data only, never v3, so v3 validation is left as it was; and the sync
rule is scoped to "entries created by `sync`". Migration is the one place the
spec asks for the field to appear, and it adds it to every entry it touches.

### Risk: 25
If wrong, the author backfills `annotations` on load, so a v3 fixture whose
entries lack the field gains `[]` after the next `sync`.

## T22: Legacy entries that already carry `removed` or `annotations`

### Spec Text
> Version 1 entries have **no** `removed` field and **no** `annotations` field.
> | `removed` | Add `{<migration-timestamp>: false}` to every entry |

### Alternatives
1. Migration sets both fields unconditionally: the spec states legacy entries
   do not have them, and "Single history entry with value `false`" describes
   the result, not a merge.
2. An existing `removed` or `annotations` on a legacy entry is preserved.

### Choice
Alternative 1. The determinism table fixes the migrated `removed` to a *single*
history entry, which a merge could not guarantee. Every other field of the
entry, documented or not, is carried through unchanged (see [T10]).

### Risk: 8
If wrong, the author skips the field when it is already present -- only
reachable with a fixture that contradicts the v1/v2 schema.

## T23: `published` text on migrated entries

### Spec Text
> | `published` | string | ISO 8601 datetime |
> | History keys | Convert every UNIX-epoch string key to ISO 8601 format |

### Alternatives
1. Migration copies `published` verbatim; only history keys are rewritten.
2. Migration normalizes `published` the way `sync` normalizes it for new
   entries (date-only gains `T00:00:00`, timezone suffixes are dropped).

### Choice
Alternative 1. The migration tables enumerate what changes, and the static
fields are not in the list; a legacy `published` is already declared to be ISO
8601, so there is nothing the spec asks to repair.

### Risk: 20
If wrong, the author routes migrated entries through the same normalization
`sync` uses, and a v1 fixture with `published` as `2024-05-01` expects
`2024-05-01T00:00:00` after migration.

## T24: How `<source>/media/<entry_id>` is built from the stored source URL

### Spec Text
> | Media | `<source>/media/<entry_id>` | `<vault>/media/` | Filename contains entry `id` |
> | Preview | `<source>/preview/<entry_id>` | `<vault>/previews/` | Filename contains entry `id` |

### Alternatives
1. Literal concatenation: the stored `source` value, one `/`, then
   `media/<entry_id>` -- so a source of `https://host/feed.json` yields
   `https://host/feed.json/media/e1`.
2. Resolve `media/<entry_id>` against the source URL the way `urljoin` does,
   dropping the last path segment -- `https://host/media/e1`.
3. Use the directory the source document lives in, i.e. strip a trailing
   filename only when it looks like one.

### Choice
Alternative 1, with a single trailing `/` on `source` collapsed. The spec writes
the remote path as a template around `<source>`, and every other placeholder in
that table (`<vault>`, `<entry_id>`) is substituted literally; nothing in the
spec mentions URL resolution or a document-relative base.

### Risk: 22
If wrong, the author resolves the asset paths relative to the source document,
so a vault whose `source` ends in a file name fetches `<host>/media/<id>`.

## T25: How a partial-download artifact is recognized

### Spec Text
> | Candidate selection | Only entries without a corresponding media file in `<vault>/media/` are candidates; A file matches if the name contains entry `id`, apart from partial downloads  |
> | Partial artifacts | Stale partial-download artifacts must not block a later successful download |

### Alternatives
1. A naming convention: files whose name carries a partial-download suffix are
   ignored when deciding candidacy, and a download writes to that suffix before
   renaming into place.
2. Partial artifacts are recognized by some other property, such as a zero-byte
   file or a separate bookkeeping file.
3. There is no convention at all: the implementation simply never leaves a
   partial file behind, so nothing needs excluding.

### Choice
Alternative 1. Downloads land on `<target>.part` and are renamed only once the
whole payload is written, and candidate matching ignores any name ending in
`.part`, `.partial`, `.tmp`, `.download` or `.crdownload`. Recognizing the
common suffixes rather than only the one this implementation writes means a
stale artifact left by a different convention still does not block a download,
which is exactly what the spec requires.

### Risk: 26
If wrong, the author uses one specific suffix outside this set (or a dot-prefixed
name), and a fixture that plants such an artifact expects it to be ignored.

## T26: Extension of a downloaded preview file

### Spec Text
> | Preview | `<source>/preview/<entry_id>` | `<vault>/previews/` | Filename contains entry `id` |
> | Media extension without override | Derive from HTTP `Content-Type` |

### Alternatives
1. Previews get the same treatment as media without an override: the extension
   comes from the preview response's `Content-Type`.
2. Previews are stored under the bare `<entry_id>` with no extension, since the
   extension rules name only media.
3. Previews reuse the media extension, including a `--format` override.

### Choice
Alternative 1. The only filename requirement stated for previews is that the
name contains the `id`, and the `Content-Type` rule is the spec's general answer
to "what extension does a downloaded file get". The `--format` override is
described as a *media* format override, so it is deliberately not applied here.

### Risk: 28
If wrong, the author stores previews as the bare entry `id`, and a fixture
asserts the exact preview file name.

## T27: Which entries get a preview download

### Spec Text
> | `--episodes=<n>` | non-negative integer | Maximum number of episode media downloads |
> | Candidate selection | Only entries without a corresponding media file in `<vault>/media/` are candidates |

### Alternatives
1. Previews are fetched for exactly the entries selected as media candidates, so
   the per-category limits bound preview traffic too.
2. Previews are fetched for every catalog entry regardless of media candidacy,
   because candidacy is defined only in terms of `<vault>/media/`.
3. Previews have their own candidate rule based on `<vault>/previews/`.

### Choice
Alternative 1. The limits are worded as caps on *media* downloads, which implies
the preview is a companion of the media download rather than an independent
stream of work; treating the selected candidates as the unit of download keeps a
limited run genuinely limited.

### Risk: 30
If wrong, the author fetches previews for entries that already have media, so a
run over an already-populated vault still requests previews.

## T28: Permanent versus transient download failures, and the retry count

### Spec Text
> | Permanent download failure | Warning to stderr; continue with remaining entries |
> | Transient download failure | Retry, then warn to stderr after retries exhausted; continue with remaining entries |

### Alternatives
1. HTTP statuses below `500` are permanent; `5xx` statuses and transport-level
   errors (connection refused, timeout, DNS) are transient.
2. Only `404` and `410` are permanent and everything else is retried.
3. Only transport-level errors are transient; every HTTP status is permanent.

### Choice
Alternative 1 with three attempts per asset. The `4xx`/`5xx` split is the
standard meaning of "permanently unavailable" versus "try again", and three
attempts is small enough that a hidden test asserting "more than one request"
passes without making a failing run slow.

### Risk: 20
If wrong, the author treats a specific status this implementation retries (for
example `429`) as permanent, or fixes a different attempt count that a test
asserts exactly.

## T29: Extension for a `Content-Type` with no known extension

### Spec Text
> | Media extension without override | Derive from HTTP `Content-Type` |

### Alternatives
1. Fall back to a generic extension such as `bin`.
2. Store the file with no extension at all.
3. Use the `Content-Type` subtype verbatim, so `video/x-matroska` becomes
   `.x-matroska`.

### Choice
Alternative 1, via the standard library's MIME table with a `bin` fallback. The
spec's own "filename contains entry `id`" rule is the only hard requirement, and
a generic extension keeps every stored file uniformly named.

### Risk: 30
If wrong, the author derives the extension from the subtype text, and a fixture
serves an exotic `Content-Type` to check it.

## T30: What the post-sync counts count

### Spec Text
> | Trigger | Successful `sync` run that includes metadata phase |
> | Counts reported | Added, removed, updated |
> | Post-sync counts | Deterministic for the same vault state and source metadata |

### Alternatives
1. The counts describe what *this run* changed: entries created now, entries
   whose `removed` flipped to true now, entries whose tracked history gained a
   value now.
2. The counts are the `digest` classification applied to the resulting catalog,
   so the same classifier drives both features.

### Choice
Alternative 1. A "post-sync change summary" reports the effect of the sync that
just ran. Reusing the digest rules would count an entry that has never changed
since it was first seen as an addition on every future sync, which makes the
summary of an unchanged run report additions -- not a summary a user would read
as correct.

### Risk: 36
If wrong, the author reuses the digest classifier, so a second sync that changes
one entry still reports the untouched entries as additions.

## T31: `--skip-metadata` on a v1 or v2 vault

### Spec Text
> Because `sync` auto-migrates v1 and v2 vaults to v3 during the metadata phase,
> the download phase always operates against a v3 catalog.
> | `--skip-metadata` | flag | Skip source fetch and metadata update; run download phase against existing vault state |

### Alternatives
1. With no metadata phase there is no migration to persist: the legacy catalog
   is upgraded in memory only, so `catalog.json` keeps its stored version.
2. Migration is persisted regardless, because a `sync` of a legacy vault always
   upgrades it on disk.

### Choice
Alternative 1. The spec attributes the migration to the metadata phase, and
`--skip-metadata` is defined as skipping "metadata update"; writing a migrated
catalog would be a metadata update. The in-memory upgrade still gives the
download phase the v3 catalog and migrated `source` the spec promises.

### Risk: 24
If wrong, the author migrates on load and saves unconditionally, so a
`--skip-metadata` run leaves a v3 `catalog.json` and a `catalog.bak` behind.

## T32: Whether removed entries are download candidates

### Spec Text
> | Candidate selection | Only entries without a corresponding media file in `<vault>/media/` are candidates |
> | Candidate order | Catalog order within category |

### Alternatives
1. Every catalog entry is considered, including entries whose latest `removed`
   value is true.
2. Entries currently marked removed are skipped, since the source no longer
   offers them.

### Choice
Alternative 1. Candidate selection is stated as a single condition about the
local `media/` directory, with no mention of `removed`; and an entry the source
has dropped is exactly the one an archiving tool most wants to keep trying for.

### Risk: 22
If wrong, the author filters removed entries out before applying the
per-category limit, which also shifts which entries a limit selects.

## T33: A `removed` history whose only value is `true`

### Spec Text
> | Removals | Latest `removed` value is `true` and prior `removed` value, if present, is `false` |

### Alternatives
1. "if present" makes the condition on the prior value vacuous when there is no
   prior value, so a single-key `removed: true` history is a removal.
2. A removal always requires an observed `false` -> `true` transition, so a
   single-key history never qualifies.

### Choice
Alternative 1, the literal reading of "if present". Such an entry is also an
addition by the additions rule, and the precedence table puts removals first,
so it is reported as a removal.

### Risk: 25
If wrong, the author requires the transition and reports that entry as an
addition instead.

## T34: The wording of digest headings

### Spec Text
> | Category grouping | Changes grouped by category (v1: single `Entries` group; v2/v3: per-category) |
> | Grouping within category | Changes grouped by type |
> | Priority | `1` | Removals (v3 only) | ... `2` | Additions | ... `3` | Field updates |

### Alternatives
1. Use the category names the spec capitalizes (`Entries`, `Episodes`,
   `Streams`, `Clips`) as headings, with per-type headings named for the groups.
2. Emit a flat list with the category and type as a prefix on each line.

### Choice
Alternative 1: a `<Category>:` heading, then `Removed:`, `Added:` and `Updated:`
sub-headings in precedence order, then one `- <title>` line per entry. The spec
names the categories in title case and describes two levels of grouping, which
is what an indented heading layout expresses.

### Risk: 34
If wrong, the author's heading words differ (for example `Removals`,
`Additions`, `Field updates`) and a fixture matches them.

## T35: Entry order within a digest group

### Spec Text
> | Entry order within group | Deterministic |
> | Digest entry order | Deterministic |

### Alternatives
1. Catalog order within the category, matching the download phase's
   "catalog order within category".
2. Alphabetical by current title, or by entry `id`.

### Choice
Alternative 1. It is the only ordering the spec names anywhere for entries
within a category, it needs no extra key, and it is stable for a given catalog.

### Risk: 18
If wrong, the author sorts by title or `id`, which differs whenever a catalog's
stored order is not already alphabetical.

## T36: Whether `removed` counts as a tracked field for the additions rule

### Spec Text
> | Additions | Entry has only initial observations; no tracked field has a second history entry | Same rule applied to available tracked fields |

### Alternatives
1. `removed` is one of the v3 tracked fields, so a second `removed` history
   entry disqualifies an entry from being an addition.
2. Only the source-supplied fields count, so `removed` history is consulted for
   the removals rule alone.

### Choice
Alternative 1. The v1/v2 column says the same rule applies to the "available"
tracked fields -- the distinction only makes sense if `removed` is a tracked
field that v1 and v2 lack. An entry that has been removed and has reappeared is
therefore not an addition, which matches the reappearance rule.

### Risk: 20
If wrong, the author treats `removed` as bookkeeping outside the tracked set, so
a reappeared entry with no other change is reported as an addition.

## T37: What the digest trailing line says

### Spec Text
> | Trailing line | Metadata about the digest run |
> | Source reference | The trailing line includes the resolved source URL for the loaded vault version |
> | Digest trailing line | Deterministic format |
> | Wall-clock usage outside digest trailing line | Not part of file naming or vault content |

### Alternatives
1. The line carries the run's wall-clock time, the catalog version and the
   resolved source URL. The "wall-clock usage *outside* the trailing line" rule
   implies the trailing line is where wall clock is allowed.
2. The line carries only the source URL, keeping the output byte-for-byte
   reproducible.

### Choice
Alternative 1: `Digest generated <timestamp> from catalog version <n> at <url>`.
The determinism rule constrains the *format*, not the values, and the carve-out
for wall clock in this one line only makes sense if the line reports a time.

### Risk: 22
If wrong, the author's trailing line omits the timestamp or the version, and a
fixture matches the whole line.

## T38: When `media/` and `previews/` are created

### Spec Text
> | Media | ... | `<vault>/media/` | ... |
> | Preview | ... | `<vault>/previews/` | ... |

### Alternatives
1. Each directory is created when the first asset of that kind is successfully
   stored, so a run that downloads nothing leaves the vault layout untouched.
2. Both directories are created up front by every `sync` (or by `init`).

### Choice
Alternative 1. The spec describes these paths as download targets, never as part
of the vault layout `init` produces, and no rule asks for empty directories.
Creating them lazily also keeps a `--skip-download` run purely a metadata run.

### Risk: 15
If wrong, the author creates both directories eagerly and a fixture asserts they
exist after a run that downloaded nothing.

## T39: What a post-sync "changed-entry line" is

### Spec Text
> | Post-sync summary | Each changed-entry line includes viewer link on same line as title |

### Alternatives
1. The post-sync summary gains one line per entry the run changed -- a kind, the
   entry's current title and its viewer link -- printed above the existing
   `Added N, removed N, updated N.` counts line.
2. The summary keeps the counts line only, and the rule is vacuous until some
   other feature adds entry lines.
3. The summary is rendered with the full `digest` layout (category headings and
   group sub-headings) applied to what this run changed.

### Choice
Alternative 1. The rule presupposes that the summary *has* changed-entry lines
with titles, so the counts-only summary of the earlier spec has to grow them;
a flat `<Kind>: <title> <link>` line per changed entry is the smallest shape
that satisfies "changed-entry line" and "same line as title". The counts line
stays last, so the previously specified counts are untouched. The entries
appear in category order, additions and updates in source order, removals after
them, which is deterministic for a given source document.

### Risk: 45
If wrong, the author reuses the digest layout (alternative 3), so the summary
carries `Episodes:` / `Added:` headings around the entry lines.

## T40: Where the viewer link sits on a report line

### Spec Text
> | `digest <name>` | Each changed-entry line includes viewer link on same line as title |
> | Post-sync summary | Each changed-entry line includes viewer link on same line as title |

### Alternatives
1. The link is appended at the end of the line, after the field-update suffix:
   `- <title> (<fields>) <link>`.
2. The link comes directly after the title, before the suffix.
3. The title is rendered as a link target in some markup form.

### Choice
Alternative 1. The spec only requires the link to share the line with the
title, and the earlier spec already fixed the field-update suffix as following
the title "in parentheses after title" -- putting the link last is the only
placement that leaves that rule intact. Plain text output has no markup, so 3
is out.

### Risk: 20
If wrong, the author puts the link between the title and the parenthesised
field names, and a fixture matches the whole line.

## T41: Where "recent vaults" are persisted

### Spec Text
> | Trigger | Navigation to any vault through viewer |
> | Persistence | Later browser session from same browser must still show visited vault |

### Alternatives
1. Server-side: the viewer stores the visited names in a file
   (`.mvault-recent.json`) in the directory it serves, so any later request --
   new browser session, new server process -- still sees them.
2. Browser-side: a cookie, so the list travels with the browser and is rendered
   from the request.
3. Browser-side: `localStorage` plus client-side rendering.

### Choice
Alternative 1. "Later browser session ... must still show" is a minimum the
server-side store always satisfies, including for a client that sends no
cookies at all, while a cookie or `localStorage` store shows nothing to such a
client. Nothing in the spec asks for the list to be private to one browser, and
a `localStorage` list would not appear in the landing page's HTML at all. The
file sits in the served directory because vault names are resolved there.

### Risk: 25
If wrong, the author keys the list to the browser with a cookie; a test that
navigates and then loads `/` on the same connection passes either way, and one
that asserts the list is empty for a fresh client only passes for the cookie.

## T42: How `/` learns that a vault was not found

### Spec Text
> | Non-existent vault on any `/catalog/<name>` route | Redirect to `/`; landing page shows vault-not-found indication; response must not be HTTP `500` |

### Alternatives
1. Redirect to exactly `/`, remembering the missing name on the server and
   showing it on the next landing page render.
2. Redirect to `/?missing=<name>` and render the indication from the query
   string.
3. Redirect to `/` and always show a generic "vault not found" area.

### Choice
Alternative 1. The spec names the redirect target as `/`, so the `Location`
header is exactly that; the viewer is a single-user local server, so one
pending notice is enough state to name the vault that was missing on the next
landing page.

### Risk: 22
If wrong, the author redirects to `/` with a query string and a fixture asserts
the query, which a bare `/` redirect does not produce.

## T43: The URL `serve <name>` opens

### Spec Text
> | `serve <name>` | Start server and open browser to default category page for vault |
> | `--host=<host>` | Override bind host; the browser URL uses this host as given |

### Alternatives
1. Resolve the vault's version before starting and open the resolved page,
   `http://<host>:<port>/catalog/<name>/<category>`.
2. Open `http://<host>:<port>/catalog/<name>` and let the redirect land on the
   default category page.

### Choice
Alternative 1: the spec says the browser opens the default category page, not
the route that redirects to it. A vault that cannot be read has no resolved
category, so its URL falls back to `/catalog/<name>`, which the viewer answers
with the vault-not-found redirect. The chosen URL is also printed on stdout, so
the address is visible without a browser.

### Risk: 18
If wrong, the author opens `/catalog/<name>` and a fixture that records the
browser URL expects no category segment.

## T44: `POST /` with a `catalog` field that is present but empty

### Spec Text
> | `POST` | `/` | Accept form-encoded body; redirect to `/catalog/<value>` when `catalog` field is present, otherwise redirect to `/` |
> | Missing `catalog` field on `POST /` | Redirect to `/` |

### Alternatives
1. A blank or whitespace-only value counts as no vault name: redirect to `/`.
2. The field is present, so redirect to `/catalog/` with an empty name, which
   then resolves as a missing vault and redirects to `/` anyway.

### Choice
Alternative 1. Submitting the landing form with an empty box is the ordinary
way to produce this request, and `/catalog/` is not a route the spec defines.
Both readings end at `/`; they differ only in how many redirects it takes.

### Risk: 12
If wrong, the author redirects to `/catalog/` first, so an assertion on the
immediate `Location` header sees `/catalog/` rather than `/`.

## T45: `/catalog/<name>/<category>/<id>` for an id that is not in the category

### Spec Text
> | `GET` | `/catalog/<name>/<category>/<id>` | HTML response for that viewer link target; may reuse the category listing page with the entry highlighted or otherwise surfaced |

### Alternatives
1. Render the category listing with nothing highlighted, since the route's job
   is to show the category the link points into.
2. Return `404`.

### Choice
Alternative 1. The route is defined as "HTML response for that viewer link
target" and the spec explicitly allows it to be the category listing; only the
non-existent-vault case is given an error behaviour, so an unknown id stays a
normal listing.

### Risk: 15
If wrong, the author returns `404` for an unknown entry id.

### Resolved by the detail-page spec
The later spec settles this: `/catalog/<name>/<category>/<id>` is now an entry
detail page rather than a reused listing, and "| Missing entry in specified
category | HTTP `404`, or redirect to category listing with error indication |"
rules out answering with a plain, unmarked listing. The implementation now
returns `404`, which was alternative 2 above; see T54 for that choice.

## T46: Whether the report links follow `--host` / `--port`

### Spec Text
> | Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>` |
> | Default scheme | `http://` | Default host | `127.0.0.1` | Default port | `8840` |

### Alternatives
1. `digest` and the post-sync summary always use the documented defaults; the
   `<host>`/`<port>` placeholders exist because `serve` can move the server.
2. `digest` and `sync` gain their own `--host`/`--port` options so the printed
   links can match a relocated server.

### Choice
Alternative 1. The spec gives `--host`/`--port` to `serve` alone and gives the
report links a default host and port with no way to override them, so the
reports print the default endpoint.

### Risk: 8
If wrong, the author threads an override (an option or an environment variable)
into the report links and tests it.

## T47: Whether a partial download counts as downloaded in the listing

### Spec Text
> | Downloaded state (v2/v3) | Entry counts as downloaded when a media filename in `<vault>/media/` contains entry `id` |

### Alternatives
1. Use the same rule the download phase uses when it picks candidates, which
   ignores partial-download artifacts (`<id>.mp4.part` and friends).
2. Take the rule literally: any file name in `media/` containing the id counts,
   including a partial one.

### Choice
Alternative 1. The viewer should agree with the downloader about what is
stored: a file the next `sync` would still re-download is not a downloaded
entry. For every vault produced by mvault itself the two readings agree, since
partial files are renamed as soon as the write finishes.

### Risk: 10
If wrong, the author lists an entry with only a `.part` file as downloaded.

## T48: What counts as "navigation to a vault" for the recent list

### Spec Text
> | Trigger | Navigation to any vault through viewer |

### Alternatives
1. Every successful `/catalog/<name>...` request records the vault, including
   the bare vault route that only redirects, and including a request whose
   category is invalid.
2. Only a rendered category listing records the vault.

### Choice
Alternative 1. `/catalog/<name>` is navigation to that vault, and it is exactly
what the landing form and the recent links produce, so recording it is what
makes a form submission show up in the list. Vaults that cannot be read are
never recorded, since that navigation ends on the landing page instead.

### Risk: 12
If wrong, the author records the vault only when a listing is rendered, so a
vault reached only by its bare route is missing from `/`.

## T49: Whether a single-point history drops its chart *data* too

### Spec Text
> | Single-point history | Chart for that field may be omitted |
> | Fields exposed | `views`, `likes` |
> | Embedding style | Machine-readable structured data embedded in HTML |

### Alternatives
1. The drawn chart is omitted but the field's points stay in the embedded
   payload, so the machine-readable data always covers `views` and `likes`.
2. Both the drawn chart and the field's entry in the payload are omitted.

### Choice
Alternative 1. The row permits omitting "the chart", and a one-point series is
exactly what cannot be drawn as a line, so the rendered figure is dropped. The
payload is a separate requirement -- `views` and `likes` are listed as "fields
exposed" unconditionally -- and keeping the point costs nothing while making the
version-aware timestamp normalization observable on single-keyed legacy vaults.

### Risk: 26
If wrong, the author drops the field from the payload as well, so a test may
assert that a one-point `views` history leaves no `views` data behind.

## T50: Trailing slash in the v2/v3 `source` when building the entry link

### Spec Text
> | v2 | `<source>/entry/<id>` |
> | v3 | `<source>/entry/<id>` |

### Alternatives
1. Strip a trailing `/` from the stored `source` first, so
   `https://example.test/feed/` yields `https://example.test/feed/entry/e1`.
2. Concatenate literally, yielding `https://example.test/feed//entry/e1`.

### Choice
Alternative 1. The download phase already builds its asset URLs from
`source.rstrip("/")`, so the viewer agreeing with it keeps one vault producing
one address for the same entry, and the determinism table asks the link to be
deterministic rather than doubled.

### Risk: 20
If wrong, the author concatenates the raw `source` and a fixture whose source
ends in `/` expects the doubled slash.

## T51: Which stored file is used when several match one entry id

### Spec Text
> | Downloaded media discovery | A downloaded media file counts as matching the entry when a saved filename in `<vault>/media/` contains the entry `id`; the detail page uses that exact filename in the media static endpoint URL |
> | Preview lookup | `/vault/<name>/preview/<id>` resolves the saved preview asset whose filename contains the requested `id` |

### Alternatives
1. Sort the directory's names and take the first match, so the page and the
   preview endpoint always resolve to the same file.
2. Take whatever the filesystem lists first, which varies between machines.

### Choice
Alternative 1. Both rows are repeated under Determinism, and directory order is
not deterministic, so the match is made over sorted names. `sync` stores one
media file and one preview per entry, so the two readings only differ on a vault
whose assets were placed by hand.

### Risk: 12
If wrong, the author iterates the directory unsorted and a fixture with two
matching files expects the other one.

## T52: Whether partial-download artifacts count as stored assets

### Spec Text
> | Downloaded media discovery | A downloaded media file counts as matching the entry when a saved filename in `<vault>/media/` contains the entry `id` |

### Alternatives
1. Ignore partial-download artifacts (`e1.mp4.part` and friends), as the
   download phase and the category listing already do.
2. Count any file name containing the id, partial or not.

### Choice
Alternative 1. The same rule already decides the listing's downloaded badge
(see T47), and a detail page that offered playback of a file the next `sync`
would re-download would contradict the listing beside it. For any vault mvault
produced the readings agree, since a partial file is renamed the moment its
write finishes.

### Risk: 10
If wrong, the author treats a lone `.part` file as the entry's media and links
it from the detail page.

## T53: MIME type for a stored asset whose extension implies none

### Spec Text
> | `GET` | `/vault/<name>/media/<file>` | Serve `<vault>/media/<file>` with an appropriate media MIME type |
> | `GET` | `/vault/<name>/preview/<id>` | Serve the matching preview image ... with an appropriate image MIME type |

### Alternatives
1. Guess from the file extension, falling back to `application/octet-stream`
   for media and to `image/jpeg` for a preview, which the spec requires to be
   served as an image.
2. Fall back to `application/octet-stream` for both.
3. Serve a fixed type per endpoint, ignoring the extension.

### Choice
Alternative 1. The extension is what the download phase derived from the
source's own `Content-Type`, so guessing from it reproduces that type; the
preview fallback stays inside the image family the row demands. The fallbacks
are unreachable for vaults mvault filled, whose assets always carry an
extension.

### Risk: 14
If wrong, the author serves a fixed type per endpoint, so an extensionless or
oddly named asset is expected to come back as that type.

## T54: Status used for a refused traversal, and for a missing entry

### Spec Text
> | Path traversal attempt | HTTP `403` or HTTP `404` |
> | Missing entry in specified category | HTTP `404`, or redirect to category listing with error indication |

### Alternatives
1. Answer `404` in both cases: a name that escapes its directory names nothing
   the viewer publishes, and a missing entry is a missing page.
2. Answer `403` for traversal and redirect for a missing entry.

### Choice
Alternative 1. The spec allows either status for traversal and either handling
for a missing entry, so the implementation picks the one that needs no extra
branch: resolution either yields a servable file inside the directory or it
yields nothing. `404` also declines to confirm whether the escaped-to path
exists.

### Risk: 5
If wrong, the author answers `403` for traversal; a conforming test must accept
both, so only a test asserting one exact status is affected.

## T55: What makes a vault "non-existent" on a static route

### Spec Text
> | Non-existent vault on detail or static route | Redirect to landing page with vault-not-found indication |

### Alternatives
1. A static route only needs the vault directory, so it redirects when that
   directory is absent and serves files even from a vault whose catalog is
   unreadable.
2. A static route reads the catalog first, so an unreadable catalog also
   redirects, exactly as the detail route does.

### Choice
Alternative 1. The static endpoints serve bytes out of `media/` and `previews/`
and never consult the catalog, so parsing it would only add a way for a
readable file to become unreachable. The detail route still reads the catalog,
since it cannot render without one.

### Risk: 15
If wrong, the author routes both families through the same catalog read, so a
vault directory holding a corrupt catalog redirects instead of serving media.

## T56: Whether the detail page requires well-formed static entry fields

### Spec Text
> | Published date | Displayed |
> | Dimensions | Display width and height |
> | Any HTTP error | Well-formed response; no raw stack trace or internal detail exposure |

### Alternatives
1. A catalog view rejects an entry missing `id`, `published`, `width` or
   `height`, so such a vault is handled like any other unreadable catalog --
   the viewer redirects to the landing page and `digest` reports an error.
2. The detail page renders whatever is present and leaves the missing fields
   blank.

### Choice
Alternative 1. The page is required to display the published date and both
dimensions, so an entry lacking them cannot be rendered as specified; treating
it as a malformed catalog reuses the handling legacy catalogs already get and
keeps the no-stack-trace rule without scattering per-field fallbacks.

### Risk: 18
If wrong, the author renders the page anyway with the missing fields empty,
so a hand-written fixture entry without `width` is expected to return `200`.

## T57: How an annotation `id` is generated

### Spec Text
> | `POST` | Create annotation | JSON with `title`, `timecode`, optional `body` |
> | `id` | string | Unique within entry |

### Alternatives
1. The server mints an opaque unique token (a UUID hex) for each created
   annotation.
2. The server numbers annotations sequentially within the entry, storing
   `"1"`, `"2"`, ... in creation order.
3. The id is derived from the timecode or the title, so two marks at the same
   second would collide.

### Choice
Alternative 1, a `uuid4` hex string. `POST` carries no `id`, so the server has
to invent one, and the only stated rule is uniqueness within the entry. A
counter would repeat an id after a delete-then-create cycle unless the counter
is also persisted, which the storage table does not describe; an opaque token
is unique without storing extra state. Every test reads the id back out of
`catalog.json` before using it in a `PATCH` or `DELETE`, which is also the only
way a client could learn it.

### Risk: 22
If wrong, the author numbers annotations per entry and a fixture asserts the
first created annotation has id `"1"`.

## T58: Which redirect status an annotation mutation answers with

### Spec Text
> | `POST` | Create annotation | ... | Redirect to entry detail page with `?timecode=<seconds>` |

### Alternatives
1. `303 See Other`, the status already used for every other viewer redirect.
2. `302 Found`.

### Choice
Alternative 1. The viewer's existing redirects (`/catalog/<name>`, the landing
form, a missing vault) all use `303`, and `303` is the correct answer to a
non-idempotent request whose result is a page to `GET`. A test that only checks
"is a redirect" passes either way.

### Risk: 8
If wrong, the author sends `302` and a fixture asserts that exact status.

## T59: An empty-string `title` on create

### Spec Text
> | `title` | string | yes | none |
> | Missing `title` on create | HTTP `400` with message naming missing field |
> | `title` | string | Stored as provided |

### Alternatives
1. `title` is missing only when the key is absent or `null`; `""` is a present
   string and is stored as provided.
2. Any falsy `title`, including `""`, is treated as missing and rejected with
   `400`.

### Choice
Alternative 1. The storage rule says the title is "stored as provided", with no
non-empty requirement anywhere, and the error row is about a *missing* field.
The natural fixture for the error row omits the key entirely, which both
readings reject.

### Risk: 24
If wrong, the author writes `if not payload.get("title")` and `{"title": "",
"timecode": "90"}` is expected to be a `400`.

## T60: `PATCH` carrying `id` but neither `title` nor `body`

### Spec Text
> | `PATCH` | Update annotation | JSON with `id` and at least one of `title` or `body` |
> | omitted fields | n/a | allowed | Leave stored value unchanged |

### Alternatives
1. The "at least one" rule is a request requirement, so a body with only `id`
   is a `400` naming the fields it must carry.
2. Omitting both is allowed by the "omitted fields ... leave stored value
   unchanged" row, so the request is a no-op that still redirects.

### Choice
Alternative 1. "at least one of `title` or `body`" is stated as part of what
the request body *is*; the omitted-fields row describes which of the two
optional fields may be left out, not that both may be. The error table does not
list this case, but every other malformed body there is a `400`.

### Risk: 32
If wrong, the author treats it as a successful no-op and expects a redirect.

## T61: A `timecode` that is present but not a string

### Spec Text
> | `timecode` | string | yes | none |
> | Invalid `timecode` format | HTTP `400` with format error message |
> | Component type | Non-negative integer |

### Alternatives
1. Only a string matching the grammar is accepted; a JSON number such as `90`
   is an invalid format and gets `400`.
2. A JSON integer is coerced, since the parsed result is whole seconds anyway.

### Choice
Alternative 1. The field table types `timecode` as `string` and the grammar
table describes text formats (`"90"`, `"1:30"`), quoted throughout. Accepting a
number would also make the "invalid pattern" rule ambiguous for floats.

### Risk: 28
If wrong, the author's parser calls `str()` on whatever arrives, so
`{"timecode": 90}` creates an annotation at 90 seconds.

## T62: An explicit `"body": null` in a `PATCH`

### Spec Text
> | `body` | string | no | Replace existing body when present |
> | omitted fields | n/a | allowed | Leave stored value unchanged |
> | `body` | string or `null` | Stored as provided or defaulted to `null` |

### Alternatives
1. "Present" means the key is in the JSON object, so `"body": null` is present
   and clears the stored body back to `null`.
2. "Present" means a non-null value, so `"body": null` behaves like an omitted
   field and leaves the stored body alone.

### Choice
Alternative 1, key presence. The companion row is about *omitted* fields, which
is a statement about keys rather than values, and the storage table already
allows `null` as a stored body, so clearing one is representable. Key presence
also makes `PATCH` reversible against `POST`, which defaults an absent body to
`null`.

### Risk: 26
If wrong, the author reads `payload.get("body")` and a `null` body leaves the
previous text in place.

## T63: Status for a mutation URL naming a vault, category or entry that does not exist

### Spec Text
> | Non-existent annotation `id` on update | HTTP `404` |
> | Any error response | Well-formed HTTP response; no raw traceback or stack trace |

### Alternatives
1. A mutation whose URL names an unknown vault, an unknown category for that
   version, or an unknown entry id answers `404`, like the unknown annotation
   id does.
2. It mirrors `GET`, which redirects an unknown vault to the landing page and
   an unknown category to the vault's default category.

### Choice
Alternative 1. A redirect is a meaningful success result for these methods --
it is what a completed annotation returns -- so reusing it for "there is
nothing here to annotate" would make a failed write indistinguishable from a
successful one. `404` is the status the spec already gives to the analogous
"the thing you named is not there" case.

### Risk: 18
If wrong, the author routes unknown vaults and categories through the same
redirects `GET` uses, so those requests answer `303` rather than `404`.

## T64: How the detail page "seeks playback" to the `timecode` query value

### Spec Text
> | Entry detail page effect | Seek playback to `timecode` query value |

### Alternatives
1. The page marks the requested offset in its markup: the stored media is
   referenced with a `#t=<seconds>` media fragment and the offset is also
   rendered as a visible, machine-readable element.
2. The page ships JavaScript that assigns `video.currentTime` on load.
3. The query is only a hint to the browser and the page renders identically.

### Choice
Alternative 1. The viewer is server-rendered with no scripting beyond its
embedded chart JSON, and `#t=` is the standard way to ask a media element to
start at an offset, so it needs no client code. The offset is also emitted as
text so the effect is observable in a response body rather than only in a real
browser.

### Risk: 34
If wrong, the author emits a `<script>` that seeks, or nothing at all, and a
fixture looks for their specific marker rather than for the seconds in the
body.

## T65: Whether the `timecode` query value is re-parsed with the grammar

### Spec Text
> | Create-success redirect value | Integer whole seconds |
> | Entry detail page effect | Seek playback to `timecode` query value |

### Alternatives
1. The query value is read with the same grammar the request body uses, so
   `?timecode=90` and `?timecode=1:30` both seek to 90 seconds and anything
   ungrammatical is ignored.
2. Only plain integer seconds are understood, since that is all a create
   redirect ever produces.

### Choice
Alternative 1. The parameter is named `timecode` and the grammar section is
written about `timecode` values generally; accepting the colon forms costs
nothing and the integer form -- the only one the redirect emits -- behaves
identically under both readings.

### Risk: 12
If wrong, the author only accepts digits, which differs solely on a
hand-written `?timecode=1:30` URL.

## T66: Fields in the request body that the method does not define

### Spec Text
> | `PATCH` | Update annotation | JSON with `id` and at least one of `title` or `body` |
> | omitted fields | n/a | allowed | Leave stored value unchanged |

### Alternatives
1. Unrecognized keys are ignored, so a `PATCH` carrying `timecode` updates the
   title and body it names and leaves the stored timecode alone.
2. Unrecognized keys are rejected with `400`.
3. A `PATCH` carrying `timecode` updates the timecode too.

### Choice
Alternative 1. The `PATCH` table lists exactly which fields it reads and the
storage table gives no rule for re-timing an annotation, so `timecode` is not
an updatable field; rejecting unknown keys is a strictness the spec never asks
for, and the error table lists no such condition.

### Risk: 20
If wrong, the author lets `PATCH` move an annotation's timecode as well.

## T67: A v1 vault addressed with the post-migration category

### Spec Text
> The annotation request must target the entry using the **pre-migration**
> category (`entries`) in the URL, but after migration the entry resides in
> `episodes`.
> | Subsequent requests | Must use `episodes` (v1 `entries` route is retired after migration) |

### Alternatives
1. Before migration only `entries` addresses a v1 entry; `episodes` is a `404`
   until the vault has actually been migrated.
2. Both names are accepted on a v1 vault, since the entry ends up in `episodes`
   either way.

### Choice
Alternative 1. The category is validated against the version on disk, which is
what makes "must use the pre-migration category" and "subsequent requests must
use `episodes`" two different rules rather than one permissive one.

### Risk: 22
If wrong, the author migrates first and then looks the entry up, so `episodes`
works on a pristine v1 vault too.

## T68: A catalog that cannot be read at all versus a migration that fails

### Spec Text
> | Migration failure during auto-migration | HTTP `500` with error message; original catalog unchanged |

### Alternatives
1. `500` covers failures raised while converting a catalog whose version was
   recognized (a v1 catalog with no `source_id`, a legacy entry with a
   malformed history); a catalog whose `version` field is missing, mistyped or
   unsupported is not a migration failure and answers `404`, as an unservable
   vault.
2. Every unreadable catalog is a `500`.
3. Every unreadable catalog is a `404`.

### Choice
Alternative 1. Migration is the step that converts entries, so only a failure
inside it is a "migration failure"; a catalog whose version cannot even be
determined never reaches that step and is the same condition `GET` treats as a
vault it cannot serve.

### Risk: 30
If wrong, the author wraps the whole read-and-migrate step and returns `500`
for any unreadable catalog.

## T69: Whether an annotation mutation counts as visiting a vault

### Spec Text
> | Read-after-write behavior | Later `GET` to same entry detail page reflects create, update, or delete result |

### Alternatives
1. Only `GET` navigation records a vault in the landing page's recent list; a
   mutation answers a redirect and records nothing, because the `GET` it
   redirects to records the visit.
2. Every request naming a vault records it.

### Choice
Alternative 1. The recent list is described in terms of vaults that were
browsed, and a mutation is always followed by the redirect target's `GET`, so
the vault still lands in the list without the mutation touching it.

### Risk: 10
If wrong, the difference is only visible when a client issues a mutation and
never follows the redirect.
