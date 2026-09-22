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
