# AMBIGUITIES

Numbered record of under-specified points in the `mvault` spec, the reading
chosen by this implementation, and the risk that the spec author's own
implementation (and therefore the hidden tests) reads it differently.

---

## T1 — Location of `catalog.bak`

### Spec Text
> | Backup path | `catalog.bak` |

and

> | Catalog path | `<name>/catalog.json` |

### Alternatives
1. `<name>/catalog.bak` — beside the catalog inside the vault directory.
2. `./catalog.bak` — relative to the process working directory.

### Choice
`<name>/catalog.bak`. Every other path in the spec that names a vault file is
given relative to the vault directory (`<name>/catalog.json`), and the backup
row sits in the same table as the catalog it mirrors. A backup written to the
CWD would collide between vaults.

### Risk: 3
Author's most likely different reading: backup written to the process CWD.

---

## T2 — Scope of the "strictly later second" advance

### Spec Text
> | Collision handling | When a new history entry would reuse an existing or non-newer second, advance to a strictly later second before writing |

and

> | Sync timestamps | Reflect sync execution time and remain strictly increasing whenever new history entries are appended |

### Alternatives
1. **Per-history**: each tracked field's history is bumped independently, so a
   single `sync` run can stamp different fields/entries with different seconds
   (a brand-new entry has an empty history and gets the raw wall clock, while a
   field changed one second ago gets wall clock + 1s).
2. **Per-sync (global)**: one timestamp is computed for the whole run as
   `max(now, newest_key_in_catalog + 1s)` and used for every history entry
   appended by that run.

### Choice
Per-sync (global). "Sync timestamps ... remain strictly increasing" speaks about
*sync* timestamps as a single per-run quantity, and the update-rule table
repeatedly says "at sync timestamp" (singular) for first observation, changes,
removals and restorations alike — implying one shared value per run. It also
keeps a single sync internally consistent: all fields touched by one run share
one key, which makes "current value" reconstruction unambiguous.

### Risk: 25
Author's most likely different reading: per-history bumping, where a newly
observed entry in a run can carry an earlier second than a changed field in the
same run.

---

## T3 — What makes a vault "invalid" for `sync`

### Spec Text
> | Missing or invalid vault | Error to stderr including `<name>`; exit non-zero |

### Alternatives
1. Only unreadable/unparseable `catalog.json` counts as invalid.
2. Any deviation from the documented root schema counts: missing
   `catalog.json`, non-object JSON, non-integer/non-`3` `version`, non-string
   `source`, or any of `episodes`/`streams`/`clips` missing or not an array.
3. As (2) but tolerating a `version` other than `3` (forward/backward compat).

### Choice
(2). The "`catalog.json` Root Schema" table states required *values*, not merely
required keys (`version` → "Required Value `3`"), so a catalog that violates it
is not a valid vault. Validating the whole root also gives `sync` a well-defined
structure to operate on.

### Risk: 20
Author's most likely different reading: accepts any integer `version` and only
rejects missing/corrupt JSON or missing category arrays.

---

## T4 — Missing top-level category array in the source response

### Spec Text
> | Source response shape | JSON object with `episodes`, `streams`, and `clips` arrays |

### Alternatives
1. A response lacking one of the three arrays is a source metadata fetch
   failure (sync fails, vault unchanged).
2. A missing array is treated as an empty array, so every previously known
   entry of that category becomes `removed: true`.

### Choice
(1). The spec fixes the response *shape*, and the error table makes
"Source metadata fetch failure" the bucket for source data that does not match
its schema. Silently treating a missing array as empty would mass-mark entries
removed on a partial/garbled response — precisely the destructive outcome the
"leave the vault unchanged" rule protects against.

### Risk: 25
Author's most likely different reading: `data.get(category, [])`, treating an
absent array as empty rather than as a fetch failure.

---

## T5 — Booleans supplied where integers are required

### Spec Text
> Each source entry must contain all nine fields above with the stated types.
> If any source entry is missing a required field or has the wrong type, `sync`
> must fail as a source metadata fetch failure and leave the vault unchanged.

### Alternatives
1. `true`/`false` for `width`/`height`/`views`/`likes` is the wrong type
   (rejected).
2. Python's `bool` is a subclass of `int`, so a naive `isinstance(v, int)`
   check accepts it.

### Choice
(1) — reject. JSON distinguishes booleans from numbers, and the spec names the
type as "integer". Accepting `true` as a view count would be a type error.

### Risk: 15
Author's most likely different reading: a bare `isinstance(x, int)` check that
silently accepts JSON booleans as integers.

---

## T6 — Normalization of `published` on storage

### Spec Text
> | Static | `published` | string | Original publication datetime |

and

> | Date-only source values | Normalize to `00:00:00` time component |
> | Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix |

### Alternatives
1. Store the source text verbatim ("Original publication datetime").
2. Store a normalized `YYYY-MM-DDTHH:MM:SS` rendering: `2024-05-01` becomes
   `2024-05-01T00:00:00`, and a trailing `Z`/offset is dropped.

### Choice
(2). The Determinism table applies "Datetime text" to datetime text generally,
and the date-only rule exists precisely so that a date-only source value becomes
a full datetime; normalizing also makes the "newest `published` first" ordering
a plain string comparison. Unparseable strings are stored verbatim rather than
rejected, since the source schema only constrains `published` to be a string.

### Risk: 20
Author's most likely different reading: normalizing date-only values but
otherwise storing the source text verbatim (including any `Z` suffix).

---

## T7 — Timezone-qualified `published` values

### Spec Text
> | Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix |

### Alternatives
1. Drop the offset, keeping the wall-clock reading
   (`2024-01-01T10:00:00+02:00` → `2024-01-01T10:00:00`).
2. Convert to UTC, then drop the offset (→ `2024-01-01T08:00:00`).

### Choice
(1) — drop the suffix without shifting. The rule is phrased as a *text* rule
("without timezone suffix"), not a conversion rule, and no clause anywhere in
the spec nominates UTC as the canonical zone. Dropping is also the
locale/zone-independent operation the Determinism section asks for.

### Risk: 30
Author's most likely different reading: converting offsets to UTC before
formatting.

---

## T8 — Does a sync with no detected changes still rewrite the catalog?

### Spec Text
> | Backup trigger | Before every write to existing `catalog.json` |

and

> | Success effect | Update catalog with new, changed, removed, and restored entries |

### Alternatives
1. A successful `sync` always rewrites `catalog.json` (and therefore always
   refreshes `catalog.bak`), even when nothing changed.
2. `sync` skips the write when no history entry was appended, leaving
   `catalog.bak` absent/stale after a no-op sync.

### Choice
(1) — always write. "Before *every* write" is the backup rule, and a successful
sync is defined as updating the catalog; the entry-ordering contract also has to
be (re-)established on every successful sync. Always writing makes
`catalog.bak` deterministically present after any successful sync, which is the
easier property to assert.

### Risk: 20
Author's most likely different reading: writing only when something actually
changed, so a no-op sync leaves no `catalog.bak`.

---

## T9 — Whether static fields are refreshed when the source changes them

### Spec Text
> | Field Group | Field | Type | Notes |
> | Static | `id` | string | Source identifier |
> | Static | `published` | string | Original publication datetime |

### Alternatives
1. Static fields are captured at first observation and never rewritten.
2. Static fields are overwritten from the source on every sync.

### Choice
(1). They are labelled "Static", `published` is described as the *original*
publication datetime, and the `sync` Update Rules table enumerates the changes a
sync may make — all of them about tracked-field history, none about static
fields.

### Risk: 25
Author's most likely different reading: unconditionally re-assigning the four
static fields from the source entry each sync (which is also what the simplest
implementation does), making the two readings differ only when a source mutates
`published`/`width`/`height`.

---

## T10 — Creation of the `annotations` field

### Spec Text
> | Local-only fields | Source data does not include `removed` or `annotations` |

### Alternatives
1. `mvault` creates an `annotations` field on new entries.
2. `annotations` is merely reserved: it is never created by `sync`, but any
   existing local value must be preserved.

### Choice
(2). The "`entry` Stored Fields" table is exhaustive and lists ten fields, none
of them `annotations`; the `init` catalog layout likewise has no room for it.
The note exists to say that these names are never sourced from the remote
payload. Unknown/extra keys already present on an entry are preserved across
syncs.

### Risk: 10
Author's most likely different reading: emitting an empty `annotations` object
(or array) on every newly created entry.

---

## T11 — Transport used for the source `GET`

### Spec Text
> | Source request | HTTP `GET` to vault `source` URL |

### Alternatives
1. `urllib.request` from the standard library (also handles `file://` URLs).
2. The third-party `requests` package.

### Choice
(1) `urllib.request`. It keeps the CLI dependency-free so `python mvault.py`
works in any environment, and it additionally accepts `file://` sources, which a
test fixture may well use in place of a live server. Any non-2xx status,
transport error, non-JSON body, or schema violation is reported as a source
metadata fetch failure.

### Risk: 5
Author's most likely different reading: `requests`, which would differ only for
`file://` URLs or for tests that patch `requests` specifically.

---

## T12 — Repeated removal / repeated restoration

### Spec Text
> | Entry absent from current source | Append `removed: true` at sync timestamp |
> | Existing entry, unchanged tracked value | No new history entry for that field |

### Alternatives
1. Append `removed: true` on every sync in which the entry is absent.
2. Append only on transition, because `removed` is a tracked field and an
   unchanged tracked value gets no new history entry.

### Choice
(2). `removed` is listed as a tracked field in both the stored-fields and
history tables, so the "unchanged tracked value" rule governs it; the
"Previously removed entry reappears" row confirms that the interesting events
are the transitions.

### Risk: 10
Author's most likely different reading: re-appending `removed: true` on every
sync while the entry stays absent.

---

## T13 — Category matching when an `id` moves between categories

### Spec Text
> | First observation | Add entry to matching category; ... |

### Alternatives
1. Entries are keyed by `id` within a category, so the same `id` appearing in
   two categories yields two independent entries.
2. Entries are keyed by `id` globally and migrate between category arrays.

### Choice
(1) — match within the category. "Add entry to matching category" ties an entry
to the category it arrived in, there is no rule describing a migration, and a
migration would have to invent semantics for the history carried across.

### Risk: 15
Author's most likely different reading: a single global `id` index, so an entry
absent from its old category is marked removed while a new entry appears in the
new one (observable only for sources that reuse ids across categories).

---

## T14 — `version` values below `1`

### Spec Text
> | Condition | Required Result |
> | `version` greater than `3` | Version-related error to stderr; exit non-zero; no migration; no modification |

and the Supported Versions table, which lists only `1`, `2` and `3`.

### Alternatives
1. Only `version > 3` is an error; `0`, `-1` and other integers below `1` fall
   through to some other handling (loaded as v1, or rejected as a generic
   invalid vault).
2. Any integer outside the supported set `{1, 2, 3}` is a version-related
   error, treated exactly like `version > 3`.

### Choice
(2). The error table enumerates the *interesting* failure (a catalog from a
future release) but the Supported Versions table is the authority on what may
be loaded; `0` names no schema the spec defines, so there is nothing to load it
as. Reporting it as a version error is the behavior that keeps
"no migration; no modification" true.

### Risk: 8
Author's most likely different reading: a generic "invalid vault" error without
the word `version` in the message (the outcome — non-zero exit, untouched
catalog — is the same).

---

## T15 — What counts as "malformed v1 or v2 entry data"

### Spec Text
> | Malformed v1 or v2 entry data | Error to stderr; exit non-zero; leave `catalog.json` unchanged |

together with the Version 1 / Version 2 Entry Schema tables.

### Alternatives
1. **Strict**: every field in the entry schema table must be present with the
   documented type, every history object must be a JSON object whose keys are
   in the documented key format and whose values have the documented type.
   Extra, undocumented keys are tolerated and carried over.
2. **Lenient**: only outright structural breakage is rejected (an entry that is
   not an object, a history that is not an object, a v1 key that cannot be
   parsed as an integer); a missing `likes` or a string `width` is carried
   through the migration untouched.

### Choice
(1) — strict. The entry schema tables state a type for every field, and the
error row exists precisely to give "data that does not match the documented
schema" a defined outcome. A lenient reading would let a v1 entry with a
non-numeric history key reach the conversion step with nothing sensible to do,
which is the case the row most obviously covers. Unknown extra keys are
preserved rather than rejected, since the spec never forbids them.

### Risk: 30
Author's most likely different reading: lenient — validate only what the
conversion actually has to touch (history key parsing and category/array
shape), so an entry missing e.g. `preview` migrates successfully instead of
failing.

---

## T16 — A version 2 catalog missing one of its category arrays

### Spec Text
> | `episodes` | array | Episode entries |
> | `streams` | array | Stream entries |
> | `clips` | array | Clip entries |

and

> | Missing categories | Create empty `streams` and `clips` arrays |

(the latter appears only in the **v1**-to-v3 table).

### Alternatives
1. A v2 catalog without, say, `clips` is malformed: error, exit non-zero,
   catalog unchanged.
2. The v1 rule generalizes: any missing category array is created empty during
   the v2 migration too.

### Choice
(1). The "Missing categories" row is scoped to v1→v3, where the source schema
genuinely has no categories at all; the v2→v3 row instead says only "Preserve
`episodes`, `streams`, and `clips` placement", which presupposes that all three
exist. The v2 catalog schema lists all three as required fields.

### Risk: 25
Author's most likely different reading: `catalog.get(category, [])` in the
migration, silently creating the missing array and exiting 0.

---

## T17 — Whether `serve` and `digest` exist yet

### Spec Text
> | Load trigger | Any command that reads a vault (`sync`, `serve`, `digest`, and future commands) |

### Alternatives
1. `serve` and `digest` are named only as illustrations of the rule's reach
   ("and future commands"); neither is specified anywhere, so neither is
   implemented and the rule is exercised through `sync` and `migrate`.
2. Both are implemented now, guessing at their behavior.
3. Implement the one whose contract is guessable from this spec alone — a
   read-only reader that loads the vault and writes nothing — and leave the
   long-running `serve` (port, routes, shutdown all unspecified) out.

### Choice
(3). "Read-only access | Loading a v1 or v2 catalog for a read-only operation
does not rewrite `catalog.json`" is a *testable* rule that needs some read-only
command to exist, and `digest` is the natural one: it loads the vault, prints a
summary, writes nothing. `serve` is omitted because a blocking HTTP server with
no specified port or routes cannot be guessed, and guessing wrong would hang a
caller rather than fail cleanly.

### Risk: 35
Author's most likely different reading: `serve` and `digest` are fully
specified elsewhere in the author's spec series and already implemented, so
their output format (and `serve`'s existence) differs from this implementation.

---

## T18 — The migration timestamp itself

### Spec Text
> | `removed` | Add `{<migration-timestamp>: false}` to every entry |

and

> | Migration-added timestamp scope | Each migration-added `removed` timestamp must be ISO 8601; cross-entry equality is not required |

### Alternatives
1. The raw wall clock at migration time, used verbatim for every entry.
2. The wall clock, but advanced to a strictly later second than every history
   key already present in the catalog (the same rule `sync` timestamps follow),
   so the migration-added `false` is unambiguously the current value.

### Choice
(2). A migrated entry's `removed` history has exactly one key, and the catalog's
"current value = value at the latest datetime key" rule only reads correctly if
that key is not older than the converted history beside it. In practice the two
readings coincide, since legacy history keys are in the past; they differ only
for a catalog carrying future-dated keys. One shared timestamp is used for all
entries of a run, which the "cross-entry equality is not required" row permits.

### Risk: 12
Author's most likely different reading: plain `datetime.now()`, so a catalog
containing future-dated history keys gets a migration stamp that is older than
them.

---

## T19 — Version 2 history keys are preserved verbatim

### Spec Text
> | History keys | Convert every UNIX-epoch string key to ISO 8601 format |

(in the **v1**-to-v3 table only; the v2→v3 table has no history row)

and

> | `2` | Supported | ... ISO 8601 history keys ... |

### Alternatives
1. v2 keys are already ISO 8601, so migration copies them unchanged — including
   a key such as `2024-06-15T09:40:00Z` or `2024-06-15T09:40:00+02:00`, which
   is valid ISO 8601 but not the project's canonical datetime text.
2. Migration re-renders every v2 key into `YYYY-MM-DDTHH:MM:SS`.

### Choice
(1) — preserve. The v2→v3 table lists exactly three effects (`removed`,
`annotations`, `version`) plus two preservation rules, and a key rewrite is
conspicuously absent where the v1 table spells one out. Validation accordingly
accepts any parseable ISO 8601 key and rejects anything else (e.g. an
epoch-seconds key in a v2 catalog) as malformed entry data.

### Risk: 15
Author's most likely different reading: normalizing every key through the same
formatter used elsewhere, which differs only for keys carrying a timezone
suffix or fractional seconds.

---

## T20 — Fate of the v1-only keys and of pre-existing `annotations`

### Spec Text
> | `source_id` | Convert to `source` using `https://media.example.com/channel/<source_id>` |
> | Entries | Move every object from `entries` to `episodes` |
> | `annotations` | Add `[]` to every entry |

### Alternatives
1. "Convert" and "move" are replacements: the migrated catalog has `source` and
   `episodes` and no longer has `source_id` or `entries`. An entry that already
   carries `annotations` (not legal in v1/v2, but possible in a hand-edited
   file) keeps its value; `removed` is (re)written to the documented
   `{<stamp>: false}`.
2. The legacy keys are left in place alongside the new ones, and
   `annotations` is overwritten with `[]` unconditionally.

### Choice
(1). "Convert to" and "Move" both describe relocation, not duplication, and the
Supported Versions table describes v3 as having `source` and category arrays —
a catalog still carrying `source_id`/`entries` would not match either the v1 or
the v3 shape. Preserving a pre-existing `annotations` value follows the general
rule that `mvault` never discards local-only data.

### Risk: 10
Author's most likely different reading: unconditional
`entry["annotations"] = []`, which differs only for hand-edited legacy files
that already have the field.

---

## T21 — Entry order produced by `migrate`

### Spec Text
> | Entries | Move every object from `entries` to `episodes` |
> | Categories | Preserve `episodes`, `streams`, and `clips` placement |

### Alternatives
1. `migrate` preserves the order the entries had in the legacy catalog.
2. `migrate` re-sorts each category into the catalog ordering contract (newest
   `published` first, ties by lexicographically smaller `id`), the way `sync`
   does before every write.

### Choice
(1) — preserve. Both migration tables describe the transformation as a move /
preservation and say nothing about ordering, and the ordering contract is
stated as an effect of `sync`. A subsequent `sync` re-establishes the order
anyway, so nothing downstream depends on `migrate` doing it.

### Risk: 30
Author's most likely different reading: reusing the shared "write catalog"
helper, which sorts, so a migrated catalog comes out ordered newest-first
regardless of the legacy order.

---

## T22 — `migrate` on a v3 vault: exit status and output

### Spec Text
> | Effect on v3 | No-op; no backup written |

### Alternatives
1. Success (exit `0`) with a short note on stdout; nothing on disk changes.
2. An error, on the grounds that there is nothing to migrate.

### Choice
(1). "No-op" describes an absence of effect, not a failure; the error table
lists the conditions that must exit non-zero and this is not among them.

### Risk: 5
Author's most likely different reading: the same exit status with different (or
no) stdout text.

---

## T23 — `published` is not re-normalized during migration

### Spec Text
> | `published` | string | ISO 8601 datetime |

(v1 and v2 entry schemas; neither migration table mentions `published`)

### Alternatives
1. Migration copies `published` verbatim.
2. Migration passes it through the same normalization `sync` applies to source
   values (date-only → `T00:00:00`, timezone suffix dropped).

### Choice
(1) — verbatim. Both migration tables enumerate the fields they touch and
`published` is not among them; the legacy schemas already promise an ISO 8601
datetime, so there is nothing to normalize for a conforming catalog.

### Risk: 12
Author's most likely different reading: running every migrated entry through
the same constructor `sync` uses, which would normalize a date-only or
`Z`-suffixed legacy `published`.

---

## T10 — addendum (`annotations` on entries created by `sync`)

This spec's Supported Versions table describes the v3 native format as having
`annotations`, which weakens but does not overturn the T10 choice: the
`entry` Stored Fields table of the core spec remains the exhaustive list of
fields `sync` writes, and only the *migration* rows mandate creating
`annotations`. So migrated entries get `annotations: []`, entries created by
`sync` still do not, and any existing value is preserved either way.
Revised risk for T10: **25** — the author may well create `annotations` on
every new entry now that v3 is documented as carrying it.

---

## T3 — addendum (resolved by the legacy-loading spec)

The legacy-loading spec resolves T3's "what makes a vault invalid" question for
the `version` field specifically: `1`, `2` and `3` are all valid and loadable
(v1/v2 migrated in memory), while a missing, non-integer or greater-than-`3`
version is an error that must not modify the catalog. The rest of the T3 choice
— root-schema violations such as a non-string `source` or a missing category
array are "invalid vault" errors — is unchanged, and now applies per version:
each catalog is validated against the schema its `version` declares.
