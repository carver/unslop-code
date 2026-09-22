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
