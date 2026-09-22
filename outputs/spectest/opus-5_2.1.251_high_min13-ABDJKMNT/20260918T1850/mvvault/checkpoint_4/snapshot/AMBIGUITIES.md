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

### Update (download/digest spec)
Resolved for `digest`: the later spec defines its syntax, output layout, and
format-aware loading, and it is now implemented. `serve` remains unspecified and
is still not implemented.

### Update (viewer spec)
Fully resolved: the viewer spec defines `serve`'s syntax, bind address, routes
and pages, and the command now exists. Loading for the viewer stays read-only,
exactly as this entry assumed.

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

---

## T26: Building asset URLs from a source URL that names a document

### Spec Text
> Media | `<source>/media/<entry_id>`

> Preview | `<source>/preview/<entry_id>`

### Alternatives
1. `<source>` is the stored source string used literally: the asset URL is the
   source text with `/media/<id>` appended, so a source of
   `http://host/source.json` yields `http://host/source.json/media/e1`.
2. `<source>` means the directory the source document lives in, so the last path
   segment is dropped and the asset URL is `http://host/media/e1`.
3. The source string is treated as a base for `urljoin`, which also drops the
   last segment but additionally resolves an absolute `/media/...`.

### Choice
Alternative 1, with a single trailing slash on the source trimmed first. The
table writes `<source>` — the same placeholder the rest of the spec uses for the
stored `source` field — and pure appending is the only reading that does not
invent a path-stripping rule the spec never states.

### Risk: 10
Concatenation is what the table literally says, and a fixture server can answer
any path. Most likely alternative reading: `urljoin` against the source URL,
which differs whenever the source ends in a filename.

---

## T27: Turning a `Content-Type` into a file extension

### Spec Text
> Media extension without override | Derive from HTTP `Content-Type`

### Alternatives
1. Use the subtype of the media type (`video/mp4` → `mp4`), with a short table
   for the types whose conventional extension is not their subtype
   (`image/jpeg` → `jpg`, `audio/mpeg` → `mp3`, `application/octet-stream` →
   `bin`), and ignore any `;` parameters.
2. Use `mimetypes.guess_extension`, which knows the same conventional names but
   returns nothing at all for types outside its table.
3. Use the whole media type, slash and all, as the extension.

### Choice
Alternative 1. It always produces an extension, which the spec assumes it can
(there is no "unknown content type" row), and it agrees with
`mimetypes.guess_extension` on every common type a media source would send.

### Risk: 35
The obvious fixtures (`video/mp4`, `image/png`) agree under every reading. Most
likely alternative reading: `mimetypes.guess_extension`, which differs on
uncommon types such as `video/x-matroska`.

---

## T28: Which entries get a preview download, and whether limits apply to previews

### Spec Text
> Download phase | Retrieve media and preview files after metadata phase

> `--episodes=<n>` | non-negative integer | Maximum number of episode media downloads

> Candidate selection | Only entries without a corresponding media file in `<vault>/media/` are candidates

### Alternatives
1. Candidate selection and the per-category limits choose a set of entries, and
   each selected entry has both its media and its preview fetched. An entry that
   already has media is not touched at all.
2. Previews are selected independently: every entry lacking a preview file gets
   one, regardless of the media limits, so `--episodes=0` still downloads
   previews.

### Choice
Alternative 1. The spec gives exactly one candidate rule, phrased in terms of the
media directory, and the limits are described as counting "media downloads" —
which is only a meaningful distinction if previews ride along with the media
selection rather than being counted themselves.

### Risk: 30
Both readings agree whenever media and previews are both missing, which is the
normal case. Most likely alternative reading: previews keyed off the previews
directory independently of the media limits.

---

## T29: What counts as a "corresponding media file", and what a partial artifact is

### Spec Text
> Candidate selection | Only entries without a corresponding media file in `<vault>/media/` are candidates

> Partial artifacts | Stale partial-download artifacts must not block a later successful download

### Alternatives
1. A file corresponds to an entry when its name, minus its extension, equals the
   entry id — except for the `.part` suffix this tool writes in-progress
   downloads under, which is skipped so a leftover `e1.part` never suppresses a
   retry. Downloads are written to `<id>.part` and renamed into place on success.
2. Any filename containing the entry id counts, so `e1.part` blocks `e1`.
3. Emptiness is the partial-download signal: a zero-byte `e1.mp4` is treated as
   stale and re-fetched.

### Choice
Alternative 1. The two rows only cohere if the in-progress artifact is
distinguishable from a finished file, and a reserved suffix plus an atomic rename
is the ordinary way to make it so. Reading (3) would also discard a legitimately
empty asset, which the spec says is downloadable content.

### Risk: 30
A fixture that plants a stale artifact will most likely name it with the same
suffix the author's own implementation writes. Most likely alternative reading: a
different reserved suffix, such as `.tmp` or `.download`.

---

## T30: Which download failures are transient, and how many retries they get

### Spec Text
> Permanent download failure | Warning to stderr; continue with remaining entries

> Transient download failure | Retry, then warn to stderr after retries exhausted; continue with remaining entries

### Alternatives
1. Transient means the request could not be completed or the server said it was
   temporary: a transport error, a timeout, `408`, `429`, or any `5xx`. Every
   other error status — notably `404` and `403` — is permanent and is not
   retried. Three attempts in total.
2. Only transport-level errors are transient; every HTTP status response,
   including `503`, is a permanent answer from a reachable server.
3. Everything is retried, and "permanent" only describes a `404`.

### Choice
Alternative 1. It is the conventional split, and it is the only one under which
both rows have a natural trigger: a `404` for an entry the source no longer
serves is permanent, a `503` is the textbook transient failure.

### Risk: 30
The retry count is invisible to a test that either fails once or fails forever.
Most likely alternative reading: transport errors only, so a persistent `503`
would warn without ever being retried.

---

## T31: Does `--skip-metadata` persist a migrated legacy catalog?

### Spec Text
> `--skip-metadata` | flag | Skip source fetch and metadata update; run download phase against existing vault state

> Because `sync` auto-migrates v1 and v2 vaults to v3 during the metadata phase, the download phase always operates against a v3 catalog.

### Alternatives
1. The migration is part of the metadata phase, so `--skip-metadata` never writes
   `catalog.json`: the catalog is still migrated in memory to find the `source`
   value, and the file is left in its legacy form.
2. Migration happens on load, independently of the phases, so even a
   download-only run rewrites the catalog as v3.

### Choice
Alternative 1. The spec places auto-migration explicitly "during the metadata
phase", and `--skip-metadata` skips that phase; the in-memory conversion still
supplies the migrated `source` the download phase is told to use.

### Risk: 20
Most likely alternative reading: migration is a property of loading, so a
download-only run on a v1 vault leaves a v3 catalog behind.

---

## T32: How the post-sync counts classify an entry

### Spec Text
> Counts reported | Added, removed, updated

> Wording | Unspecified

### Alternatives
1. The three counts mirror the `digest` groups, applied to this run only and with
   the same precedence: an entry created this run is added, an entry whose
   `removed` flipped to `true` this run is removed, an entry with any other
   tracked-field change is updated, and each entry counts once.
2. The counts are independent tallies, so an entry that is both new and changed
   increments two of them.
3. `updated` counts field changes rather than entries.

### Choice
Alternative 1. The same document defines exactly this three-way classification
with an explicit "each entry may appear once" rule for `digest`; reusing it keeps
a `sync` summary and a following `digest` telling the same story.

### Risk: 30
A newly added entry has no prior value to differ from, so readings (1) and (2)
agree on the common fixtures. Most likely alternative reading: `updated` counts
every entry that gained any history entry, including new ones.

---

## T33: Entry order within a `digest` group

### Spec Text
> Entry order within group | Deterministic

> Download candidate order | Same as catalog order within category

### Alternatives
1. Catalog order — the order the entries are stored in, which is the order the
   rest of the spec makes canonical.
2. Alphabetical by current title.
3. By entry id.

### Choice
Alternative 1. The spec never asks `digest` to re-order anything, and the one
place it does pin an order for a list of entries ("catalog order within
category") makes stored order the document's default meaning of deterministic.

### Risk: 35
Any of the three is deterministic, so the fixture decides. Most likely
alternative reading: sorted by title, which reads more naturally in a
human-facing summary.

---

## T34: What the `digest` trailing line says

### Spec Text
> Trailing line | Metadata about the digest run

> Source reference | The trailing line includes the resolved source URL for the loaded vault version

> Digest trailing line | Deterministic format

> Wall-clock usage outside digest trailing line | Not part of file naming or vault content

### Alternatives
1. The line reports the run itself: vault name, the catalog version it was read
   at, how many changes were listed, when it was generated, and the resolved
   source URL. "Deterministic format" constrains the shape, not the clock — which
   is why the determinism table carves the trailing line out of the wall-clock
   rule.
2. No timestamp at all, so the whole line is byte-stable.

### Choice
Alternative 1. Excluding the trailing line from the wall-clock prohibition only
makes sense if it is allowed to contain a wall-clock reading.

### Risk: 25
The only pinned content is the source URL, which both readings include. Most
likely alternative reading: a shorter line with no timestamp, which a test could
compare byte-for-byte.

---

## T35: How reappearance is rendered, and whether `removed` is a "changed field"

### Spec Text
> Reappearance after removal (v3 only) | Indicate reappearance alongside any other changed fields

> Field-update suffix | Changed field names in parentheses after title

### Alternatives
1. Reappearance is rendered inside the same parenthesised suffix as a leading
   `reappeared` marker — `Title (reappeared, views)` — so the one suffix carries
   both facts.
2. The raw field name `removed` is listed among the changed fields.
3. Reappearance gets its own group or its own line.

### Choice
Alternative 1. "Alongside any other changed fields" places it in the suffix that
already lists changed fields, and a marker word says what the change was, which a
bare `removed` would not.

### Risk: 30
Most likely alternative reading: the literal field name `removed` in the suffix,
which is what a loop over tracked fields produces without a special case.

---

## T36: `digest` on a catalog that is broken for its declared version

### Spec Text
> Missing vault | Error to stderr including vault name; exit non-zero

> `digest` on vault with unsupported version | stderr | non-zero | Message includes version value

### Alternatives
1. Anything that makes the catalog unreadable — unparseable JSON, a missing
   entry array, a history that is not an object, a v1 key that is not an integer
   — is reported like every other unusable vault: a message naming the vault, to
   stderr, non-zero. Only the two named conditions get their specific wording.
2. `digest` tolerates structural damage and digests whatever it can parse.

### Choice
Alternative 1. The spec only ever describes `digest` failing loudly, and silently
digesting half a damaged catalog would make the output untrustworthy without
telling anyone.

### Risk: 20
Most likely alternative reading: `digest` skips entries it cannot interpret and
still exits zero.

---

## T37: Does `--format` change which entries are candidates?

### Spec Text
> Candidate selection | Only entries without a corresponding media file in `<vault>/media/` are candidates

> Media extension with override | Use override string as extension

### Alternatives
1. Candidate selection ignores the override: an entry with `e1.mp4` on disk is
   not a candidate even under `--format=mkv`, because it already has a
   corresponding media file.
2. The override narrows the rule to a file with that exact extension, so
   `--format=mkv` re-downloads entries that only have `e1.mp4`.

### Choice
Alternative 1. The candidate rule is written without reference to the format
option, and re-fetching everything on a format change would silently multiply the
downloads a limit is there to bound.

### Risk: 20
Most likely alternative reading: the override participates in the existence
check, so changing format re-downloads.

---

## T38: Are removed entries still download candidates?

### Spec Text
> Candidate selection | Only entries without a corresponding media file in `<vault>/media/` are candidates

> `--skip-metadata` | ... run download phase against existing vault state

### Alternatives
1. Removal is irrelevant to candidacy: every stored entry without a media file is
   a candidate, including one the source has stopped listing. A vault keeps
   removed entries precisely so their media can still be archived, and their
   download simply fails permanently once the source drops the asset.
2. Entries whose latest `removed` is `true` are skipped.

### Choice
Alternative 1. The candidate rule states one condition and the spec is explicit
that it is the only one ("Only entries without a corresponding media file").

### Risk: 25
Most likely alternative reading: skip removed entries, on the grounds that their
assets are gone anyway — which shows up as a difference in the warning count.

---

## T39: Are `media/` and `previews/` created when nothing is downloaded?

### Spec Text
> Media | ... | `<vault>/media/` | Filename contains entry `id`

> Metadata-only run | `--skip-download`

### Alternatives
1. The directories are created lazily, the first time a file is actually written
   into them, so a `--skip-download` run leaves the vault with just its catalog.
2. Every `sync` creates both directories up front.

### Choice
Alternative 1. `init` is specified elsewhere as producing `catalog.json` alone,
and the spec describes the directories as download targets rather than as part of
the vault layout.

### Risk: 10
Most likely alternative reading: the download phase makes both directories
unconditionally, which a test would only notice by listing the vault directory.

---

## T40: Where the recent-vault list is kept

### Spec Text
> `Trigger` | Navigation to any vault through viewer

> `Persistence` | Later browser session from same browser must still show visited vault

### Alternatives
1. A persistent cookie: the browser stores the list, the server only reads it
   back. "Same browser" is then literally true, and two browsers see two lists.
2. Server-side state, in the `serve` process or in a file beside the vaults.
   Every client of that server sees the same list.
3. Both: set the cookie, and keep a copy in the server for the run.

### Choice
Alternative 3. "From same browser" only makes sense for something the browser
holds, so the cookie (`Max-Age` one year) is the mechanism that carries the
requirement. The in-process copy costs nothing and keeps the landing page useful
for a client that does not return cookies, which is how the list is most easily
observed.

### Risk: 20
The author most likely stores the list in a cookie alone. A fixture that visits
a vault with one HTTP client and then asserts a *different*, cookie-less client
sees an empty recent area would fail here; nothing in the spec asks for that
isolation, but it is the natural consequence of a cookie-only implementation.

---

## T41: How the landing page learns which vault was not found

### Spec Text
> `Non-existent vault on any /catalog/<name> route` | Redirect to `/`; landing page shows vault-not-found indication; response must not be HTTP `500`

### Alternatives
1. Redirect to `/?missing=<name>` and render the notice from the query string.
2. Redirect to exactly `/` and carry the name in a one-shot cookie.
3. Redirect to exactly `/` and let the landing page always carry a generic
   "vault not found" line, shown whether or not anything went wrong.

### Choice
Alternative 1. The indication has to survive a redirect, and a query parameter
is the only carrier that works for a client with no cookie jar and does not
pollute the ordinary landing page. `/?missing=<name>` is still a redirect to the
landing page, and it lets the page name the vault that was asked for.

### Risk: 25
The author may well redirect to the bare path. A fixture asserting the `Location`
header equals `/` exactly would fail against `/?missing=ghost`, even though
following the redirect lands on the same page.

---

## T42: Invalid category -- redirect or refuse

### Spec Text
> `Invalid category on GET /catalog/<name>/<category>` for v2/v3 vault | Redirect to `/catalog/<name>/episodes` or return HTTP `400`/`404`

### Alternatives
1. Redirect to the version's default category page.
2. Answer `400` or `404`.

### Choice
Alternative 1, the reading the spec lists first: it matches what
`/catalog/<name>` already does with an unknown category (namely, none at all),
and it leaves the browser somewhere useful.

### Risk: 3
The spec permits both outcomes explicitly, so a conforming fixture has to accept
either; only a fixture written against one implementation's exact status would
disagree.

---

## T43: What "a media filename contains entry `id`" covers

### Spec Text
> `Downloaded state (v2/v3)` | Entry counts as downloaded when a media filename in `<vault>/media/` contains entry `id`

### Alternatives
1. Any name in `media/` that contains the id as a substring, case-sensitively,
   including a `.part` file left behind by an interrupted download.
2. Only finished downloads, i.e. the same rule the download phase applies when
   it decides what is still missing, which ignores `.part` files.

### Choice
Alternative 1, the rule as written. The listing rule states one condition and
does not mention partial artifacts; the download phase's own exclusion is
specified separately and is about what to fetch next, not about what to show.

### Risk: 10
Most likely alternative reading: reuse the download phase's notion of a finished
file, which shows up only for a vault holding a `<id>.part` file.

---

## T44: What the post-sync summary looks like now that it carries links

### Spec Text
> `Post-sync summary` | Each changed-entry line includes viewer link on same line as title

> (earlier spec) `Counts reported` | Added, removed, updated

### Alternatives
1. Keep the counts line and add the changed entries above it, grouped by
   category and change group exactly as a digest groups them.
2. Print a flat list of changed entries with no grouping, then the counts.
3. Replace the counts with the entry lines.

### Choice
Alternative 1. The earlier spec's counts are still required, and the two report
surfaces are now described in the same row of the same table, so rendering them
from one grouped-change structure keeps them consistent -- the same entry reads
the same way whether a sync or a digest reports it.

### Risk: 30
The author's summary may list entries without category or group headings, or put
the counts first. Any fixture looking for a title and its link on one line passes
either way; one that pins the exact line layout would not.

---

## T45: Where the viewer link sits on a change line

### Spec Text
> `digest <name>` | Each changed-entry line includes viewer link on same line as title

> (earlier spec) `Field-update suffix` | Changed field names in parentheses after title

### Alternatives
1. `<title> (<fields>) <link>` -- the link last, after the existing suffix.
2. `<title> <link> (<fields>)` -- the link immediately after the title.
3. The title itself rendered as the link target in some bracketed form.

### Choice
Alternative 1. The earlier spec fixes the field suffix "after title", so the link
is appended after it; that keeps both rules literally true and leaves the
existing line prefix untouched.

### Risk: 10
Most likely alternative reading: the link directly after the title. Both put the
link on the title's line, so only a fixture matching a whole line would notice.

---

## T46: `/catalog/<name>/<category>/<id>` for an id that is not in the category

### Spec Text
> `GET` | `/catalog/<name>/<category>/<id>` | HTML response for that viewer link target; may reuse the category listing page with the entry highlighted or otherwise surfaced

### Alternatives
1. Serve the category listing with nothing highlighted: the route is defined by
   its category, and an unknown id simply highlights nothing.
2. Answer `404` for an id the category does not hold.

### Choice
Alternative 1. The row describes the response as "the category listing page with
the entry highlighted", so the page does not depend on the id existing, and a
stale link from an older report still shows the category it pointed into.

### Risk: 15
Most likely alternative reading: `404` for an unknown id. The spec's error table
never mentions unknown ids, which is the reason to treat them as harmless.

---

## T47: `serve <name>` for a vault that cannot be read

### Spec Text
> `serve <name>` | Start server and open browser to default category page for vault

### Alternatives
1. Start anyway and open `/catalog/<name>`, which redirects to the landing page
   and names the vault that was not found.
2. Refuse to start and exit with an error.

### Choice
Alternative 1. The row says `serve` starts a server; the vault-not-found
behavior is already specified for the route, so pointing the browser at the
route reuses it instead of inventing a second failure mode.

### Risk: 5
Most likely alternative reading: a startup error for a name that is not a vault.

---

## T48: Which requests count as "navigation to a vault"

### Spec Text
> `Trigger` | Navigation to any vault through viewer

### Alternatives
1. Any `/catalog/<name>` request that resolves to a readable vault, including
   the bare catalog redirect and the redirect away from an invalid category.
2. Only a rendered category listing.
3. Only an explicit submission of the landing page's form.

### Choice
Alternative 1. "Any vault" and "navigation ... through viewer" are both broad,
and the recent list is most useful when it records where the user actually went;
a vault that could not be read is not recorded, since no navigation succeeded.

### Risk: 10
Most likely alternative reading: only a successful listing counts, which differs
only for a request that stops at a redirect.

---

## T49: Whether viewer links follow a relocated server

### Spec Text
> `Link format` | `http://<host>:<port>/catalog/<name>/<category>/<id>`

> `Default host` | `127.0.0.1`; `Default port` | `8840`

### Alternatives
1. `digest` and `sync` always print the default address; `<host>` and `<port>`
   are placeholders whose values are the documented defaults.
2. Add `--host`/`--port` options to `digest` and `sync` so a report can point at
   a viewer that was moved.

### Choice
Alternative 1. The spec defines `--host` and `--port` for `serve` alone, and
lists the report host and port under Determinism as fixed values, so a report
must be reproducible without being told where a server happens to be running.

### Risk: 5
Most likely alternative reading: an environment variable or option that shifts
the printed address, which the spec never names.

---

## T50: `POST /` with a `catalog` field that is present but empty

### Spec Text
> `POST` | `/` | Accept form-encoded body; redirect to `/catalog/<value>` when `catalog` field is present, otherwise redirect to `/`

### Alternatives
1. An empty or blank value names no vault, so it takes the "otherwise" branch
   and redirects to `/`.
2. The field is present, so redirect literally to `/catalog/` and let that route
   deal with the empty name.

### Choice
Alternative 1. `/catalog/` is not one of the defined routes, and redirecting a
user to it would answer an empty form with an error page; treating a blank name
as no name keeps the form on screen.

### Risk: 25
The author's implementation may branch on the field's presence alone, in which
case an empty submission redirects to `/catalog/` and a fixture would see that
`Location`. Most likely alternative reading: redirect to `/catalog/`.

---

## T51: Is an unreadable catalog a "non-existent vault" to the viewer?

### Spec Text
> `Non-existent vault on any /catalog/<name> route` | Redirect to `/`; landing page shows vault-not-found indication; response must not be HTTP `500`

> `Any HTTP error` | Well-formed HTTP response; no raw exception or stack trace exposure

### Alternatives
1. Anything the viewer cannot show -- a missing directory, a catalog that will
   not parse, an unsupported `version`, an entry with no title -- is treated as
   a non-existent vault and redirects to `/`.
2. Only a missing directory redirects; a corrupt catalog is a different error,
   answered with `400` or a 500-free error page.

### Choice
Alternative 1. From the browser's side both mean "there is no vault to show
here", and the one rule the spec is firm about -- never a `500`, never a
traceback -- is easiest to keep with a single failure path.

### Risk: 10
Most likely alternative reading: a distinct error page for a corrupt catalog.
Both satisfy the stated constraints, so only a fixture pinning the status of a
deliberately corrupted vault would disagree.
