# AMBIGUITIES

Interpretation decisions taken while implementing the `mvault` spec.

## T1. Scope of the "strictly later second" rule for sync timestamps

### Spec Text
> Collision handling | When a new history entry would reuse an existing or non-newer second, advance to a strictly later second before writing

> Sync timestamps | Reflect sync execution time and remain strictly increasing whenever new history entries are appended

### Alternatives
1. **Per-history**: each tracked field resolves its own collision against the latest key in *that* history object, so one sync run can write different timestamps for different entries/fields.
2. **Per-sync (global)**: one timestamp is computed for the whole run — wall clock truncated to the second, advanced to `max(all timestamps in the catalog) + 1s` when it is not strictly newer — and every append in that run uses it.

### Choice
Per-sync (global). "Sync timestamps ... remain strictly increasing" speaks about the run's timestamp as a single value, and the ordering contract ("Comparison order: chronological") is only globally meaningful if a later sync never writes a key that is older than an earlier sync's key for a different entry. A global stamp also satisfies the per-history rule as a side effect, so it is conforming under both readings for any catalog where all histories were written by this implementation.

### Risk: 20
Most likely alternative preferred by the author: per-history collision resolution, which would let a stale entry receive the raw wall-clock second while a recently updated entry is bumped forward.

## T2. Timezone suffixes in `published`

### Spec Text
> `published` | string | ISO 8601 datetime or date-only text

> Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix

> Date-only source values | Normalize to `00:00:00` time component

### Alternatives
1. **Drop the offset**: parse, discard `tzinfo`, keep the wall-clock fields as written (`2024-03-01T10:00:00+02:00` → `2024-03-01T10:00:00`).
2. **Convert to UTC** first, then drop the offset (`2024-03-01T10:00:00+02:00` → `2024-03-01T08:00:00`).

### Choice
Drop the offset. The spec calls the rule "without timezone suffix", which describes removing the suffix from the text rather than shifting the instant; it also never names UTC anywhere. Both readings agree for the common `Z` / naive fixtures. Fractional seconds are truncated for the same reason (the required text has second precision).

### Risk: 15
Most likely alternative preferred by the author: normalizing to UTC before formatting, which only differs for sources that use a non-zero offset.

## T3. Source payload missing one of the three category arrays

### Spec Text
> Source response shape | JSON object with `episodes`, `streams`, and `clips` arrays

> Source metadata fetch failure | stderr | non-zero | Error message; malformed source entries are included in this case

### Alternatives
1. **Fail**: a payload lacking any of the three arrays (or where one is not a list) is a source metadata fetch failure and the vault is left unchanged.
2. **Tolerate**: treat a missing array as empty, so every stored entry of that category is marked `removed: true`.

### Choice
Fail. The response shape is stated as a requirement, and the spec already routes every other shape problem ("malformed source entries") into the fetch-failure case; silently interpreting a truncated payload as "everything was deleted" is destructive and irreversible in the history.

### Risk: 35
Most likely alternative preferred by the author: tolerating the missing key as an empty list (a `payload.get(category, [])` style implementation).

## T4. What makes a vault "invalid"

### Spec Text
> `sync` with invalid vault | stderr | non-zero | Message includes vault name

### Alternatives
1. **Catalog readable as the documented schema**: `catalog.json` exists, parses as a JSON object, has `version == 3`, a string `source`, three category arrays, and entries that carry the documented static fields plus six non-empty history objects.
2. **Only parse failures count**: anything that loads as JSON is accepted, and missing pieces surface later as crashes.
3. Something in between (e.g. ignore `version`).

### Choice
Reading 1. `sync` has to read `source`, the categories and existing histories to do any work, so validating exactly those before touching anything is what makes the "leave the vault unchanged" guarantee hold, and it turns every corruption into the required named error instead of a traceback. `version` is checked because the root schema fixes it at `3`.

### Risk: 20
Most likely alternative preferred by the author: the same checks but without the `version` comparison, so a catalog with a different `version` value would still sync.

### Update (multi-version loading spec)
Partly resolved. `version` is still read first, but `1` and `2` are now supported
legacy layouts rather than invalidity: they are converted in memory and validated
against their own schemas (see [T16](#t16-what-counts-as-malformed-v1-or-v2-entry-data)).
A missing, non-integer or greater-than-`3` version is now a distinct version error.

## T5. `published` that is a string but not parseable as ISO 8601

### Spec Text
> If any source entry is missing a required field or has the wrong type, `sync` must fail as a source metadata fetch failure and leave the vault unchanged.

### Alternatives
1. **Fetch failure**: `"published": "last tuesday"` is rejected like a type error.
2. **Pass through**: store the text verbatim and sort by raw string comparison.

### Choice
Fetch failure. Normalization of date-only values means the value must be parsed, and a value that cannot be parsed cannot satisfy the `YYYY-MM-DDTHH:MM:SS` determinism rule, so it is malformed source metadata.

### Risk: 20
Most likely alternative preferred by the author: storing the unparseable text as-is, if their normalizer only special-cases the date-only shape.

## T6. Entry identity across categories

### Spec Text
> First observation | Add entry to matching category ...

> `id` | string | Unique identifier

### Alternatives
1. Identity is `(category, id)`: the same id in `episodes` and `clips` is two independent entries.
2. Identity is `id` alone: an id that moves between categories is the same entry and would have to be relocated.

### Choice
`(category, id)`. Matching happens inside the "matching category", and no rule describes moving an entry between categories or reconciling one entry's history across two arrays.

### Risk: 10
Most likely alternative preferred by the author: the same per-category matching.

## T7. Static fields when the source changes them

### Spec Text
> Static | `width` | integer | Pixel width

> Existing entry, changed tracked value | Append new history entry at sync timestamp

### Alternatives
1. **Freeze**: static fields keep their first-observed values; later source values for `published`/`width`/`height` are ignored.
2. **Overwrite**: static fields are refreshed from the newest source snapshot (no history kept).

### Choice
Freeze. The field group is named "Static" precisely in contrast with "Tracked", and the only rule that reacts to a changed source value is scoped to tracked fields.

### Risk: 20
Most likely alternative preferred by the author: overwriting the static fields on every sync, which is what a plain "build the entry from the source row, then merge histories" implementation does.

## T8. Writing the catalog when a sync produced no changes

### Spec Text
> Backup trigger | Before every write to existing `catalog.json`

> Backup content | Byte-for-byte copy of pre-write `catalog.json`

### Alternatives
1. **Always write** on a successful sync (so `catalog.bak` always exists afterwards and holds the previous file).
2. **Write only when something changed**, leaving no backup for a no-op sync.

### Choice
Always write. It makes `catalog.bak` a dependable "state before the last sync" artifact, and a no-op sync then produces a backup identical to the catalog, which is consistent with "byte-for-byte copy of pre-write `catalog.json`".

### Risk: 15
Most likely alternative preferred by the author: skipping the write (and therefore the backup) when nothing changed.

## T9. Booleans where an integer is required

### Spec Text
> `views` | integer | Current view count

> If any source entry is missing a required field or has the wrong type, `sync` must fail as a source metadata fetch failure

### Alternatives
1. Reject `true`/`false` for `width`, `height`, `views`, `likes` (Python's `bool` is a subclass of `int`, but JSON booleans are not integers).
2. Accept them, as a bare `isinstance(value, int)` check would.

### Choice
Reject. JSON distinguishes booleans from numbers, and the `removed` field is the only place the schema calls for booleans.

### Risk: 10
Most likely alternative preferred by the author: accepting booleans as integers by way of an unguarded `isinstance` check.

## T10. Duplicate ids inside one source category

### Spec Text
> `id` | string | Unique identifier

### Alternatives
1. Process rows in order, so a repeated id is treated as an update of the entry created by the earlier row (last row wins for the current value).
2. Reject the payload as malformed.

### Choice
Process in order. The spec lists only missing/mistyped fields as malformed-entry causes, so uniqueness is stated as a source property rather than a validation rule.

### Risk: 10
Most likely alternative preferred by the author: the same in-order processing (a dict keyed by id, last row winning).

## T11. Backup location and `init`

### Spec Text
> Backup path | `catalog.bak`

> Backup trigger | Before every write to existing `catalog.json`

### Alternatives
1. `<name>/catalog.bak`, next to the catalog; `init` writes a brand-new file, so it creates no backup.
2. `catalog.bak` relative to the process working directory.

### Choice
`<name>/catalog.bak`. The catalog path is given as `<name>/catalog.json`, and a backup that lands outside the vault would collide between vaults. `init` has no pre-write file to copy, so it leaves no backup.

### Risk: 5
Most likely alternative preferred by the author: the same vault-relative path.

## T12. `annotations` on entries created by `sync`

### Spec Text
> | `3` | Native format | Category arrays; full `source`; ISO 8601 history keys; `removed`; `annotations` |

> `annotations` | Add `[]` to every entry

> Version 1 entries have **no** `removed` field and **no** `annotations` field.

### Alternatives
1. **Every v3 entry has `annotations`**: `sync` gives each newly observed entry an
   `annotations: []`, exactly like migration does, so a native catalog and a migrated
   one have the same entry shape.
2. **Only migration adds it**: the current spec increment mentions `annotations` only
   in the migration tables, so `sync` keeps creating entries without the field and it
   appears solely in migrated catalogs (the behavior of the previous increment).

### Choice
Reading 1. The "Shape Summary" column describes what a catalog of each version looks
like, and it lists `annotations` as a defining feature of v3; the repeated emphasis
that v1/v2 entries have **no** `annotations` is only a contrast if v3 entries have one.
A catalog where migrated entries carry `annotations` and entries added by the next
`sync` do not would satisfy neither reading of that table.

### Risk: 45
Most likely alternative preferred by the author: `sync` leaving `annotations` out, so
the field exists only on migrated entries until some future `annotate` command.

## T13. Version 2 history keys during migration

### Spec Text
> | `2` | Supported | Category arrays; full `source`; ISO 8601 history keys; ... |

> `source` | Preserve existing value

(The v2 → v3 table lists no history-key rule, unlike the v1 → v3 table.)

### Alternatives
1. **Preserve verbatim**: v2 keys are already ISO 8601, so they are copied unchanged,
   including any `Z` suffix or fractional seconds.
2. **Normalize**: re-render every key as `YYYY-MM-DDTHH:MM:SS`, matching the datetime
   text rule that governs everything this implementation writes.

### Choice
Preserve verbatim. The v1 table spells out a key conversion and the v2 table
deliberately does not, so the absence is meaningful: for v2 the migration only adds
`removed`, `annotations` and the version bump. Keys are still parsed, so non-ISO text
is rejected as malformed entry data.

### Risk: 25
Most likely alternative preferred by the author: normalizing v2 keys through the same
formatter used for every other stored timestamp. The two readings agree for fixtures
written as plain `YYYY-MM-DDTHH:MM:SS`.

## T14. Entry order in a migrated catalog

### Spec Text
> Entries | Move every object from `entries` to `episodes`

> Categories | Preserve `episodes`, `streams`, and `clips` placement

### Alternatives
1. **Apply the standard catalog ordering** (newest `published` first, ties by `id`)
   when the migrated catalog is written, like every other write.
2. **Keep the legacy file order**, since migration is described as a move, not a sort.

### Choice
Reading 1. Ordering is a documented property of `catalog.json` itself, not of `sync`,
and "Post-migration usability: all subsequent commands operate as for a vault created
in v3" is most literally true when the migrated file is indistinguishable from one the
tool would have produced natively. "Placement" in the v2 table is about which category
an entry lands in, which is preserved either way.

### Risk: 25
Most likely alternative preferred by the author: writing the entries in their original
order, if their migration builds the new catalog and saves it without the sort step.

## T15. `published` values during migration

### Spec Text
> `published` | string | ISO 8601 datetime

(The v1 → v3 and v2 → v3 tables list conversions for `source_id`, entries, categories,
history keys, `removed`, `annotations` and `version` - not for `published`.)

### Alternatives
1. **Preserve verbatim**: the stored text is copied as-is.
2. **Normalize** to `YYYY-MM-DDTHH:MM:SS`, as `sync` does for source values.

### Choice
Preserve verbatim. Both migration tables enumerate exactly what changes, and
`published` is not in them; a legacy vault's own value is not source data being
ingested. Fixtures written in the native text are identical under both readings.

### Risk: 20
Most likely alternative preferred by the author: normalizing, if their migration reuses
the entry builder that `sync` uses for source rows.

## T16. What counts as malformed v1 or v2 entry data

### Spec Text
> Malformed v1 or v2 entry data | Error to stderr; exit non-zero; leave `catalog.json` unchanged

### Alternatives
1. **Validate against the documented legacy entry schema**: the four static fields with
   their types, five non-empty history objects, keys that parse (epoch seconds for v1,
   ISO 8601 for v2) and values of the documented type.
2. **Only fail on what the conversion itself touches**: a key that cannot be converted.
   Wrong value types or a missing `width` would pass straight into the v3 catalog.

### Choice
Reading 1. The v1 and v2 entry schemas are given as tables of required fields and
types, and the same strictness is already applied to native catalogs and to source
payloads; validating before any write is what makes "leave `catalog.json` unchanged"
hold. Empty history objects are rejected because a tracked field with no data point has
no current value.

### Risk: 30
Most likely alternative preferred by the author: a looser check that only rejects
unconvertible history keys, leaving other malformed fields to fail later or not at all.

## T17. Integer versions below `1`

### Spec Text
> Non-integer `version` field | Version-related error ...

> `version` greater than `3` | Version-related error ...

### Alternatives
1. Treat any integer outside `{1, 2, 3}` - including `0` and negatives - as the same
   version error.
2. Treat only `> 3` as an error and attempt to read `0` or `-1` as some other shape.

### Choice
Reading 1. The supported-versions table is exhaustive, and there is no described layout
for any other value; reporting an unsupported version is the only safe outcome.

### Risk: 10
Most likely alternative preferred by the author: the same rejection, possibly with a
message worded for "unknown" rather than "too new" versions.

## T18. Scope of the migration timestamp

### Spec Text
> Migration-added timestamp scope | Each migration-added `removed` timestamp must be ISO 8601; cross-entry equality is not required

### Alternatives
1. One wall-clock stamp computed per migration and shared by every entry.
2. A fresh stamp per entry.

### Choice
One stamp per migration. It is allowed by the rule (equality is permitted, just not
required), keeps a migrated catalog readable, and makes the `sync`-on-legacy path
deterministic: the sync timestamp is then the single second after the migration stamp.

### Risk: 5
Most likely alternative preferred by the author: the same shared stamp; any test has to
accept both, since cross-entry equality is explicitly not required.

## T19. Native catalogs that predate `annotations`

### Spec Text
> `3` | Native format | ... `removed`; `annotations`

> v3 reload | No additional history entry, no semantic modification, no backup write

### Alternatives
1. **Lenient**: a v3 catalog whose entries have no `annotations` is still valid and is
   left exactly as it is.
2. **Strict**: require `annotations` on every v3 entry, rejecting such a catalog as
   invalid - or backfilling `[]` on load.

### Choice
Lenient. Backfilling would be a semantic modification on a v3 reload, and rejecting
would make v3 catalogs written by earlier builds unreadable even though `removed` -
the field that actually carries history - is present. `annotations` is therefore
written but never required.

### Risk: 15
Most likely alternative preferred by the author: requiring the field, if their v3
validator checks the full entry schema including `annotations`.

## T20. A legacy vault whose `sync` fails

### Spec Text
> v1 vault | Auto-migrate to v3 in memory, apply sync updates, write v3 catalog to disk

> Trigger | `migrate` command or `sync` on a v1/v2 vault

### Alternatives
1. **All or nothing**: the migration only reaches disk as part of the sync write, so a
   failed fetch leaves the legacy `catalog.json` exactly as it was.
2. **Persist the migration first**, then fail the sync, leaving a migrated v3 catalog
   behind.

### Choice
Reading 1. The sequence given is migrate-in-memory, apply updates, write once, and the
existing rule that a failing sync leaves the vault untouched is unqualified. A vault
that silently changed version because the network was down would also make the backup
mean two different things.

### Risk: 20
Most likely alternative preferred by the author: saving the migration as soon as the
catalog is loaded ("Save timing: save migrated v3 catalog immediately"), which would
leave a v3 catalog behind even when the fetch fails.
