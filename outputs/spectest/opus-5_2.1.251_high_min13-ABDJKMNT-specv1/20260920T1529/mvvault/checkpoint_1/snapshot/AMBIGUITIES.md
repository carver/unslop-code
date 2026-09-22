# AMBIGUITIES

Interpretation decisions made while implementing `mvault` from the spec.

## T1: Location of `catalog.bak`

### Spec Text
> | Backup path | `catalog.bak` |

### Alternatives
1. The backup lives beside the catalog it copies: `<name>/catalog.bak`.
2. The backup is written to the process working directory: `./catalog.bak`.

### Choice
`<name>/catalog.bak`. The persistence table sits under the `catalog.json`
heading, whose path is given elsewhere as `<name>/catalog.json`; both paths are
written without a directory prefix, so they are naturally read as relative to
the vault directory. A backup outside the vault would also break if two vaults
were synced from the same working directory.

### Risk: 3
Author most likely prefers: the same, `<name>/catalog.bak`.

## T2: Whether a sync that changes nothing still writes (and therefore backs up)

### Spec Text
> | Backup trigger | Before every write to existing `catalog.json` |

> | Existing entry, unchanged tracked value | No new history entry for that field |

### Alternatives
1. A successful `sync` always rewrites `catalog.json` (so `catalog.bak` is
   refreshed on every successful sync, even a no-op one).
2. `sync` writes only when at least one history entry was appended, so a no-op
   sync leaves `catalog.bak` absent/stale.

### Choice
Always write on a successful sync. The spec conditions the backup on "every
write", and the simplest conforming implementation serialises the catalog at the
end of every successful sync; a test that runs `init`, `sync`, `sync` and then
asserts `catalog.bak` matches the first sync's catalog only passes under this
reading. The "no new history entry" rule constrains history content, not whether
the file is rewritten.

### Risk: 15
Author most likely prefers: the same (unconditional write); a dirty-flag
implementation that skips the second write is the plausible alternative.

## T3: Scope of the "strictly later second" advance

### Spec Text
> | Collision handling | When a new history entry would reuse an existing or non-newer second, advance to a strictly later second before writing |

> | Sync timestamps | Reflect sync execution time and remain strictly increasing whenever new history entries are appended |

### Alternatives
1. Per-sync (global): one timestamp is chosen for the whole sync, advanced past
   the newest timestamp found anywhere in the catalog, and every history entry
   appended by that sync shares it.
2. Per-history-object: each field's new key is advanced only past that field's
   own newest key, so one sync can write different keys to different fields.

### Choice
Per-sync global advance. "Sync timestamps" (singular per run) are described as a
property of the run, and a single shared key per sync is what makes a catalog
readable as a sequence of syncs. Both readings agree in the common case; they
differ only when one field was previously advanced further ahead than another,
and the global reading keeps a sync atomic.

### Risk: 25
Author most likely prefers: per-history-object advance, if they implemented the
collision rule inside the history-append helper rather than at the sync level.

## T4: Re-appending `removed: true` for an entry that is already removed

### Spec Text
> | Entry absent from current source | Append `removed: true` at sync timestamp |

> | Existing entry, unchanged tracked value | No new history entry for that field |

### Alternatives
1. `removed` behaves like every other tracked field: append only when the
   current value actually changes, so a second sync with the entry still absent
   adds nothing.
2. Append `removed: true` on every sync in which the entry is absent, growing
   the history indefinitely.

### Choice
Append only on change. `removed` is listed in the same tracked-field table as
the other five fields and the unchanged-value rule is stated generally, so the
absent-entry row is best read as "make sure the current value is `true`".

### Risk: 12
Author most likely prefers: the same change-only behaviour.

## T5: Whether ids are scoped per category

### Spec Text
> | First observation | Add entry to matching category; create initial history entry for all six tracked fields; set `removed` to `false` at sync timestamp |

### Alternatives
1. Each of `episodes`, `streams`, `clips` is an independent namespace: entries
   are matched by (category, id), and an id appearing in a different category is
   a separate entry.
2. Ids are globally unique across the vault, and an entry that moves between
   categories is relocated rather than duplicated.

### Choice
Per-category matching. "Add entry to matching category" and the per-category
shape of both the catalog and the source response make category the outer
dimension; nothing in the spec describes moving an entry between categories, and
removal detection is only meaningful when compared within a category.

### Risk: 15
Author most likely prefers: the same per-category matching.

## T6: Source datetimes carrying a timezone offset

### Spec Text
> | Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix |

### Alternatives
1. Drop the offset and keep the wall-clock time as written
   (`2024-05-06T07:08:09+02:00` → `2024-05-06T07:08:09`).
2. Convert to UTC first, then drop the suffix
   (`2024-05-06T07:08:09+02:00` → `2024-05-06T05:08:09`).

### Choice
Drop the offset, keep the wall-clock time. The rule is phrased as being about
the *text* ("without timezone suffix"), i.e. a formatting rule, and the sibling
rule for date-only values is likewise a pure text normalisation. No rule
anywhere mentions UTC or timezone conversion.

### Risk: 30
Author most likely prefers: UTC conversion, if their implementation parses with
`datetime.fromisoformat` and calls `astimezone`/`utcoffset` before formatting.

## T7: A `published` string that is not parseable as ISO 8601

### Spec Text
> | `published` | string | ISO 8601 datetime or date-only text |

> If any source entry is missing a required field or has the wrong type, `sync`
> must fail as a source metadata fetch failure and leave the vault unchanged.

### Alternatives
1. Store an unparseable string verbatim; only the declared *type* is validated.
2. Treat an unparseable string as a source metadata fetch failure.

### Choice
Store verbatim. The validation rule is explicitly about missing fields and wrong
types, and a non-ISO string is still a string. Normalisation is applied when the
value parses and is a no-op otherwise, which keeps sync total on well-typed
input.

### Risk: 20
Author most likely prefers: the same type-only validation.

## T8: What makes a vault "invalid"

### Spec Text
> | Missing or invalid vault | Error to stderr including `<name>`; exit non-zero |

> | `version` | integer | `3` |

### Alternatives
1. A vault is invalid if `catalog.json` is missing, unreadable, not a JSON
   object, or does not satisfy the root schema — including `version` not being
   the integer `3`.
2. Only structural damage counts (missing file / bad JSON / missing keys); the
   `version` value is not re-checked on load.

### Choice
Validate the full root schema, `version == 3` included. The root-schema table
states `3` as a *Required Value*, so a catalog carrying another version does not
satisfy the documented contract and is safest treated as invalid rather than
silently migrated.

### Risk: 25
Author most likely prefers: the looser structural check, if their loader only
guards `json.load` and the three category arrays.

## T9: Static fields when a later sync reports different values

### Spec Text
> | Static | `published` | string | Original publication datetime |

### Alternatives
1. Static fields are captured at first observation and never updated.
2. Static fields are overwritten with the latest source values on every sync.

### Choice
Capture once, never update. They are labelled "Static" and `published` is
described as the *original* publication datetime; only the six tracked fields
have an append-on-change rule, so re-writing statics would leave a silent,
unrecorded mutation.

### Risk: 20
Author most likely prefers: the same capture-once behaviour.

## T10: Duplicate ids inside one source category

### Spec Text
> | `id` | string | Unique identifier |

### Alternatives
1. The last occurrence in the array wins.
2. The first occurrence wins.
3. Duplicates are a source metadata fetch failure.

### Choice
Last occurrence wins. The source declares ids unique, so the spec gives no
handling for duplicates; building a dict keyed by id — the obvious
implementation — yields last-wins, and inventing a new failure mode for a case
the error table never lists would be worse.

### Risk: 20
Author most likely prefers: last-wins as an incidental consequence of the same
dict build; this input is unlikely to be tested at all.

## T11: Transport and envelope failures

### Spec Text
> | Source metadata fetch failure | stderr | non-zero | Message includes `Source metadata fetch failure`; malformed source entries are included in this case |

### Alternatives
1. Every failure to obtain a usable payload — connection error, HTTP error
   status, non-JSON body, non-object body, missing/non-array `episodes`,
   `streams` or `clips`, and malformed entries — reports the same message.
2. Only malformed *entries* use this message; transport errors surface as an
   unhandled traceback or a different message.

### Choice
One failure mode for all of them. The row is named "Source metadata fetch
failure" and says malformed entries are *included* in it, implying the category
is broader than entry validation, and the vault is left unchanged in every case.

### Risk: 8
Author most likely prefers: the same single failure mode.

## T12: `catalog.json` serialisation style

### Spec Text
> | Catalog path | `<name>/catalog.json` |

> | JSON object key order | Not part of the contract |

### Alternatives
1. Pretty-printed with a 2-space indent and a trailing newline.
2. Compact single-line JSON.

### Choice
2-space indent with a trailing newline. The spec presents the initial catalog as
pretty-printed JSON, and key order being explicitly outside the contract implies
tests parse the file rather than compare bytes, so either is conforming and
readability wins.

### Risk: 5
Author most likely prefers: some pretty-printed form; byte-level comparison is
ruled out by the key-order rule.

## T13: Booleans supplied where an integer is required

### Spec Text
> | `views` | integer | Current view count |

### Alternatives
1. `True`/`False` are rejected as the wrong type for `width`, `height`, `views`
   and `likes`.
2. They are accepted, since `bool` is a subclass of `int` in Python.

### Choice
Reject. JSON distinguishes `true` from `1`, and the spec's types are JSON types;
accepting a boolean view count would let clearly malformed source data through
the validation the spec requires.

### Risk: 12
Author most likely prefers: acceptance, if they validated with a bare
`isinstance(value, int)` and never considered booleans.

## T14: Exit code and stream for a bare invocation

### Spec Text
> | `python mvault.py` | stderr | non-zero | Usage text |

### Alternatives
1. Print usage to stderr and exit `2` (argparse's convention for a usage error).
2. Exit `1`.

### Choice
Exit `2`, matching argparse. The spec only requires "non-zero", and `2` is what
a standard argparse CLI produces for a missing required subcommand, so it is the
most likely shape of the author's own implementation.

### Risk: 3
Author most likely prefers: any non-zero code; the requirement is satisfied
either way.

## T15: Sort comparison for `published`

### Spec Text
> | `1` | Newest `published` first |
> | `2` | Lexicographically smaller `id` first when `published` values are equal |

### Alternatives
1. Compare the stored, normalised `published` text (which is fixed-width, so
   lexicographic order equals chronological order) and treat equality as string
   equality.
2. Re-parse each `published` into a datetime for comparison, so that values
   differing only in source formatting compare equal.

### Choice
Compare the stored normalised text. Normalisation already collapses date-only
and offset-bearing inputs into one canonical `YYYY-MM-DDTHH:MM:SS` form, so the
two readings agree on every parseable value, and the text comparison also gives
a total order for values that did not parse (see T7).

### Risk: 10
Author most likely prefers: the same, given the determinism section fixes a
single datetime text format.
