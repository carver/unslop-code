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
