# AMBIGUITIES

Numbered record of spec under-specification, the interpretation chosen for this
implementation, and the risk that the spec author's own implementation (and the
hidden tests written against it) reads the spec differently.

---

## T1. Location of `catalog.bak`

### Spec Text
> | Backup path | `catalog.bak` |

(under `catalog.json` Persistence; the catalog itself is specified as
`<name>/catalog.json`.)

### Alternatives
1. `<name>/catalog.bak` — sibling of the catalog, inside the vault directory.
2. `./catalog.bak` — relative to the process working directory.

### Choice
`<name>/catalog.bak`. Every other path in the spec (`<name>/`,
`<name>/catalog.json`) is vault-relative, and a backup that lives outside the
vault would be clobbered by syncing a second vault from the same directory.

### Risk: 3
Author most likely prefers: the same vault-relative `<name>/catalog.bak`.

---

## T2. Normalization of the stored `published` value

### Spec Text
> | Static | `published` | string | Original publication datetime |

> | `published` | string | ISO 8601 datetime or date-only text |

> | Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix |
> | Date-only source values | Normalize to `00:00:00` time component |

### Alternatives
1. Store the source text verbatim ("Original publication datetime") and only
   normalize internally for ordering.
2. Normalize on store: date-only `2024-05-01` becomes `2024-05-01T00:00:00`,
   and any timezone suffix/offset is dropped so the stored text always matches
   `YYYY-MM-DDTHH:MM:SS`.
3. Normalize, converting offsets to UTC wall time before dropping the suffix.

### Choice
Alternative 2. The Determinism table states datetime text has no timezone
suffix and that date-only values are normalized to a `00:00:00` time
component — that rule has no other stored field it could apply to (history keys
are generated locally and never date-only). Offsets are dropped rather than
converted, since the spec never mentions timezone conversion and converting
would silently change the calendar date.

### Risk: 30
Author most likely prefers: same normalization for date-only input, but may
keep a `Z`/offset-bearing datetime verbatim rather than stripping the suffix.

---

## T3. Scope of the sync timestamp collision advance

### Spec Text
> | Collision handling | When a new history entry would reuse an existing or non-newer second, advance to a strictly later second before writing |

> | Sync timestamps | Reflect sync execution time and remain strictly increasing whenever new history entries are appended |

### Alternatives
1. Per-history-object: each tracked field advances independently past its own
   latest key, so one sync can write several different timestamps.
2. Per-sync (global): compute one timestamp for the whole sync run, advanced
   past the newest key anywhere in the catalog, and use it for every append in
   that run.

### Choice
Alternative 2. "Sync timestamps ... remain strictly increasing" reads as a
property of the sync run rather than of individual fields, and a single
timestamp per run keeps one sync's appends mutually consistent (a brand-new
entry added during a colliding sync does not land earlier than the changes
recorded beside it).

### Risk: 30
Author most likely prefers: the per-field `while ts in history: ts += 1s` loop,
which agrees with the global choice except when a sync both collides and adds a
first-observation entry.

---

## T4. What makes a vault "invalid" for `sync`

### Spec Text
> | Missing or invalid vault | Error to stderr including `<name>`; exit non-zero |

> | `version` | integer | `3` |

### Alternatives
1. Only unreadable/unparseable `catalog.json` counts as invalid.
2. Also require the root schema: object with `version`, `source`, `episodes`,
   `streams`, `clips` of the stated types.
3. As 2, and additionally require `version == 3` exactly.

### Choice
Alternative 3. The root schema table gives `3` as a *required value*, not a
default, so a catalog claiming another version is not a valid vault for this
tool.

### Risk: 25
Author most likely prefers: the same structural validation, but may accept any
integer `version` and simply rewrite it as `3`.

---

## T5. Source response missing a category array

### Spec Text
> | Source response shape | JSON object with `episodes`, `streams`, and `clips` arrays |

> If any source entry is missing a required field or has the wrong type, `sync`
> must fail as a source metadata fetch failure and leave the vault unchanged.

### Alternatives
1. Strict: a response lacking any of the three arrays (or having a non-array
   there) is a source metadata fetch failure.
2. Tolerant: a missing key is treated as an empty array, so every catalog entry
   in that category is marked `removed: true`.

### Choice
Alternative 1. The spec fixes the response shape, and the entry-level rule
shows the author's disposition is to fail loudly on malformed source data
rather than silently reinterpret it. Tolerant handling would also destroy
history (mass removals) on a truncated response.

### Risk: 35
Author most likely prefers: strict failure, but a `.get(cat, [])` style
implementation would silently mark the category removed.

---

## T6. Does a no-op `sync` rewrite (and therefore back up) the catalog?

### Spec Text
> | Backup trigger | Before every write to existing `catalog.json` |

> | Success effect | Update catalog with new, changed, removed, and restored entries |

### Alternatives
1. Always write the catalog on a successful sync, so `catalog.bak` appears even
   when nothing changed.
2. Write only when something actually changed; a no-op sync leaves the vault
   untouched and creates no backup.

### Choice
Alternative 1. The backup rule is phrased around "every write", not "every
change", and unconditional write is both simpler and keeps catalog ordering
canonical. A test asserting `catalog.bak` exists after any successful sync
passes; a test asserting the catalog file mtime/content is *identical* after a
no-op sync also passes, since the serialized content is unchanged.

### Risk: 20
Author most likely prefers: unconditional write; a dirty-flag implementation
would leave no `catalog.bak` after a first no-op sync.

---

## T7. Category membership and cross-category ids

### Spec Text
> | First observation | Add entry to matching category; ... |
> | Entry absent from current source | Append `removed: true` at sync timestamp |

### Alternatives
1. Ids are scoped per category: a catalog entry in `episodes` is "present" only
   if its id appears in the source's `episodes` array.
2. Ids are global: an entry is present if the id appears anywhere in the
   source, and entries migrate between categories.

### Choice
Alternative 1. "Add entry to matching category" ties an entry to the category
it arrived in, and nothing in the spec describes moving an entry between
categories or de-duplicating ids across them.

### Risk: 12
Author most likely prefers: the same per-category scoping.

---

## T8. Integer typing of source fields

### Spec Text
> | `width` | integer | Pixel width |
> | `views` | integer | Current view count |
> | `likes` | integer or `null` | Current like count |

### Alternatives
1. Accept any Python `int`, including `True`/`False` (JSON `true`/`false`),
   which are `int` subclasses.
2. Reject booleans and floats (including integral floats like `10.0`) as wrong
   type.

### Choice
Alternative 2. JSON distinguishes booleans and numbers from integers; `true`
where an integer is required is exactly the "wrong type" case the spec asks to
reject.

### Risk: 20
Author most likely prefers: rejecting booleans, but a naive
`isinstance(v, int)` check would accept `true`, and a `float` view count is an
untested corner either way.

---

## T9. `annotations`

### Spec Text
> | Local-only fields | Source data does not include `removed` or `annotations` |

### Alternatives
1. Create an `annotations` structure on every entry even though no command in
   this spec reads or writes it.
2. Never create it; preserve it untouched if a pre-existing catalog has one.

### Choice
Alternative 2. The `entry` Stored Fields table is exhaustive and lists no
`annotations` field, and no subcommand in this spec produces annotations, so
inventing one would contradict the stored-field contract.

### Risk: 15
Author most likely prefers: not emitting the field; a possible variant is an
empty `annotations` object/array on each entry.

---

## T10. HTTP failure surface

### Spec Text
> | Source request | HTTP `GET` to vault `source` URL |
> | Source metadata fetch failure | stderr | non-zero | Error message; malformed source entries are included in this case |

### Alternatives
1. Only transport errors count; any body that parses as JSON is accepted.
2. Non-2xx status, unreachable host, non-JSON body, non-object JSON, and
   malformed entries all map to the one fetch-failure outcome.

### Choice
Alternative 2. The spec explicitly folds malformed *entries* into the fetch
failure bucket, which signals a single catch-all failure mode for "could not
obtain usable source metadata"; the vault is left unchanged in all of them.

### Risk: 5
Author most likely prefers: the same catch-all.

---

## T11. Unparseable `published` text and ordering

### Spec Text
> | `1` | Newest `published` first |
> | `2` | Lexicographically smaller `id` first when `published` values are equal |

### Alternatives
1. Reject entries whose `published` is a string but not ISO-parseable.
2. Accept them (the schema only requires type `string`), store the text as
   given, and order by its text value.

### Choice
Alternative 2. The source schema constrains `published` to type `string`; the
"ISO 8601 datetime or date-only text" note describes the expected content, and
the malformed-entry rule is written in terms of missing fields and wrong
*types*. Normalized ISO text sorts correctly lexicographically, so string
ordering agrees with chronological ordering for all well-formed input.

### Risk: 18
Author most likely prefers: same permissive handling; a stricter author would
raise a fetch failure on garbage `published` text.
