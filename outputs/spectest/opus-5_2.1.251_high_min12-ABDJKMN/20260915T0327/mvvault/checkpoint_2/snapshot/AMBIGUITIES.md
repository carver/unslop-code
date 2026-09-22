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

> **Update (multi-version spec):** resolved. Versions `1` and `2` are now
> supported input and are migrated rather than rejected; only a missing,
> non-integer, or out-of-range `version` is an error (see T16). The structural
> validation of a version `3` root object is unchanged.

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

> **Update (multi-version spec):** partially resolved. The Supported Versions
> table names `annotations` as part of the native v3 shape, and both migration
> tables require `annotations: []` on every migrated entry, so the field is
> real and is an empty **array**. What remains open — whether `sync` creates it
> on natively-observed entries — is tracked as T12, where the choice made here
> is now reversed.

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

---

## T12. `annotations` on entries created natively by `sync`

### Spec Text
> | `3` | Native format | Category arrays; full `source`; ISO 8601 history keys; `removed`; `annotations` |

> | `annotations` | Add `[]` to every entry |

> | Post-migration usability | All subsequent commands operate as for a vault created in v3 |

### Alternatives
1. `annotations` exists only on entries that went through migration; `sync`
   keeps creating first-observation entries without the field.
2. `annotations: []` is part of the v3 entry shape, so `sync` creates it on
   every new entry too, and a migrated vault and a natively-created vault have
   the same entry shape.

### Choice
Alternative 2. The Supported Versions table describes `annotations` as a
property of the *version 3 format*, not of the migration, and it is listed
beside `removed`, which `sync` unquestionably creates. "Operate as for a vault
created in v3" only makes sense if a v3-created vault looks like a migrated
one. This reverses T9 for the same reason.

### Risk: 35
Author most likely prefers: the same always-present `annotations: []`; a
migration-only implementation would leave sync-created entries without it.

---

## T13. Entry order produced by `migrate`

### Spec Text
> | Entries | Move every object from `entries` to `episodes` |

> | Categories | Preserve `episodes`, `streams`, and `clips` placement |

(and, from the earlier spec, `catalog.json` Ordering: "Newest `published`
first; ties break by lexicographically smaller `id`".)

### Alternatives
1. `migrate` is a pure shape conversion: entries keep the order they had in the
   legacy file.
2. `migrate` also re-applies the catalog ordering rule, so the written v3 file
   is sorted newest-`published` first.

### Choice
Alternative 1. "Move every object" and "preserve placement" describe a
transport, not a re-ordering, and the Migration Determinism table — which
enumerates every other normalization migration performs — says nothing about
order. A subsequent `sync` re-sorts the catalog anyway, so the invariant is
restored the first time the vault is written by `sync`.

### Risk: 28
Author most likely prefers: order preservation; an author who funnels migration
output through their existing save/sort path would emit sorted entries.

---

## T14. How strict is "malformed v1 or v2 entry data"?

### Spec Text
> | Malformed v1 or v2 entry data | Error to stderr; exit non-zero; leave `catalog.json` unchanged |

(with the Version 1 / Version 2 Entry Schema tables giving a type for each of
the nine fields.)

### Alternatives
1. Only structurally impossible data fails: a non-object entry, or a v1 history
   key that cannot be read as epoch seconds.
2. Full schema validation: every entry must be an object with a string `id`,
   string `published`, integer `width`/`height`, and all five history objects
   present with correctly typed keys and values (string / integer /
   integer-or-null).
3. Lenient: missing history fields default to `{}`, wrong value types pass
   through untouched.

### Choice
Alternative 2. The spec spends two full tables giving types for legacy entry
fields; the only thing those tables can be *for* is deciding what counts as
malformed, since nothing else in the spec reads them. It also mirrors the
existing source-entry validation, which rejects missing fields and wrong types
alike.

### Risk: 40
Author most likely prefers: failing on unconvertible history keys and
non-object entries, but tolerating a legacy entry that simply omits one history
field (a `.get(field, {})` style converter) — the case where strict validation
errors and lenient conversion succeeds.

---

## T15. A version 2 catalog missing one of the three category arrays

### Spec Text
> | `episodes` | array | Episode entries |
> | `streams` | array | Stream entries |
> | `clips` | array | Clip entries |

> | Missing categories | Create empty `streams` and `clips` arrays |

(the second row appears only under *Version 1 to Version 3 Migration*.)

### Alternatives
1. Strict: a v2 catalog lacking `clips` violates its declared schema and is an
   error.
2. Lenient: an absent category is treated as empty, exactly as for v1; a
   present-but-non-array category is still an error.

### Choice
Alternative 2. The migration rules describe what a v3 catalog must end up with
rather than what the input must contain, and "create empty ... arrays" shows
the author's disposition toward filling in absent categories rather than
rejecting them. It also makes a hand-written v2 fixture that only lists
`episodes` work.

### Risk: 22
Author most likely prefers: the same fill-in behaviour; a strict validator
would reject the partial v2 catalog instead.

---

## T16. Versions below `1`

### Spec Text
> | `version` greater than `3` | Version-related error to stderr; exit non-zero; no migration; no modification |

### Alternatives
1. Only `> 3` is rejected; `0` and negative integers fall through to some other
   handling (or are read as v1).
2. The supported set is exactly `{1, 2, 3}`; any other integer is a
   version-related error.

### Choice
Alternative 2. The Supported Versions table is an enumeration, not a lower
bound, and there is no schema at all for version `0`. The error text mentions
`version`, so a test that only checks for a version-related message passes
either way.

### Risk: 15
Author most likely prefers: the same closed set; an implementation written as
`if version > 3: error` with `elif version == 1 / == 2 / else native` would
instead treat `0` as a v3 catalog and fail on its shape (still non-zero, but
without a version-related message).

---

## T17. Choosing the migration timestamp

### Spec Text
> | Migration-added timestamp scope | Each migration-added `removed` timestamp must be ISO 8601; cross-entry equality is not required |

> | `removed` | Add `{<migration-timestamp>: false}` to every entry |

### Alternatives
1. One `datetime.now()` captured per migration run and shared by every entry.
2. A fresh `datetime.now()` per entry, so entries may differ by a second.
3. A timestamp derived from the entry's own newest history key.

### Choice
Alternative 1. "Cross-entry equality is not required" permits, but does not
forbid, a single shared stamp, and one stamp per run keeps the migration
reproducible within a run. Derivation from existing history (3) is excluded
because the timestamp is described as a *migration* timestamp.

### Risk: 8
Author most likely prefers: either 1 or 2; the spec explicitly declines to
distinguish them, so only a test asserting entries *differ* would separate
them, and such a test would be non-deterministic.

---

## T18. Does `migrate` on a v3 vault rewrite `catalog.json`?

### Spec Text
> | Effect on v3 | No-op; no backup written |

> | v3 reload | No additional history entry, no semantic modification, no backup write |

### Alternatives
1. Re-serialize the catalog (harmless, byte-identical for a canonical file) but
   skip the backup.
2. Write nothing at all and exit `0`.

### Choice
Alternative 2. "No-op" is unqualified, and the only way to guarantee "no backup
write" under the standard backup rule ("before every write to existing
`catalog.json`") is not to write. Exit status is `0` because a v3 vault is
valid input, not an error.

### Risk: 10
Author most likely prefers: the same no-write no-op; a re-serializing variant
would differ only for a catalog whose on-disk formatting is not canonical.

---

## T19. `published` text during migration

### Spec Text
> | `published` | string | ISO 8601 datetime |

> | History keys | Convert every UNIX-epoch string key to ISO 8601 format |

### Alternatives
1. Migration rewrites `published` through the same normalization `sync` applies
   to source data (date-only gains `00:00:00`, timezone suffix dropped).
2. Migration copies `published` verbatim; only history *keys* are converted.

### Choice
Alternative 2. The migration tables list exactly which fields change, and
`published` is not among them — "Convert every UNIX-epoch string key" is scoped
to history keys. Legacy `published` values are already declared to be ISO 8601
datetimes, so the two readings agree on well-formed input.

### Risk: 12
Author most likely prefers: verbatim copy; a normalizing implementation differs
only on a legacy catalog holding date-only or offset-bearing `published` text.

---

## T20. What `sync` on a v1/v2 vault leaves behind when the fetch fails

### Spec Text
> | v1 vault | Auto-migrate to v3 in memory, apply sync updates, write v3 catalog to disk |

> | Backup before write | Standard backup rules apply; backup contains the **original** pre-migration catalog |

### Alternatives
1. Migration is persisted as its own step as soon as the legacy catalog is
   loaded, so a later fetch failure still leaves a v3 catalog (and a backup)
   behind — but then the backup written by the sync itself holds the migrated
   v3 file, not the original.
2. A legacy `sync` performs exactly one write, at the end: the backup captures
   the original legacy catalog and a failed sync leaves the vault untouched at
   its original version.

### Choice
Alternative 2. It is the only reading under which "backup contains the original
pre-migration catalog" holds, and it preserves the earlier spec's rule that a
failed sync leaves the vault unchanged. "Auto-migrate ... **in memory**" says
the migration step itself is not a disk operation.

### Risk: 18
Author most likely prefers: the same single write; a two-step implementation
would leave a migrated v3 catalog on disk after a source fetch failure.
