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

### Resolved
The viewer spec settles this: `serve` *is* a required command with a defined
CLI, bind address and HTTP surface, so alternative (3) was wrong about leaving
it out. It is implemented now (see T41-T52); the read-only reading of the
`digest`/`serve` load rule that this entry chose was correct and still holds --
the viewer reads every version in its own format and writes nothing.

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

---

## T24 — How `<source>/media/<entry_id>` is built from the `source` URL

### Spec Text
> | Media | `<source>/media/<entry_id>` | `<vault>/media/` | Filename contains entry `id` |

### Alternatives
1. Literal concatenation: `source.rstrip("/") + "/media/" + id`, so a `source`
   of `https://h/source.json` yields `https://h/source.json/media/e1`.
2. Treat `source` as a *base* and resolve `media/<id>` relative to it
   (`urljoin`), so `https://h/source.json` yields `https://h/media/e1` — the
   last path segment is replaced.
3. Strip a trailing filename-looking segment (anything containing a `.`) before
   appending.

### Choice
(1) — literal concatenation with a single trailing-slash guard. The spec writes
the template as `<source>/media/<entry_id>` where `<source>` is the same token
used everywhere else for the catalog's `source` field; nothing in the spec
mentions relative resolution or segment stripping, and `urljoin` semantics
would silently produce a different URL depending on whether `source` happens to
end in a slash.

### Risk: 30
Author's most likely different reading: `urljoin(source, "media/" + id)`, which
differs whenever the vault `source` does not end in `/`.

---

## T25 — Deriving the media extension from `Content-Type`

### Spec Text
> | Media extension without override | Derive from HTTP `Content-Type` |

### Alternatives
1. Python's `mimetypes.guess_extension`, whose answers vary by version and
   platform (`image/jpeg` → `.jpg`, but `audio/mpeg` → `.mp3` only on some
   versions, and it returns `None` for unknown types).
2. A fixed table for the common media/image types, falling back to
   `mimetypes.guess_extension` and then to a generic extension.
3. The subtype of the MIME type verbatim (`video/mp4` → `mp4`,
   `image/jpeg` → `jpeg`).

### Choice
(2). A fixed table pins the cases a media vault actually sees
(`video/mp4`→`mp4`, `video/webm`→`webm`, `audio/mpeg`→`mp3`,
`image/jpeg`→`jpg`, `image/png`→`png`, `image/gif`→`gif`,
`image/webp`→`webp`), which keeps filenames stable across Python versions, and
still degrades gracefully via `mimetypes` and a final `bin` fallback. Header
parameters (`; charset=...`) are stripped, and a missing header yields `bin`.

### Risk: 45
Author's most likely different reading: subtype-verbatim
(`image/jpeg` → `e1.jpeg`), which differs from this choice precisely on the
JPEG case a fixture is most likely to use.

---

## T26 — Whether previews follow media candidate selection and the limits

### Spec Text
> | Candidate selection | Only entries without a corresponding media file in `<vault>/media/` are candidates |

and

> | Preview | `<source>/preview/<entry_id>` | `<vault>/previews/` | Filename contains entry `id` |

### Alternatives
1. Previews are fetched for exactly the entries selected as media candidates,
   so the per-category limit bounds preview downloads too.
2. Previews have their own candidate rule (entries without a file in
   `<vault>/previews/`) and are unbounded by `--episodes`/`--streams`/`--clips`,
   since those options say "media downloads".
3. Previews are fetched for every catalog entry on every run.

### Choice
(1). The Download Rules table states exactly one candidate rule and one
per-category limit rule, both phrased in terms of "entries"; only the *option*
descriptions narrow the count to "media downloads", which explains what the
number caps, not which entries get processed. Reading the single candidate list
as driving both assets also makes the download phase idempotent — a second run
with everything already fetched issues no requests at all.

### Risk: 40
Author's most likely different reading: previews are selected independently of
media (present-in-`previews/` check), so an entry whose media already exists but
whose preview failed earlier still re-fetches the preview.

---

## T27 — Which failures are transient, and how many retries

### Spec Text
> | Permanent download failure | Warning to stderr; continue with remaining entries |
> | Transient download failure | Retry, then warn to stderr after retries exhausted; continue with remaining entries |

### Alternatives
1. Classify by HTTP status: 4xx (except `408`/`429`) permanent, 5xx plus
   `408`/`429` plus transport/timeout errors transient.
2. Only `404`/`410` are permanent; everything else is transient.
3. Retry everything a fixed number of times regardless of classification.

### Choice
(1), with three total attempts (initial + 2 retries) and no sleep between them.
4xx means "the server understood and this will not change"; 5xx and transport
errors are the textbook transient class. Three attempts is the common default
and keeps a failing run fast enough for a test suite; sleeping would make the
observable behavior depend on wall clock, which the Determinism table
discourages.

### Risk: 35
Author's most likely different reading: a different retry count (2 or 3
*retries* rather than 3 total attempts), which a fixture counting requests
against a flaky endpoint would detect.

---

## T28 — Partial-download artifacts

### Spec Text
> | Partial artifacts | Stale partial-download artifacts must not block a later successful download |

### Alternatives
1. Download to a sibling temporary file (`<id>.<ext>.part`) and `os.replace` it
   into place on success, so a failure never leaves a final-looking file; a
   pre-existing `.part` is ignored by candidate selection and overwritten.
2. Download straight to the final path and delete it on failure.
3. Download to a directory outside the vault.

### Choice
(1). "Partial artifacts" names a file that exists and is incomplete, and the
rule is that it must not *block* a later download — which only bites if such a
file could be mistaken for a finished media file. Writing through `<id>.<ext>.part`
and excluding `*.part` from the candidate-selection glob satisfies the rule and
makes the final rename atomic.

### Risk: 20
Author's most likely different reading: a different suffix (`.tmp`,
`.download`) or writing in place — visible only to a fixture that inspects
`<vault>/media/` mid-failure or pre-seeds an artifact with a specific name.

---

## T29 — When the metadata save happens relative to downloads

### Spec Text
> | Persistence boundary | Metadata changes must be durably saved before successful sync returns, including runs with download failures |

and

> | Save timing | Metadata phase persists before successful `sync` returns |

### Alternatives
1. Write `catalog.json` at the end of the metadata phase, before any download
   is attempted.
2. Write it after the download phase, in a `finally`-style block.

### Choice
(1). "Metadata phase persists" attaches the write to the metadata phase, and
writing first is the only ordering under which a crash *during* downloads still
leaves the metadata saved. Both orderings satisfy the literal wording for a
normal run, so nothing observable is lost.

### Risk: 5
Author's most likely different reading: save after downloads, which is
indistinguishable except under a mid-download crash.

---

## T30 — What `--skip-metadata` does to a legacy vault

### Spec Text
> | `--skip-metadata` | flag | Skip source fetch and metadata update; run download phase against existing vault state |

and

> Because `sync` auto-migrates v1 and v2 vaults to v3 during the metadata
> phase, the download phase always operates against a v3 catalog. The source
> URL for downloads is the migrated `source` value.

### Alternatives
1. `--skip-metadata` skips the whole metadata phase including its persistence,
   so a v1/v2 catalog is migrated only *in memory* (as every read-only load
   already does) and `catalog.json` is left byte-for-byte alone.
2. `--skip-metadata` only skips the *source fetch*, still migrating and
   rewriting `catalog.json`.

### Choice
(1). The option skips "source fetch **and** metadata update", and persisting a
migration is a metadata update. The legacy-loading rules already guarantee an
in-memory v3 view for any reader, so "the download phase always operates
against a v3 catalog" and "the source URL is the migrated `source` value" both
hold without writing anything.

### Risk: 25
Author's most likely different reading: `--skip-metadata` still persists the
auto-migration, so a v1/v2 vault comes out as v3 on disk after a download-only
run.

---

## T31 — What the post-sync counts count

### Spec Text
> | Counts reported | Added, removed, updated |
> | Post-sync counts | Deterministic for the same vault state and source metadata |

### Alternatives
1. Mutually exclusive buckets with the digest's precedence: an entry newly
   marked `removed: true` counts only as removed; a brand-new entry counts only
   as added; anything else with a tracked-field change counts as updated.
2. Overlapping counts: a newly removed entry is both "removed" and "updated"
   (its `removed` history did change).
3. "Updated" counts *fields* changed rather than entries.

### Choice
(1). The spec puts the three counts in one row of a summary about the run and
gives the digest — the other consumer of the same classification — an explicit
"Each entry may appear once" precedence. Mirroring it keeps the two features
consistent and makes the counts sum to something a reader can interpret.

### Risk: 40
Author's most likely different reading: a removal also increments "updated"
(counts computed independently per bucket), or "updated" counts field changes.

---

## T32 — Digest layout: labels, ordering and nesting

### Spec Text
> | Category grouping | Changes grouped by category (v1: single `Entries` group; v2/v3: per-category) |
> | Grouping within category | Changes grouped by type |
> | Entry order within group | Deterministic |

### Alternatives
1. Category header line, indented group header lines, indented `- ` entry
   lines; categories in catalog order (`Episodes`, `Streams`, `Clips`); groups
   in the documented precedence order (removals, additions, field updates);
   entries in catalog order.
2. Groups as the outer level and categories inner.
3. A flat, one-line-per-change listing with a `category/group` prefix.
4. Entries sorted by id or by title rather than catalog order.

### Choice
(1). The spec nests "Grouping within category" *inside* "Category grouping", so
category is the outer level. Category order follows the order the categories
are listed in everywhere else in the spec; group order follows the precedence
table, which is the only ordering the spec supplies for groups; entry order
follows catalog order, which is the same "deterministic" order the Download
Rules already use for candidates. Labels are `Episodes` / `Streams` / `Clips` /
`Entries` (the spec's own words) and `Removed` / `Added` / `Updated`.

### Risk: 55
Author's most likely different reading: different literal labels or entry
ordering (e.g. sorted by id), since the spec fixes only the category words and
leaves group labels and entry order to "deterministic".

---

## T33 — Contents of the digest trailing line

### Spec Text
> | Trailing line | Metadata about the digest run |
> | Source reference | The trailing line includes the resolved source URL for the loaded vault version |

and

> | Wall-clock usage outside digest trailing line | Not part of file naming or vault content |

### Alternatives
1. Vault name, loaded catalog version, resolved source URL, and a wall-clock
   timestamp.
2. Only the resolved source URL.
3. Source URL plus counts of the changes reported above.

### Choice
(1). The Determinism table's carve-out — wall clock is banned everywhere
*except* the digest trailing line — only makes sense if the trailing line is
where a timestamp is expected, and "metadata about the digest run" naturally
covers which vault, at which version, from which source, when. The format is
fixed, so "Deterministic format" holds.

### Risk: 50
Author's most likely different reading: a different set of fields or a
different order; any fixture doing an exact-string comparison on this line will
disagree.

---

## T34 — `removed` as a tracked field for the digest Additions rule (v3)

### Spec Text
> | Additions | Entry has only initial observations; no tracked field has a second history entry | Same rule applied to available tracked fields |

### Alternatives
1. In v3 the tracked fields are the six stored histories including `removed`,
   so a second `removed` observation (even `false` → `false`) disqualifies an
   addition.
2. `removed` is excluded from the Additions test because it is local-only and
   never comes from the source.

### Choice
(1). "Tracked field" is the spec series' established term for the six
histories, and the v1/v2 column says "available tracked fields" — which is only
a meaningful qualifier if v3's set is larger, i.e. includes `removed`. This also
makes the Removals rule (which reads `removed` history) and the Additions rule
use one consistent field set.

### Risk: 20
Author's most likely different reading: `removed` excluded from the Additions
test, so an entry whose only second observation is a repeated `removed: false`
still counts as an addition.

---

## T35 — How reappearance is rendered

### Spec Text
> | Reappearance after removal (v3 only) | Indicate reappearance alongside any other changed fields |

### Alternatives
1. The entry lands in Field updates and its parenthesised suffix leads with a
   `reappeared` marker followed by the other changed field names.
2. A fourth top-level group, `Reappeared`.
3. The literal field name `removed` in the suffix, with no special wording.

### Choice
(1). The Group Precedence table lists exactly three groups, so reappearance is
not its own group; a reappearance is by construction a `removed` field update
(latest `false`, prior `true`), which puts it in Field updates. "Alongside any
other changed fields" describes the suffix, so the marker goes there:
`Title (reappeared, title)`.

### Risk: 45
Author's most likely different reading: the suffix says `removed` like any
other field, or reappearance is called out with different wording.

---

## T36 — `--format` and candidate selection

### Spec Text
> | Candidate selection | Only entries without a corresponding media file in `<vault>/media/` are candidates |
> | `--format=<str>` | string | Override media download format and output extension |

### Alternatives
1. Candidate selection stays extension-agnostic: any `<id>.*` file in
   `<vault>/media/` disqualifies the entry, whatever `--format` says.
2. With `--format=webm`, only `<id>.webm` disqualifies the entry, so a run with
   a new format re-downloads everything in the new format.

### Choice
(1). The candidate rule is stated once, without reference to the format option,
and speaks of "a corresponding media file" rather than "the file this run would
write". Re-downloading the whole catalog because a flag changed would also make
`--format` surprisingly expensive.

### Risk: 30
Author's most likely different reading: format-aware selection, so
`--format=webm` over a vault of `.mp4` files re-fetches every entry.

---

## T37 — Which asset failures produce which warnings

### Spec Text
> | Permanently unavailable content during download | stderr | `0` | Warning per affected entry; continue |

### Alternatives
1. Media and preview are attempted independently; each failure warns, so an
   entry can produce two warnings and a media success can coexist with a
   preview failure.
2. A media failure skips the preview attempt for that entry.
3. One combined warning per entry regardless of how many assets failed.

### Choice
(1). "Warning per affected entry" sets a floor on granularity, not a ceiling,
and "continue with remaining entries" is about not aborting. Attempting both
assets independently means a transient preview outage does not cost the media
file, and every warning names the entry id so the "per affected entry"
requirement is satisfied either way.

### Risk: 25
Author's most likely different reading: the preview is skipped once the media
download fails, so a fixture that serves only the preview sees no request.

---

## T38 — Digest handling of a v1 catalog with ISO history keys

### Spec Text
> | v1 | Single group: `Entries` | Not available (no `removed` field) | UNIX-epoch string keys |

### Alternatives
1. A v1 catalog whose keys are not epoch strings is malformed and `digest`
   errors, consistent with the per-version schema validation the legacy-loading
   spec established.
2. `digest` accepts whatever keys are present and falls back to lexicographic
   comparison when a key does not parse as an integer.

### Choice
(1). The version's declared key format is part of its schema; the existing
loader already rejects a v1 catalog with non-epoch keys, and `digest`
"works directly on v1, v2, and v3 catalogs" — it does not loosen validation.

### Risk: 30
Author's most likely different reading: a permissive digest loader that never
validates key formats, since `digest` is described as read-only reporting.

---

## T39 — Scope of `--episodes`/`--streams`/`--clips` when `--skip-download`

### Spec Text
> | Metadata-only run | `--skip-download` |

### Alternatives
1. `--skip-download` wins: the limits are accepted (they are recognized
   options) but have nothing to act on.
2. Combining a limit with `--skip-download` is a usage error.

### Choice
(1). The Error Handling table makes only *malformed* limits and *unrecognized*
options errors; a well-formed limit is neither. Silently ignoring it matches
the phase model, where limits are a download-phase concept.

### Risk: 8
Author's most likely different reading: rejecting the combination as
contradictory.

---

## T40 — Whether a digest group header is emitted for an empty group

### Spec Text
> | Empty category | Omitted |

### Alternatives
1. Empty *groups* are omitted too (only "Empty category" is stated, but the
   same reasoning applies), and a category with no non-empty group is omitted
   entirely.
2. Every category that has any entries prints all three group headers, empty or
   not.

### Choice
(1). The spec omits empty categories to keep the digest readable; printing a
bare `Removed:` header with nothing under it contradicts that intent, and the
`Removals` row for v1/v2 explicitly says the group is "omitted entirely" when
not applicable — establishing that groups, not just categories, get omitted.

### Risk: 10
Author's most likely different reading: fixed three-group scaffolding under
each non-empty category.

---

## T41 — Where the recent-vault list is persisted

### Spec Text
> | Trigger | Navigation to any vault through viewer |
> | Persistence | Later browser session from same browser must still show visited vault |

### Alternatives
1. Server-side: a small JSON file, so any client of that server sees the list
   and it survives a server restart.
2. Client-side `localStorage` written by inline JavaScript on every vault page.
3. A cookie set on each vault navigation and read when rendering `/`.

### Choice
(1), stored as `.mvault-recent.json` in the working directory the server was
launched from — the same directory the vault names themselves resolve against.
"Later browser session from same browser" is a *minimum* the store must meet,
and a server-side file meets it unconditionally, including across a restart of
`serve` itself. It also keeps the landing page meaningful to a client that does
not run JavaScript or keep cookies, which is what the rest of the spec assumes
(every other viewer requirement is plain HTML with links and a form).

Scoping the file to the working directory rather than the user's home keeps one
directory of vaults from leaking its history into another.

### Risk: 40
Author's most likely different reading: a browser-owned store (cookie or
`localStorage`), so a fixture that drives the viewer without cookies/JS sees an
empty recent area where this implementation shows the vault — and, conversely,
a fixture asserting that a *fresh* client sees nothing after another client
visited a vault would fail here.

---

## T42 — A `catalog` field that is present but empty

### Spec Text
> | `POST` | `/` | Accept form-encoded body; redirect to `/catalog/<value>` when `catalog` field is present, otherwise redirect to `/` |

and

> | Missing `catalog` field on `POST /` | Redirect to `/` |

### Alternatives
1. "Present" means the key exists, so `catalog=` redirects to `/catalog/`
   (which then has no vault name and bounces back to `/`).
2. "Present" means a usable vault name was supplied, so an empty or
   whitespace-only value is treated like a missing field and redirects
   straight to `/`.

### Choice
(2). The value is interpolated into a path as `<value>`; an empty `<value>`
names no vault, and the spec's only stated purpose for the field is to carry a
vault name. Both readings end the user on `/`, but (2) gets there in one
redirect instead of two and never emits a `/catalog/` URL that means nothing.
Submitting the form with the box left blank is the common case this protects.

### Risk: 25
Author's most likely different reading: a literal `"catalog" in form` check, so
an empty value redirects to `/catalog/` first.

---

## T43 — How the vault-not-found indication reaches `/`

### Spec Text
> | Non-existent vault on any `/catalog/<name>` route | Redirect to `/`; landing page shows vault-not-found indication; response must not be HTTP `500` |

### Alternatives
1. Redirect to `/?missing=<name>` and render the indication from the query
   string.
2. Redirect to exactly `/` and carry the pending notice in server state,
   rendering (and clearing) it on the next `GET /`.
3. Render the landing page directly with status `404`, no redirect at all.

### Choice
(2). The spec says "Redirect to `/`", and a fixture that reads the `Location`
header will compare it against `/` — a query string would fail that comparison
while adding nothing the spec asks for. (3) contradicts "Redirect" outright.
The notice is one-shot, so reloading `/` afterwards shows the clean landing
page.

### Risk: 30
Author's most likely different reading: a query parameter such as
`/?missing=<name>` or `/?error=...`, which still satisfies "landing page shows
vault-not-found indication" but changes the `Location` header.

---

## T44 — Where on the line the viewer link goes, and what separates it

### Spec Text
> | `digest <name>` | Each changed-entry line includes viewer link on same line as title |
> | Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>` |

### Alternatives
1. Append the bare URL after the existing entry text, separated by a single
   space: `- New Title (title) http://127.0.0.1:8840/catalog/v/episodes/e1`.
2. Put the URL before the title.
3. Wrap it in punctuation (`<...>`, `[...]`, `-> ...`) or a label
   (`link: ...`).

### Choice
(1). The row is phrased as the link being added *to* the existing line ("on
same line as title"), which reads as an append rather than a reordering, and
the Link format row gives the URL with no surrounding punctuation — so nothing
is added around it. Keeping the changed-field annotation between the title and
the link preserves the previously specified digest line shape exactly.

### Risk: 35
Author's most likely different reading: a different separator or decoration
(e.g. `title — <url>` or `<url>` in angle brackets), which breaks any fixture
doing an exact-line comparison but not one that searches for the URL substring.

---

## T45 — Whether the post-sync summary gains per-entry lines

### Spec Text
> | Post-sync summary | Each changed-entry line includes viewer link on same line as title |

and, from the earlier spec,

> | Counts reported | Added, removed, updated |

### Alternatives
1. The post-sync summary already had (or must now grow) one line per changed
   entry, carrying that entry's title; the counts line stays.
2. The summary stays counts-only and the rule is vacuous.
3. The counts line is replaced by the per-entry listing.

### Choice
(1). "Each changed-entry line ... on same line as title" presupposes lines that
name individual entries by title, which counts-only output does not have, so
the rule is only meaningful if such lines exist. The counts are a separately
specified requirement and are kept. The listing reuses the digest's category /
group layout and labels so the two human-facing reports read alike, and its
entries are the ones this run actually changed (not the digest's
whole-history classification).

### Risk: 45
Author's most likely different reading: the same idea but a different layout --
a flat list, different labels, or entries ordered by the sync's processing
order rather than final catalog order.

---

## T46 — "a media filename ... contains entry `id`"

### Spec Text
> | Downloaded state (v2/v3) | Entry counts as downloaded when a media filename in `<vault>/media/` contains entry `id` |

### Alternatives
1. Literal substring containment against every name in `<vault>/media/`,
   including in-progress `*.part` artifacts.
2. Substring containment, but `*.part` artifacts are excluded, mirroring the
   download phase's candidate selection.
3. The stricter `<id>` / `<id>.<ext>` prefix match the download phase uses to
   decide whether an entry already has media.

### Choice
(1). The spec deliberately words this rule as *contains*, in a series that
elsewhere describes the download phase's own matching separately; taking it
literally is the only reading that needs no extra assumption. A `.part` file
is transient — the download phase renames it into place on success and removes
it on failure — so the two readings differ only for a vault inspected mid
download or seeded by hand.

### Risk: 25
Author's most likely different reading: `.part` artifacts excluded, so an entry
with only a partial download shows as undownloaded.

### Annotation (reinforced by the detail-page spec)
> | Downloaded media discovery | A downloaded media file counts as matching the entry when a saved filename in `<vault>/media/` contains the entry `id`; the detail page uses that exact filename in the media static endpoint URL |

The later spec restates the rule as plain containment and adds that the matched
name is used verbatim in the media URL, so reading (1) stands. Which of several
containing names is picked is a new question, recorded as [T56](#t56).

---

## T47 — `/catalog/<name>/<category>/<id>` for an id that is not there

### Spec Text
> | `GET` | `/catalog/<name>/<category>/<id>` | HTML response for that viewer link target; may reuse the category listing page with the entry highlighted or otherwise surfaced |

### Alternatives
1. Serve the category listing anyway, with nothing highlighted (`200`).
2. Return `404`.

### Choice
(1). The route's stated contract is "HTML response for that viewer link
target", and the sanctioned implementation is the category listing with the
entry surfaced; an id that is absent simply has nothing to surface. The error
table lists specific conditions that earn `400`/`404` and an unknown id is not
among them, so a `200` listing is the conservative behaviour — it is also what
a stale bookmark should show.

### Risk: 20
Author's most likely different reading: `404` for an id that is not in the
category.

### Annotation (resolved against this choice)
> | Missing entry in specified category | HTTP `404`, or redirect to category listing with error indication |

The detail-page spec replaces the "may reuse the category listing" licence with
a real detail page and names `404` first, so choice (1) -- a plain `200`
listing -- is no longer conforming. The implementation now returns `404`; see
[T55](#t55).

---

## T48 — Recent-vault links when the vault is no longer readable

### Spec Text
> | Link target | Each recent-vault link points directly to that vault's resolved default category page |
> | Recent-vault links on `/` | Use the same resolved default-category route as `/catalog/<name>` would redirect to |

### Alternatives
1. Drop vaults that can no longer be read from the recent area.
2. Keep them, linking to `/catalog/<name>`, which redirects to `/` and shows
   the not-found indication.
3. Keep them with a guessed `episodes` route.

### Choice
(2). Resolution requires reading the catalog, and if that fails there is no
version to resolve with; `/catalog/<name>` is exactly "what `/catalog/<name>`
would redirect to" for a name the viewer cannot resolve, and following it
produces the spec's own not-found behaviour. Dropping the entry would
contradict the persistence rule for a vault that is merely temporarily absent.

### Risk: 15
Author's most likely different reading: pruning unreadable vaults from the
recent list.

---

## T49 — Whether `digest` and `sync` can override the viewer link host/port

### Spec Text
> | Default scheme | `http://` |
> | Default host | `127.0.0.1` |
> | Default port | `8840` |

### Alternatives
1. These are the only values: the reports always print
   `http://127.0.0.1:8840/...` with no way to change them.
2. They are *defaults*, so the report commands accept `--host` / `--port`
   overrides the way `serve` does.

### Choice
(2), implemented additively: `digest` and `sync` accept optional `--host` and
`--port`, and with neither supplied the output is exactly the fixed
`http://127.0.0.1:8840/...` form of reading (1). Calling a value a "default"
implies something can replace it, and `serve --host/--port` means a user's
viewer genuinely can live elsewhere. Because the options are optional and the
defaults are unchanged, no behaviour observable without them differs between
the two readings.

### Risk: 5
Author's most likely different reading: no such options, so a fixture that
asserts `sync --host=... ` is rejected as an unrecognized option would fail.

---

## T50 — Redirect or `400`/`404` for an invalid category

### Spec Text
> | Invalid category on `GET /catalog/<name>/<category>` for v2/v3 vault | Redirect to `/catalog/<name>/episodes` or return HTTP `400`/`404` |

### Alternatives
1. Redirect to the vault's default category page.
2. Return `404`.
3. Return `400`.

### Choice
(1). The spec permits all three, so this is a free choice; redirecting matches
what `/catalog/<name>` already does for an unresolved category and leaves the
user on a usable page instead of a dead end. It is also the option the spec
names first and spells out in full.

### Risk: 0

---

## T51 — Does a failed vault navigation count as a visit?

### Spec Text
> | Trigger | Navigation to any vault through viewer |

### Alternatives
1. Only a navigation that actually resolved a vault is recorded.
2. Every `/catalog/<name>` request is recorded, including names that do not
   resolve.

### Choice
(1). "Navigation to any vault" presupposes there is a vault; a request for a
name that does not resolve is answered by the not-found rule, not by a vault
page, so nothing was visited. Recording misses would fill the landing page with
typos that permanently link to a not-found redirect.

### Risk: 10
Author's most likely different reading: recording the name unconditionally on
every `/catalog/<name>` request.

---

## T52 — Opening the browser when there is no browser

### Spec Text
> | `serve` without `<name>` | Start server and open browser to `/` |
> | `serve <name>` | Start server and open browser to default category page for vault |

### Alternatives
1. Opening the browser is best-effort: the server binds first, the open is
   attempted on a background thread, and a failure (headless machine, no
   browser, a `BROWSER` command that blocks) is ignored.
2. Failing to open a browser is an error that aborts `serve`.
3. Open the browser before binding the socket.

### Choice
(1). The row's primary clause is "Start server"; the viewer is useful over HTTP
whether or not a local browser exists, and a headless host is exactly where one
runs a server. Binding first guarantees the browser cannot reach the port
before it is listening, and backgrounding the open means a browser command that
blocks (Python's `GenericBrowser` waits for the child) cannot stop the server
from serving.

### Risk: 5
Author's most likely different reading: a synchronous `webbrowser.open` call,
which only differs when that call blocks or raises.

---

## T53 — Shape of the embedded chart payload

### Spec Text
> | Embedding style | Machine-readable structured data embedded in HTML |
> | Payload container and key names | Unspecified as long as the payload remains machine-readable |

### Alternatives
1. A `<script type="application/json">` element holding one object keyed by
   field name, whose points are `{"timestamp": ..., "value": ...}` objects.
2. The same, but with points as two-element `[timestamp, value]` arrays.
3. The history object reproduced as-is (`{"<timestamp>": value, ...}`), with
   normalized keys.
4. Per-point HTML `data-` attributes rather than a JSON payload.

### Choice
(1). The spec explicitly declines to fix the container and key names, so the
only real requirement is that a reader can recover the pairs and the order.
A JSON `<script>` is the standard way to hand structured data to a page, and
named `timestamp`/`value` keys are self-describing where positional pairs are
not. Reading (3) is rejected because a JSON object gives no ordering guarantee
to a consumer, and "Point order | Chronological, oldest first" is a hard rule.

### Risk: 20
Author's most likely different reading: positional `[timestamp, value]` pairs,
which only matters if the hidden fixture indexes points rather than parsing
them structurally.

---

## T54 — Whether a single-point field's data is dropped as well as its chart

### Spec Text
> | Single-point history | Chart for that field may be omitted |

### Alternatives
1. Omit only the rendered chart; the point still appears in the payload.
2. Omit the field from the machine-readable payload too.

### Choice
(1). The row licenses dropping "the chart for that field" -- the visual --
while the table's other rows describe the payload without carving out an
exception for short histories, and "no filtering or replacement" argues for
keeping every point that exists. Because the omission is permissive, a test
cannot require the chart to be absent; it can only require that the page still
renders, which both readings satisfy.

### Risk: 20
Author's most likely different reading: the single point dropped from the
payload as well, so a fixture asserting the field is absent would fail here.

---

## T55 — Missing entry: `404` or redirect

### Spec Text
> | Missing entry in specified category | HTTP `404`, or redirect to category listing with error indication |

### Alternatives
1. HTTP `404` with a well-formed error page.
2. `302` to `/catalog/<name>/<category>` carrying an error indication.

### Choice
(1). Both are sanctioned, so this is a free choice; `404` is named first, is
the honest status for a URL that names nothing, and needs no place to stash an
error indication across a redirect. This supersedes [T47](#t47), which chose a
plain `200` listing under the older, more permissive wording.

### Risk: 3
Author's most likely different reading: the redirect form, which a fixture
written as `assert status == 404` would reject -- but the spec offers both, so
such a fixture would contradict its own table.

---

## T56 — Which saved media file is used when several contain the id

### Spec Text
> | Downloaded media discovery | A downloaded media file counts as matching the entry when a saved filename in `<vault>/media/` contains the entry `id`; the detail page uses that exact filename in the media static endpoint URL |

### Alternatives
1. Whatever `os.listdir` returns first -- filesystem order.
2. A finished file first, then alphabetical order among equals.
3. Plain alphabetical order, `.part` artifacts included.

### Choice
(2). The determinism table demands the reference be stable for the same vault
and entry, which rules out (1) outright. Preferring a finished file over a
`.part` artifact matters only for a vault caught mid-download, and serving the
complete file there is plainly the better answer; alphabetical order settles
everything else. The normal case -- exactly one media file per entry -- is
identical under all three readings.

### Risk: 10
Author's most likely different reading: plain sorted order with no `.part`
preference, which differs only when a finished file and a partial one both
contain the id.

---

## T57 — "appropriate" MIME types for the static endpoints

### Spec Text
> | `GET` | `/vault/<name>/media/<file>` | Serve `<vault>/media/<file>` with an appropriate media MIME type |
> | `GET` | `/vault/<name>/preview/<id>` | Serve the matching preview image from `<vault>/previews/` whose saved filename contains `<id>`, with an appropriate image MIME type |

### Alternatives
1. Derive the type from the file extension, reusing the `Content-Type` table
   the download phase already pins, and fall back to
   `application/octet-stream` for anything unrecognised.
2. As (1), but the preview route falls back to an image type, since the row
   promises an image.
3. One fixed type per route (`video/mp4` and `image/jpeg`).

### Choice
(2). The download phase names every saved file `<id>.<ext>` from the response
`Content-Type`, so the extension is a faithful record of what was fetched and
inverting that same table keeps the two directions consistent. A fixed type
(3) would mislabel a `.webm` or a `.png`. The preview route's image fallback
honours its "appropriate image MIME type" wording for the rare extension
nothing recognises; the media route has no equivalent promise, so it falls
back to `application/octet-stream`.

### Risk: 15
Author's most likely different reading: a bare `mimetypes.guess_type` with an
`application/octet-stream` fallback on both routes, which differs only for a
preview file with an unrecognised extension.

---

## T58 — A traversal sequence in the vault-name segment of a `/vault/` route

### Spec Text
> | Non-existent vault on detail or static route | Redirect to landing page with vault-not-found indication |

and

> | Path traversal attempt | HTTP `403` or HTTP `404` |

### Alternatives
1. Treat `/vault/..%2F..%2Fetc/media/x` as a vault that does not exist and
   redirect to `/`.
2. Treat it as a traversal attempt and answer `403`.

### Choice
(2) for the static routes. Both rows could claim the case, but a name that is
a traversal sequence is an attack shape rather than a typo, and answering it
with a redirect that then advertises the attempted path on the landing page is
worse than refusing it. The `/catalog/` routes keep reading (1), because their
own error table only ever offers the redirect there. An ordinary non-existent
name such as `/vault/ghost/media/x.mp4` still redirects on both route families.

### Risk: 25
Author's most likely different reading: one uniform vault-not-found redirect
for every unresolvable name, traversal shapes included.

---

## T59 — Extra path segments under `/vault/<name>/media/`

### Spec Text
> | `GET` | `/vault/<name>/media/<file>` | Serve `<vault>/media/<file>` ... |

### Alternatives
1. `<file>` is exactly one segment; anything deeper is `404`/`403`.
2. Deeper segments are joined into a relative path under `media/`.

### Choice
(2), bounded by the containment check. The download phase only ever writes
flat filenames into `media/`, so the two readings agree on every file the tool
itself produces; joining is simply more forgiving for a hand-placed
subdirectory, and the traversal guard still refuses anything that resolves
outside `media/`. `/vault/<name>/preview/<id>` stays single-segment, because
`<id>` is matched against filenames rather than used as a path.

### Risk: 5
Author's most likely different reading: a strict single segment, which differs
only for a request naming a subdirectory that does not normally exist.

---

## T60 — Whether the detail page shows the preview image

### Spec Text
> | Media playback reference | Use media static endpoint when downloaded media file exists |

and

> | `GET` | `/vault/<name>/preview/<id>` | Serve the matching preview image ... |

### Alternatives
1. Render an `<img>` pointing at `/vault/<name>/preview/<id>` when a matching
   preview file exists.
2. Leave the preview endpoint unreferenced by any page.

### Choice
(1). The page-content table names the media reference explicitly but says
nothing either way about previews, and the endpoint would otherwise exist with
nothing linking to it. Guarding on an actual file in `<vault>/previews/` keeps
the page free of broken images, and the reference sits under `/preview/`, so
it can never be mistaken for the media reference the spec does constrain.

### Risk: 8
Author's most likely different reading: no preview on the detail page at all,
which differs only for a fixture that enumerates every `/vault/` URL a page
references.

---

## T61 — What "media playback reference" is made of

### Spec Text
> | Media playback reference | Use media static endpoint when downloaded media file exists |
> | Downloaded media reference | When rendered, the detail page uses the matched saved filename in `/vault/<name>/media/<file>` |

### Alternatives
1. A `<video controls>` element whose `src` is the media URL.
2. A plain `<a href>` to the media URL.
3. Both: a player element with the link as its fallback content.

### Choice
(3). "Playback" asks for a player, but a vault can also hold audio, and a
browser that cannot play the container should still offer the file; `<video>`
fallback content is exactly the place for that link, so one element satisfies
both without duplicating the URL in the page's visible output. Every reading
puts the same `/vault/<name>/media/<file>` URL on the page, which is what the
determinism row constrains.

### Risk: 10
Author's most likely different reading: a bare `<a href>`, which differs only
for a fixture that inspects the tag rather than the URL.

---

## T62 — Whether the detail page still lists the rest of the category

### Spec Text
> | `GET` | `/catalog/<name>/<category>/<id>` | Entry detail page for matching entry |
> | Back navigation | Link to current vault/category listing |

### Alternatives
1. A page about one entry, with a link back to the listing.
2. The category listing with a detail panel for the selected entry bolted on.

### Choice
(1). A "detail page for matching entry" with a separate row for "back
navigation" only makes sense if the listing is somewhere else -- there would be
nothing to navigate back to if the listing were already on the page. The older
spec's explicit licence to reuse the listing has been dropped, which reads as a
deliberate change rather than an omission.

### Risk: 15
Author's most likely different reading: a detail page that keeps the listing
alongside it, so a fixture asserting a sibling entry's title is present would
fail here.

---

## T63 — A trailing slash on the v2/v3 `source`

### Spec Text
> | v2 | `<source>/entry/<id>` |
> | v3 | `<source>/entry/<id>` |

### Alternatives
1. Literal concatenation, so a `source` of `https://host/chan/` yields
   `https://host/chan//entry/e1`.
2. Strip trailing slashes from `source` first.

### Choice
(2), matching `asset_url`, which already builds `<source>/media/<id>` that way
for the download phase. One vault should not produce a doubled slash on its
entry links and a clean one on its asset URLs, and no fixture in the spec ever
writes a `source` with a trailing slash, so the readings agree everywhere the
spec's own examples reach.

### Risk: 8
Author's most likely different reading: literal concatenation, visible only for
a vault whose `source` ends in `/`.

---

## T64 — Where the annotation `id` comes from

### Spec Text
> | `POST` | Create annotation | JSON with `title`, `timecode`, optional `body` | Redirect to entry detail page with `?timecode=<seconds>` |

and

> | `id` | string | Unique within entry |

### Alternatives
1. The server mints the `id`; the create body has no say in it.
2. The client may supply an `id` on create and the server honours it (falling
   back to a generated one when it is absent).
3. The id is a positional counter (`"1"`, `"2"`, ...) derived from the list
   length.

### Choice
(1): a server-generated opaque id (12 hex characters), re-rolled if it ever
collided with an id already on the entry. The `POST` field table lists exactly
three fields and `id` is not among them, so a create request has no documented
way to name one; the storage table's "Unique within entry" is then the
server's obligation. A counter (3) would repeat ids after a delete, breaking
that guarantee.

### Risk: 12
Author's most likely different reading: a positional/counter id such as `"1"`,
which any test that hard-codes an expected id would depend on.

---

## T65 — Whether an empty `title` counts as "missing"

### Spec Text
> | `title` | string | yes | none |

and

> | Missing `title` on create | HTTP `400` with message naming missing field |

### Alternatives
1. "Missing" means the JSON key is absent (or `null`); `{"title": ""}` is a
   present value and is stored as the empty string.
2. "Missing" means falsy; `{"title": ""}` is rejected with the same `400`.

### Choice
(1). The field table's Required column is about presence, and the Default
column says `none` — that is, there is nothing to fall back to when the key is
absent. An empty string is a value the user typed, and the storage table says
`title` is "Stored as provided", with no trimming or emptiness rule anywhere.

### Risk: 25
Author's most likely different reading: a truthiness check (`if not
data.get("title")`), which returns `400` for an empty title.

---

## T66 — `PATCH` carrying only `id`

### Spec Text
> | `PATCH` | Update annotation | JSON with `id` and at least one of `title` or `body` | Redirect to entry detail page |

and

> | omitted fields | n/a | allowed | Leave stored value unchanged |

### Alternatives
1. `{"id": "..."}` alone violates the documented request body → `400`.
2. It is a legal no-op: every field is omitted, so every stored value is left
   unchanged, and the response is the usual redirect.

### Choice
(1). The Request Body column states a requirement ("`id` **and at least one
of** `title` or `body`"), and the "omitted fields" row is about which of the
two optional fields may be left out of an otherwise valid update, not about
dropping both. Returning `400` also makes the failure visible instead of
silently confirming an update that changed nothing.

### Risk: 35
Author's most likely different reading: a permissive update that applies
whichever of the two fields is present and redirects even when neither is.

---

## T67 — A non-string `timecode` on create

### Spec Text
> | `timecode` | string | yes | none |

and

> | Component type | Non-negative integer |

### Alternatives
1. Only strings are accepted; `{"timecode": 90}` is an invalid format → `400`.
2. A JSON integer is accepted as whole seconds (it denotes exactly what
   `"90"` denotes); every other non-string type is rejected.

### Choice
(2). The stored form is an integer count of seconds, and a JSON integer is
that value with no parsing required, so refusing it would reject the least
ambiguous spelling of an accepted value. Floats, booleans, lists and objects
have no reading under the grammar and are refused.

### Risk: 20
Author's most likely different reading: a strict `isinstance(value, str)`
check that answers `400` for `{"timecode": 90}`.

---

## T68 — What exactly fails the `timecode` pattern

### Spec Text
> | Invalid pattern | Return error |

> | Leading zeros | Allowed |

### Alternatives
1. Anchored `^\d+(:\d+){0,2}$`: no sign, no whitespace, no decimal point, no
   empty component, at most three components.
2. A looser reading that tolerates surrounding whitespace (`" 90"`), a `+`
   sign, or four components by folding the extra one in as days.

### Choice
(1). The grammar table lists exactly three formats, and "Component type:
non-negative integer" rules out signs and fractions. Nothing in the spec
mentions trimming, so whitespace is not part of any documented format;
`"1:2:3:4"` matches no listed format either.

### Risk: 8
Author's most likely different reading: stripping surrounding whitespace
before matching, so `" 90"` parses as 90.

---

## T69 — Redirect status and shape for an annotation mutation

### Spec Text
> | `POST` | Create annotation | ... | Redirect to entry detail page with `?timecode=<seconds>` |

### Alternatives
1. `302`, the status the rest of this viewer already redirects with, to the
   absolute path `/catalog/<name>/<category>/<id>?timecode=<seconds>`.
2. `303 See Other`, the status HTTP prescribes for "the result of this
   non-GET request is at another URI".

### Choice
(1). The viewer's own rule is "Redirect status | HTTP `302` or `303`", and
every existing redirect in the implementation is a `302`; a mutation redirect
is not singled out. Tests that accept either status are unaffected, and a
client that follows redirects reaches the same page under both.

### Risk: 5
Author's most likely different reading: `303` for the mutating methods.

---

## T70 — Whether `PATCH`/`DELETE` redirects also carry `?timecode=`

### Spec Text
> | `PATCH` | Update annotation | ... | Redirect to entry detail page |
> | `DELETE` | Delete annotation | ... | Redirect to entry detail page |

### Alternatives
1. Only the create redirect carries a query parameter; update and delete
   redirect to the bare detail page.
2. Update also carries the annotation's timecode, so the page it lands on
   seeks to the annotation that was just edited.

### Choice
(1). The table gives `POST` a longer Success Result *specifically* to name the
query parameter and gives the other two methods the plain detail page. A
`DELETE` has no timecode left to point at, and the asymmetry only makes sense
as a deliberate distinction.

### Risk: 7
Author's most likely different reading: appending the edited annotation's
timecode to the `PATCH` redirect as well.

---

## T71 — What a failed legacy mutation leaves on disk

### Spec Text
> | v1 | Migrate entire catalog to v3 first, then apply annotation, then persist |

and

> | Non-existent annotation `id` on update | HTTP `404` |

### Alternatives
1. Migration is persisted as part of the annotation write only, so a request
   that ends in `400`/`404` writes nothing at all and a pristine v1 vault is
   still v1 afterwards.
2. Migration is persisted as soon as it happens, so a `PATCH` with an unknown
   id against a v1 vault leaves a migrated (v3) catalog and no annotation.

### Choice
(1). The sequence in the table is "migrate, then apply annotation, then
persist": persistence is the last step and covers both changes at once, which
is also what "Single write for migration + annotation" describes. A request
the server rejects therefore never reaches the write.

### Risk: 15
Author's most likely different reading: migrating and saving up front, then
failing the annotation, which leaves a v3 catalog behind after a `404`.

---

## T72 — Mutations aimed at a vault or category the route cannot serve

### Spec Text
> | Migration failure during auto-migration | HTTP `500` with error message; original catalog unchanged |

and (from the viewer's error table)

> | Non-existent vault on any `/catalog/<name>` route | Redirect to `/` |

### Alternatives
1. Annotation methods reuse the viewer's existing rules: an unreadable or
   missing vault redirects to `/`, and a category that the vault's version
   does not have redirects to that version's default category.
2. Annotation methods are an API surface and answer `404`/`400` in both cases.

### Choice
(1). The annotation tables add rules for annotation-specific failures and say
nothing about vault or category resolution, so the `/catalog/...` route rules
that already govern those two segments keep applying. The viewer's error table
also permits a redirect *or* a `4xx` for an invalid category, so this choice
stays inside the documented set either way.

### Risk: 15
Author's most likely different reading: `404` for a missing vault on a
mutating method.

---

## T73 — Unknown fields in an annotation request body

### Spec Text
> | `PATCH` | Update annotation | JSON with `id` and at least one of `title` or `body` |

### Alternatives
1. Fields outside the documented set are ignored (a `timecode` on `PATCH`, an
   `id` on `POST`).
2. They make the body invalid → `400`.

### Choice
(1). Each method's field table documents what is read; nothing says a body is
rejected for carrying more. Ignoring `timecode` on `PATCH` also matches the
table's own silence about updating it — the stored timecode is left as it is.

### Risk: 15
Author's most likely different reading: honouring a client-supplied `id` on
create, which would make `POST` able to set (or collide) ids.

---

## T74 — The media element and the `?timecode=` query

### Spec Text
> | Entry detail page effect | Seek playback to `timecode` query value |

### Alternatives
1. Append a media fragment to the media URL (`...e1.mp4#t=90`) and state the
   position as an attribute, so a browser starts there with no scripting.
2. Keep the media URL byte-identical and carry the position only in a data
   attribute plus a script that sets `currentTime`.

### Choice
(1), plus the data attribute and a rendered "Playback starts at ..." line.
`#t=` is the standard way to express a start position in a URL, it is what a
plain `<video src>` honours, and the page only gains the fragment when the
query is actually present, so a request without `?timecode=` renders exactly
the same markup as before.

### Risk: 20
Author's most likely different reading: leaving the `src` untouched and
seeking from a script, so a test comparing the media URL exactly on a
`?timecode=` request sees the plain path.

---

## T75 — The body of an annotation error response

### Spec Text
> | Missing `title` on create | HTTP `400` with message naming missing field |
> | Any error response | Well-formed HTTP response; no raw traceback or stack trace |

### Alternatives
1. The viewer's existing HTML error page, with the message in its text.
2. A JSON error document, matching the JSON request bodies.

### Choice
(1). These requests are issued by the entry detail page of an HTML viewer and
succeed with a redirect to an HTML page, not with a JSON result; the spec asks
for "a message", not for a machine-readable shape. Reusing the viewer's error
page keeps every failure -- annotation or not -- looking the same and keeps
the "well-formed HTTP response" guarantee in one place. The field name appears
verbatim in the text either way.

### Risk: 15
Author's most likely different reading: a JSON body such as
`{"error": "missing required field: title"}`.

---

## T76 — Whether a `Content-Type` header gates the JSON body

### Spec Text
> | `POST` | Create annotation | JSON with `title`, `timecode`, optional `body` |

### Alternatives
1. The body is parsed as JSON whatever the request headers say; a body that
   does not parse is the documented "Malformed JSON body" `400`.
2. A request without `Content-Type: application/json` is refused (`400`, or
   `415`).

### Choice
(1). The error table's only body-related row is "Malformed JSON body | HTTP
`400`", and `415` appears nowhere in the spec. A form-encoded body still ends
in `400`, because it is not parseable JSON — the documented outcome.

### Risk: 3
Author's most likely different reading: requiring the JSON content type and
answering `415`.

---

## T77 — How stored annotations are rendered

### Spec Text
> | Read-after-write behavior | Later `GET` to same entry detail page reflects create, update, or delete result by visibly rendering stored annotations |

### Alternatives
1. An ordered list on the detail page showing each annotation's timecode
   (as clock text and as seconds), title and body, each linking to the same
   page with its own `?timecode=`.
2. Only titles, or only an embedded JSON payload alongside the chart data.

### Choice
(1). "Visibly rendering" rules out a script-only payload, and the stored shape
has four fields worth showing; rendering the timecode both ways keeps the page
readable without hiding the integer the spec stores. The per-annotation link
is what makes "Seek playback to `timecode` query value" reachable from the UI.

### Risk: 10
Author's most likely different reading: a plainer list (title and body only),
which a test asserting on the rendered timecode text would notice.

---

## T78 — An unusable `?timecode=` on a `GET`

### Spec Text
> | Entry detail page effect | Seek playback to `timecode` query value |

### Alternatives
1. A value that is not a timecode is ignored: the page renders normally with
   no seek.
2. It is the same "Invalid `timecode` format" `400` as on create.

### Choice
(1). The error table's timecode row is about the *create* field; a detail page
is a read-only view that must keep rendering. Ignoring a junk query parameter
also keeps hand-edited or stale links working instead of turning them into
error pages.

### Risk: 10
Author's most likely different reading: `400` for `?timecode=abc`.
