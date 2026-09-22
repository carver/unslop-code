# AMBIGUITIES

Numbered record of spec under-specification, the interpretation chosen, and the
risk that the spec author's own implementation reads it differently.

---

## T1: One sync timestamp per run vs. one per appended history entry

### Spec Text
> `Collision handling` | When a new history entry would reuse an existing or non-newer second, advance to a strictly later second before writing

> `Sync timestamps` | Reflect sync execution time and remain strictly increasing whenever new history entries are appended

### Alternatives
1. Allocate a single timestamp for the whole `sync` run, advanced past the newest
   timestamp found anywhere in the catalog, and use it for every append in that run.
2. Allocate a timestamp per tracked-field history, advancing only past that one
   history's newest key. Two fields on the same entry could then get different
   timestamps within one sync.
3. Advance on every individual append, so a sync touching N fields writes N
   consecutive seconds.

### Choice
Alternative 1. "Sync timestamps ... reflect sync execution time" describes a
property of the sync, not of a field, and the "First observation" rule says the
initial `removed: false` is set "at sync timestamp" — the definite article
implies one timestamp shared by the six initial history entries of a new entry.
Advancing past the global catalog maximum makes strict increase hold across
consecutive syncs in the same second, which is what the determinism table asks for.

### Risk: 20
The author most likely computes one timestamp per sync run as well; the residual
risk is that they advance past each field's own newest key rather than the global
maximum, which differs only when histories are unevenly timestamped.

---

## T2: Does a no-change sync still write (and therefore back up) the catalog?

### Spec Text
> `Backup trigger` | Before every write to existing `catalog.json`

> `Success effect` | Update catalog with new, changed, removed, and restored entries

### Alternatives
1. `sync` always rewrites `catalog.json`, so `catalog.bak` is always produced/refreshed.
2. `sync` writes only when something actually changed, so a second identical sync
   leaves `catalog.bak` untouched (or absent after a first sync on a fresh vault).

### Choice
Alternative 1. The persistence rule is phrased as a property of writes ("before
every write"), not as a condition on changes, and re-sorting/normalizing on every
sync keeps the file canonical. Always writing makes `catalog.bak` a reliable
"state before the last sync" snapshot, which is the obvious intent of the backup.

### Risk: 35
The author may short-circuit when no field changed; a test asserting
`catalog.bak` does not exist after a no-op second sync would then fail against
this implementation. Most likely preferred reading if different: write only on change.

---

## T3: Source response missing one of the three category arrays

### Spec Text
> `Source response shape` | JSON object with `episodes`, `streams`, and `clips` arrays

### Alternatives
1. A missing (or non-array) category key is a source metadata fetch failure; the
   vault is left unchanged.
2. A missing category is treated as an empty array, so every stored entry in that
   category gets `removed: true`.

### Choice
Alternative 1. The response shape is stated as a requirement, and the spec
already routes malformed source data to the "source metadata fetch failure" case.
Silently deleting a whole category's worth of live entries because of a truncated
response is the more destructive reading.

### Risk: 40
This is the least-constrained corner of the source contract. An author using
`payload.get("episodes", [])` would get alternative 2 for free, and that is a
natural fixture to write ("partial response marks entries removed").

---

## T4: Entry identity — per category or global across categories?

### Spec Text
> `id` | string | Unique identifier

> `First observation` | Add entry to matching category

### Alternatives
1. Entries are keyed by (category, id): an id is looked up only within its own
   category array.
2. Entries are keyed by id alone across the whole catalog; an id that moves
   between categories updates the existing entry in place, or moves it.

### Choice
Alternative 1. The catalog stores three independent arrays and the update rules
speak of "the matching category". Under this reading, the same id appearing in a
different category is a new entry there and a removal in the old category.

### Risk: 20
"Unique identifier" could be read as globally unique, but a fixture that moves an
id between categories is unusual, so the two readings rarely diverge on tested input.

---

## T5: Normalizing a `published` value that carries a timezone offset

### Spec Text
> `Datetime text` | `YYYY-MM-DDTHH:MM:SS` without timezone suffix

### Alternatives
1. Drop the offset and keep the local wall-clock time (`2024-01-02T10:00:00+05:00`
   → `2024-01-02T10:00:00`).
2. Convert to UTC, then drop the offset (→ `2024-01-02T05:00:00`).
3. Reject offset-bearing values as malformed source data.

### Choice
Alternative 1. The rule is stated as a text-formatting rule ("without timezone
suffix"), not as a conversion rule, and nothing in the spec mentions UTC or any
reference zone. Truncating the suffix is the literal reading.

### Risk: 30
An author who parses with `datetime.fromisoformat` and calls `.astimezone(utc)`
would produce alternative 2. Most likely alternative reading: convert to UTC first.

---

## T6: Are booleans acceptable where an integer is required?

### Spec Text
> If any source entry is missing a required field or has the wrong type, `sync`
> must fail as a source metadata fetch failure and leave the vault unchanged.

### Alternatives
1. `True`/`False` are the wrong type for `width`, `height`, `views`, `likes` and
   are rejected.
2. Booleans pass, because in Python `bool` is a subclass of `int`.

### Choice
Alternative 1. JSON distinguishes `true` from `1`, and the schema lists a separate
boolean type for `removed`, so the spec clearly treats them as distinct types.

### Risk: 20
A plain `isinstance(value, int)` check accepts booleans, so an author who did not
think about it would prefer alternative 2 — but only a deliberately adversarial
fixture (`"views": true`) would reveal the difference.

---

## T7: Unrecognized fields on source entries and on stored entries

### Spec Text
> Each source entry must contain all nine fields above with the stated types.

> `Local-only fields` | Source data does not include `removed` or `annotations`

### Alternatives
1. Extra source fields are ignored (not stored); extra local fields already on a
   stored entry — such as `annotations` — are preserved across syncs.
2. Extra source fields make the entry malformed.
3. Stored entries are rebuilt from source each sync, dropping local-only extras.

### Choice
Alternative 1. The requirement is that all nine fields are *present*, not that no
others are. `annotations` is named as a local-only field even though it is not in
the stored-fields table, which only makes sense if the tool must not clobber it.

### Risk: 10
Preserving unknown keys is the conservative behavior and matches the explicit
mention of `annotations`.

---

## T8: What counts as a source metadata fetch failure

### Spec Text
> `Source metadata fetch failure` | stderr | non-zero | Error message; malformed
> source entries are included in this case

### Alternatives
1. Transport errors, non-2xx HTTP status, non-JSON bodies, a non-object top-level
   value, bad response shape, and malformed entries all map to this one case.
2. Only transport errors count; bad payloads surface as some other error class.

### Choice
Alternative 1. The row explicitly folds malformed entries into the fetch-failure
case, which signals that the category is "anything that prevented obtaining valid
source metadata". All of these exit non-zero with a stderr message, so observable
behavior is uniform.

### Risk: 10
Exit code and stream are identical under either reading; only message wording differs.

---

## T9: What makes a vault "invalid"

### Spec Text
> `Missing or invalid vault` | Error to stderr including `<name>`; exit non-zero

### Alternatives
1. Invalid = `<name>/` is not a directory, `catalog.json` is absent, unreadable,
   not valid JSON, not a JSON object, missing `source`/`version`/any of the three
   category keys, or has those keys with the wrong types.
2. Only absence of the directory or of `catalog.json` counts; a corrupt catalog
   crashes with a traceback.

### Choice
Alternative 1. The spec lists "sync with invalid vault" as its own error row
distinct from "non-existent vault", so structural validation of `catalog.json`
must happen before any source request.

### Risk: 25
The exact validation set is a judgment call — an author might accept a catalog
that is missing, say, `clips` and repair it silently rather than erroring.

---

## T10: Does a `version` other than `3` make the vault invalid?

### Spec Text
> `version` | integer | `3`

### Alternatives
1. A catalog whose `version` is not `3` is an invalid vault and `sync` errors.
2. Any integer `version` is accepted; the field is only a contract for what `init` writes.

### Choice
Alternative 1. The root schema gives `3` as the required value, not a default, and
there is no migration story anywhere in the spec.

### Risk: 30
If the author only validates presence/type, a fixture with `"version": 2` would be
synced successfully. Most likely alternative reading: accept any integer version.

> **Resolved by the multi-version loading spec.** Versions `1` and `2` are now
> loaded and migrated rather than rejected; only a missing, non-integer, or
> greater-than-`3` version is an error. The choice above survives as the
> treatment of unsupported versions, not of every non-`3` version.

---

## T11: Storage form of a date-only `published`

### Spec Text
> `Date-only source values` | Normalize to `00:00:00` time component

> `published` | string | Original publication datetime

### Alternatives
1. `"2024-03-05"` is stored as `"2024-03-05T00:00:00"`.
2. The date-only text is stored verbatim and normalized only for comparison/sorting.

### Choice
Alternative 1. The determinism table puts the normalization rule next to the
datetime-text rule, both describing output text, and the stored field is typed as
a "publication datetime". Storing the normalized form also makes the ordering rule
a plain string comparison.

### Risk: 20
An author who normalizes only inside the sort key would keep the raw text on disk.

---

## T12: Duplicate ids within one source category

### Spec Text
> `id` | string | Unique identifier

### Alternatives
1. Process entries in order, so a later duplicate updates the entry the earlier one
   created (last occurrence wins).
2. Treat duplicates as malformed source data and fail.

### Choice
Alternative 1. Uniqueness is stated as a property of the data, not as a validation
rule the tool must enforce, and the nine-field schema check is the only source
validation the spec spells out.

### Risk: 15
Fixtures with duplicate ids are unlikely; if present, an author's dict-building
loop would also naturally give last-wins.

---

## T13: `published` text that is not parseable as a date or datetime

### Spec Text
> `published` | string | ISO 8601 datetime or date-only text

### Alternatives
1. A non-parseable string is malformed source data (fetch failure).
2. It is a string, so it passes type validation and is stored verbatim; ordering
   falls back to raw string comparison.

### Choice
Alternative 1. The schema names the value space as "ISO 8601 datetime or date-only
text", and the tool cannot honor the normalization or ordering rules for a value it
cannot parse. Failing keeps the vault consistent.

### Risk: 30
The validation sentence enumerates "missing a required field or has the wrong
type" — `"tomorrow"` is a string, so a strictly type-based author accepts it.
Most likely alternative reading: accept any string and store it as-is.

---

## T14: `init` when `<name>` exists as a non-directory file

### Spec Text
> `Existing directory` | Error to stderr including `<name>`; exit non-zero; no
> modification of existing data

### Alternatives
1. Any existing path at `<name>` — file, directory, or symlink — is an error.
2. Only an existing directory errors; an existing regular file is overwritten by
   `mkdir` failing loudly with a traceback.

### Choice
Alternative 1. "No modification of existing data" is the governing intent, and a
clean error beats an uncaught `FileExistsError`.

### Risk: 15
Both readings exit non-zero with a message naming the vault; the difference is
only whether the failure is graceful.

---

## T15: Ordering of the `removed` history relative to other tracked fields on restore

### Spec Text
> `Previously removed entry reappears` | Append `removed: false` at sync timestamp

### Alternatives
1. On reappearance, `removed: false` is appended and any tracked field whose value
   changed while the entry was gone also gets an append at the same timestamp.
2. Reappearance only writes `removed: false`; other fields resync on the next run.

### Choice
Alternative 1. The update rules are independent per field — "existing entry,
changed tracked value" applies to a reappearing entry just as to any other, and
there is no exception carved out for restores.

### Risk: 10
Treating the six tracked fields uniformly is the straightforward implementation.

---

## T16: Do entries created by `sync` in a native v3 vault get `annotations`?

### Spec Text
> | `3` | Native format | Category arrays; full `source`; ISO 8601 history keys; `removed`; `annotations` |

> `annotations` | Add `[]` to every entry

### Alternatives
1. `annotations` is created only by migration; a first observation in a native v3
   vault still stores the ten fields it always has, and `annotations` is only
   preserved when something else put it there.
2. Every entry a v3 vault creates also gets `annotations: []`, so a migrated
   vault and a natively created one are byte-comparable in shape.

### Choice
Alternative 1. The earlier spec's stored-entry table did not list `annotations`
(see T7), and this spec adds it only as a migration output; changing what a first
observation writes is a change to v3 behavior that this spec never asks for.

### Risk: 35
The v3 row of the version table does name `annotations` as part of the native
shape, so the author may well create it at first observation. Most likely
alternative reading: `sync` adds `annotations: []` to every new entry too.

---

## T17: What counts as "malformed v1 or v2 entry data"

### Spec Text
> `Malformed v1 or v2 entry data` | Error to stderr; exit non-zero; leave `catalog.json` unchanged

### Alternatives
1. Every legacy entry is validated against the version's entry schema before
   anything is written: it must be an object, carry `id`/`published` strings and
   `width`/`height` integers, and carry all five history objects whose keys parse
   in that version's key format and whose values have the documented types.
2. Only the failures that would crash the converter are errors (a non-object
   entry, a non-numeric v1 epoch key); anything else is copied through untouched.
3. Nothing is validated; malformed data is carried into the v3 catalog.

### Choice
Alternative 1. The schema tables are stated as the definition of a v1/v2 entry,
and the error row exists precisely so malformed entries do not reach disk. The
whole catalog is converted in memory first, so any single bad entry aborts the
run before the backup or the write.

### Risk: 40
The exact validation set is the least-constrained part of this spec. An author
who only guards the epoch conversion would accept, say, a `views` history holding
a string. Most likely alternative reading: validate only what conversion touches.

---

## T18: Integer `version` values below `1`

### Spec Text
> `version` greater than `3` | Version-related error to stderr; exit non-zero

### Alternatives
1. Only `1`, `2` and `3` are supported; `0` or a negative version is the same
   version-related error as `4`.
2. The error is written for versions above `3` only, so `0` falls through to some
   other failure (or is treated as v1).

### Choice
Alternative 1. The supported-versions table is exhaustive, and "greater than `3`"
names the realistic failure (a catalog from a newer tool) rather than carving an
exception for versions that never existed.

### Risk: 15
A `version: 0` fixture is unlikely, and both readings exit non-zero with a
version-related message under any sane implementation.

---

## T19: Does migration order the entries it produces?

### Spec Text
> `Entries` | Move every object from `entries` to `episodes`

> `Categories` | Preserve `episodes`, `streams`, and `clips` placement

### Alternatives
1. Migration moves entries verbatim and in their existing order; the newest-first
   ordering rule is (re)applied by the next `sync`, as it always is.
2. Migration also sorts each category into the v3 ordering, so a migrated catalog
   is indistinguishable from a synced one.

### Choice
Alternative 1. "Move" and "preserve" are both transport words, and the determinism
section demands "no semantic modification" from a reload. Ordering is restored on
the next sync anyway, so nothing downstream depends on migration sorting.

### Risk: 25
An author who funnels the migrated catalog through the same save path as `sync`
would get alternative 2 for free. A fixture whose v1 `entries` are not already in
newest-first order would expose the difference.

---

## T20: `serve` and `digest` are named as load triggers but do not exist

### Spec Text
> `Load trigger` | Any command that reads a vault (`sync`, `serve`, `digest`, and future commands)

> `Read-only access` | Loading a v1 or v2 catalog for a read-only operation does **not** rewrite `catalog.json`

### Alternatives
1. The row describes the loading rule's scope, not a command list to implement:
   the CLI keeps `init`, `sync` and `migrate`, and the read-only guarantee is
   satisfied by loading never writing on its own.
2. `serve` and `digest` must be invented here, with behavior chosen freely.

### Choice
Alternative 1. This spec defines no syntax, output, or effect for `serve` or
`digest`; inventing two commands from two mentions would be guesswork, while the
loading rule is implementable exactly as stated.

### Risk: 20
If the author's tool already has those commands from another spec, their fixtures
may call them and find them missing — but nothing in this document says what they
would print.

---

## T21: Does `migrate` on a v3 vault rewrite `catalog.json`?

### Spec Text
> `Effect on v3` | No-op; no backup written

### Alternatives
1. Nothing is written at all: the catalog file is left byte-identical and
   untouched.
2. The catalog is re-serialized in place (same content, new mtime) and only the
   backup is skipped.

### Choice
Alternative 1. "No-op" is stated first and unqualified; the backup clause is a
consequence of not writing, not an exception to writing.

### Risk: 10
Both readings leave semantically identical content; only a byte or mtime
comparison could tell them apart.

---

## T22: One migration timestamp per run, or one per entry?

### Spec Text
> `Migration-added timestamp scope` | Each migration-added `removed` timestamp must be ISO 8601; cross-entry equality is not required

### Alternatives
1. One timestamp is allocated per migration run and shared by every entry.
2. Each entry gets its own `datetime.now()` reading, so entries may differ.

### Choice
Alternative 1. "Cross-entry equality is not required" permits both but demands
neither; a single reading per run is deterministic and keeps the migrated catalog
comparable entry to entry.

### Risk: 5
The rule explicitly refuses to test cross-entry equality, so no conforming fixture
can distinguish the two.

---

## T23: When is the migrated catalog written during `sync`?

### Spec Text
> `Save timing` | Save migrated v3 catalog immediately

> v1 vault | Auto-migrate to v3 in memory, apply sync updates, write v3 catalog to disk

> `Backup before write` | Standard backup rules apply; backup contains the **original** pre-migration catalog

### Alternatives
1. `sync` writes once: migrate in memory, fetch, apply, then a single backed-up
   write. A fetch failure leaves the vault at v1/v2 on disk.
2. `sync` writes the migrated catalog before fetching, then writes again after
   applying updates. A fetch failure leaves a migrated-but-unsynced v3 catalog.

### Choice
Alternative 1. The sync row says "in memory ... apply sync updates, write v3
catalog", and only a single write can leave the *original* pre-migration catalog
in `catalog.bak` — under alternative 2 the final backup would hold the freshly
migrated v3.

### Risk: 20
"Save migrated v3 catalog immediately" pulls toward alternative 2. A fixture that
fails the fetch on a v1 vault and then checks the on-disk version would separate
the two readings.

---

## T24: Are legacy datetime texts other than v1 epoch keys normalized?

### Spec Text
> `v1 UNIX-epoch conversion` | Convert each epoch-seconds key to `YYYY-MM-DDTHH:MM:SS` in UTC

> `published` | string | ISO 8601 datetime

### Alternatives
1. Only v1 history keys are rewritten. `published` values and v2 history keys are
   carried across exactly as stored.
2. Everything is re-rendered into the canonical `YYYY-MM-DDTHH:MM:SS` text, so a
   v2 key of `2024-06-15T09:40:00Z` or a date-only `published` is rewritten.

### Choice
Alternative 1. The determinism table names exactly one conversion, and the v2
migration table says only "preserve". Rewriting values the spec does not mention
would be the "semantic modification" that a reload is forbidden to make.

### Risk: 15
Legacy fixtures are likely already in canonical form, in which case the readings
agree. Most likely alternative reading: normalize every datetime on the way in.

---

## T25: Root keys that are not part of the v3 schema

### Spec Text
> `source_id` | Convert to `source` using `https://media.example.com/channel/<source_id>`

> `Entries` | Move every object from `entries` to `episodes`

> All commands that need a source URL for a version 1 vault must use this derivation.

### Alternatives
1. The migrated catalog holds exactly the five v3 root keys: `source_id` and
   `entries` are consumed by the conversion, and any other root key is dropped.
   A `source` key that happens to sit in a v1 catalog is ignored in favour of the
   derivation.
2. Unrecognized root keys are carried into the v3 catalog, and an existing
   `source` on a v1 catalog wins over the derivation.

### Choice
Alternative 1. "Convert" and "move" describe replacement rather than addition, and
the source rule says every command *must* use the derivation for a v1 vault, which
leaves no room for a stray `source` key to take precedence.

### Risk: 25
An author who mutates the loaded dict in place (`catalog["episodes"] =
catalog.pop("entries")`) would keep unknown root keys, so a fixture with an extra
root field would show a difference.
