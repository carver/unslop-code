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

## T21. How `<source>/media/<entry_id>` is built from the stored `source`

### Spec Text
> | Media | `<source>/media/<entry_id>` | `<vault>/media/` | Filename contains entry `id` |

> Source URL | `https://media.example.com/channel/<source_id>`

### Alternatives
1. **Literal concatenation**: strip one trailing `/` from the stored `source` and append
   `/media/<entry_id>`, so a feed at `http://host/feed.json` yields
   `http://host/feed.json/media/a`.
2. **Relative resolution** (`urljoin`): treat the last path segment as a document name and
   replace it, yielding `http://host/media/a`.
3. **Strip a file-looking last segment** only when it contains a dot.

### Choice
Literal concatenation. The spec writes the template as `<source>/media/<entry_id>` with
`<source>` as a single opaque placeholder, and the one concrete source URL the spec gives
(`https://media.example.com/channel/<source_id>`) is a directory-shaped URL for which all
three readings agree. Readings 2 and 3 would silently rewrite a source the user typed.

### Risk: 25
Most likely alternative preferred by the author: the same literal concatenation; their
fixture server almost certainly serves a directory-shaped source, which hides the
difference entirely.

## T22. Which entries receive a preview download

### Spec Text
> Download phase | Retrieve media and preview files after metadata phase

> Candidate selection | Only entries without a corresponding media file in `<vault>/media/` are candidates

> `--episodes=<n>` | non-negative integer | Maximum number of episode **media** downloads

### Alternatives
1. **Previews follow the media candidates**: each selected candidate gets both its media
   and its preview file, so the per-category limit bounds preview downloads as well.
2. **Previews are independent**: every entry whose preview file is missing is fetched,
   regardless of the media limit.
3. Previews for every entry on every run.

### Choice
Reading 1. "Candidate selection" is stated once, for the download phase as a whole, and
the phase is described as retrieving "media and preview files" together. Reading 2 would
need its own candidate rule and its own limit, neither of which the spec provides, and
reading 3 re-downloads unchanged files on every sync.

### Risk: 35
Most likely alternative preferred by the author: previews driven by the presence of a file
in `<vault>/previews/` rather than by the media candidate list — the two differ whenever a
previous run stored the media but not the preview.

## T23. Deriving the media extension from `Content-Type`

### Spec Text
> Media extension without override | Derive from HTTP `Content-Type`

### Alternatives
1. **Standard MIME mapping** (`mimetypes.guess_extension`): `video/mp4` → `.mp4`,
   `image/jpeg` → `.jpg`, `audio/mpeg` → `.mp3`.
2. **Subtype as text**: take everything after the slash, so `image/jpeg` → `.jpeg` and
   `audio/mpeg` → `.mpeg`.

### Choice
The standard MIME mapping. "Derive from `Content-Type`" names a derivation rather than a
substring, and the platform's own mapping is the only derivation with a documented,
locale-independent result. Parameters (`; charset=...`) are stripped before lookup.

### Risk: 30
Most likely alternative preferred by the author: the subtype-as-text split, which is a
two-line implementation. The readings agree on `video/mp4`, `video/webm` and `image/png`,
and disagree on `image/jpeg` and `audio/mpeg`.

## T24. Unknown or missing `Content-Type` on a successful download

### Spec Text
> Successful HTTP download response | Any successful response is treated as downloadable
> content; implementations are not required to validate payload semantics beyond using
> `Content-Type` for extension derivation

### Alternatives
1. Store the file with a neutral `.bin` extension.
2. Store the file with no extension at all.
3. Treat the response as a failure.

### Choice
Reading 1. The response is explicitly "downloadable content", so it must be stored;
`.bin` keeps the filename rule ("contains entry `id`") intact and keeps the candidate
check (an entry with any media file is no longer a candidate) working. Reading 3
contradicts the rule outright.

### Risk: 20
Most likely alternative preferred by the author: storing the entry id with no extension.

## T25. What counts as a transient download failure, and how often it is retried

### Spec Text
> Permanent download failure | Warning to stderr; continue with remaining entries

> Transient download failure | Retry, then warn to stderr after retries exhausted; continue with remaining entries

### Alternatives
1. **Status-based split**: connection/timeout errors and the retryable statuses
   (`408`, `425`, `429`, `5xx`) are transient; every other unsuccessful status
   (`404`, `403`, `410`, ...) is permanent and is not retried.
2. **Retry everything** a fixed number of times, treating "permanent" only as a label for
   the message.
3. Retry only transport errors, treating every HTTP status as permanent.

### Choice
Reading 1 with three attempts. The spec contrasts the two cases precisely by whether a
retry happens, and the conventional HTTP reading of that contrast is "4xx is the server
telling you not to come back, 5xx and transport errors are not".

### Risk: 15
Most likely alternative preferred by the author: the same split, possibly with a different
attempt count. Observable behavior (a warning per entry, exit code `0`, other entries
still downloaded) is identical under every reading.

## T26. Local filename for a downloaded asset

### Spec Text
> | Media | ... | `<vault>/media/` | Filename contains entry `id` |

> Media extension with override | Use override string as extension

### Alternatives
1. `<entry_id>.<extension>`.
2. A name that merely contains the id, such as `<entry_id>-<title>.<extension>`.

### Choice
`<entry_id>.<extension>`. It satisfies "contains entry `id`", makes "extension = format
string" exactly true, and is the only shape under which the candidate check ("entries
without a corresponding media file") can be evaluated from the directory listing alone.

### Risk: 10
Most likely alternative preferred by the author: the same `<id>.<ext>` shape; the wording
"contains" suggests their own tests assert containment rather than equality.

## T27. Shape of the `--format` value

### Spec Text
> `--format=<str>` | string | Override media download format and output extension

### Alternatives
1. The value is a bare extension (`mp4`); it is appended to the remote path after a dot
   and used as the stored extension after a dot.
2. The value may include a leading dot (`.mp4`), which would produce `a..mp4`.

### Choice
Reading 1, with any leading dots stripped from the value first, so `mp4` and `.mp4` behave
the same. The spec's own template writes the dot itself (`<entry_id>.<format>`), so the
value is the format name, not the suffix.

### Risk: 10
Most likely alternative preferred by the author: the same bare-extension reading, without
the leading-dot tolerance (which only differs for input the spec's template never intends).

## T28. `digest` entry order inside a group

### Spec Text
> Entry order within group | Deterministic

> Download candidate order | Same as catalog order within category

### Alternatives
1. Catalog order — the order the entries appear in `catalog.json`.
2. Sorted by `id`, or by title.

### Choice
Catalog order. It is the order the spec names everywhere else it has to fix one, it is
deterministic for any given file, and it keeps the digest consistent with how the same
catalog is read elsewhere.

### Risk: 20
Most likely alternative preferred by the author: the same catalog order; "deterministic"
without a named key most plausibly means "whatever order you read them in, don't shuffle".

## T29. A `removed` history whose only value is `true`

### Spec Text
> Removals | Latest `removed` value is `true` and prior `removed` value, **if present**, is `false`

### Alternatives
1. A single `true` entry qualifies as a removal (the prior value is simply not present).
2. A prior `false` is required, so a single `true` qualifies as nothing.

### Choice
Reading 1. "If present" exists precisely to make the prior-value condition vacuous when
there is no prior value; without that reading the phrase would be redundant. Such an entry
also matches the additions rule, which is why the precedence table puts removals first.

### Risk: 25
Most likely alternative preferred by the author: the same reading — the clause is hard to
explain otherwise — but a catalog produced by `sync` never contains this shape, so the
author's fixture would have to be hand-written to reach it.

## T30. How reappearance is indicated

### Spec Text
> Field-update suffix | Changed field names in parentheses after title

> Reappearance after removal (v3 only) | Indicate reappearance alongside any other changed fields

### Alternatives
1. The parenthesised list carries the word `reappeared` in place of the `removed` field
   name, e.g. `title-a (reappeared, views)`.
2. A separate marker outside the parentheses, e.g. `title-a [reappeared] (views)`.
3. The raw field name `removed` in the list, leaving the reader to infer direction.

### Choice
Reading 1. "Alongside any other changed fields" places the indication in the same list as
the changed fields, and `reappeared` states the direction, which the bare field name
`removed` would get backwards for a value that just went back to `false`.

### Risk: 35
Most likely alternative preferred by the author: listing the field as `removed` like any
other changed tracked field. The exact wording is not fixed by the spec, so any test
asserting it would be asserting the author's own phrasing.

## T31. Whether `removed` is a tracked field for v3 additions and field updates

### Spec Text
> Additions | Entry has only initial observations; no tracked field has a second history entry

> Field updates | At least one tracked field has two or more history entries and the latest two values differ

> Additions | ... | Same rule applied to **available** tracked fields

### Alternatives
1. `removed` is one of the six tracked fields for v3, so it participates in both rules.
2. Only the five source-fed fields count; `removed` feeds removal detection alone.

### Choice
Reading 1. The v1/v2 column says the same rule applies to the *available* tracked fields,
which is only a meaningful qualification if v3 has one more of them — `removed`. It is
also what makes the reappearance row reachable: an entry that only came back has no other
changed field to report.

### Risk: 20
Most likely alternative preferred by the author: the same reading; it is the one that makes
the "available" wording and the reappearance row consistent.

## T32. Classification behind the post-sync counts

### Spec Text
> Counts reported | Added, removed, updated

> Wording | Unspecified

### Alternatives
1. Each entry contributes to at most one count, using the digest precedence: an entry
   newly created counts as added, an entry that just went `removed: true` counts as
   removed, any other entry with an appended tracked value counts as updated (so a
   reappearance counts as an update).
2. Independent counters, where one entry may be counted twice.
3. Counting appended history keys rather than entries.

### Choice
Reading 1. The spec presents the three counts as a summary of the same change
classification `digest` uses, and "Each entry may appear once" is the stated rule there.
Counting entries rather than history keys is what makes the numbers comparable to the
digest's lists.

### Risk: 20
Most likely alternative preferred by the author: the same per-entry counting; the most
likely disagreement is whether a reappearance is counted as an update or not at all.

## T33. `--skip-metadata` on a v1 or v2 vault

### Spec Text
> `--skip-metadata` | flag | Skip source fetch and metadata update; run download phase against existing vault state

> Because `sync` auto-migrates v1 and v2 vaults to v3 during the metadata phase, the
> download phase always operates against a v3 catalog. The source URL for downloads is
> the migrated `source` value.

### Alternatives
1. The legacy catalog is still read through the v3 conversion in memory — so downloads use
   the derived/preserved `source` — but nothing is written, because the metadata phase
   (which persists) was skipped.
2. `--skip-metadata` also skips the conversion, leaving the download phase without a usable
   `source` for a v1 vault.
3. The migration is persisted even though the metadata phase was skipped.

### Choice
Reading 1. "Run download phase against existing vault state" describes what the downloads
read, and the download phase is defined to operate against a v3 catalog with the migrated
`source`. Reading 3 would write `catalog.json` during a run whose whole point is not to.

### Risk: 15
Most likely alternative preferred by the author: the same in-memory conversion; the
disagreement would only show as whether `catalog.json` is rewritten by a
`--skip-metadata` run on a legacy vault.

## T34. Whether removed entries are download candidates

### Spec Text
> Candidate selection | Only entries without a corresponding media file in `<vault>/media/` are candidates

### Alternatives
1. Every catalog entry is considered, including entries whose latest `removed` value is
   `true`.
2. Entries currently marked removed are excluded.

### Choice
Reading 1. The candidate rule is stated as an exhaustive "only ..." condition and names
just one criterion; the spec never ties the download phase to `removed`. An entry that
vanished upstream is also exactly the one a local archive most wants a copy of, though the
fetch will usually fail and be reported as a download failure.

### Risk: 30
Most likely alternative preferred by the author: skipping removed entries, since fetching
media for content known to be gone looks wasteful in an implementation that has the flag
at hand.

## T35. Creating `<vault>/media/` and `<vault>/previews/`

### Spec Text
> | Media | ... | `<vault>/media/` | ... |

> | Preview | ... | `<vault>/previews/` | ... |

### Alternatives
1. Both directories are created whenever the download phase runs, even if it downloads
   nothing.
2. Each directory is created lazily, on the first file that lands in it.

### Choice
Reading 1. The candidate rule has to read `<vault>/media/` on every download phase, so the
directory is part of the phase's working state rather than a side effect of a successful
download; creating both up front keeps the vault layout uniform.

### Risk: 10
Most likely alternative preferred by the author: either reading; a test that asserts on
directory contents rather than existence cannot tell them apart.

## T36. Where the viewer keeps its list of recent vaults

### Spec Text
> Persistence | Later browser session from same browser must still show visited vault

> Trigger | Navigation to any vault through viewer

### Alternatives
1. **Browser-side**: a persistent cookie (or `localStorage`) holds the list, so the list belongs to one browser profile and a different browser starts empty.
2. **Server-side**: the server stores the list next to the vaults it serves (`.mvault-recent.json` in its working directory), so any client of that server sees the same list.

### Choice
Server-side, in `.mvault-recent.json` in the directory `serve` runs in. The spec's only hard requirement is that a *later* session still shows the vault; the "same browser" wording describes the situation the requirement is tested in, not an isolation guarantee. A server-side file satisfies the requirement for every client, including a browser that cleared its cookies, and it keeps the landing page renderable without client state. A cookie-based list would also pass every requirement listed, but only if the test client replays cookies.

### Risk: 30
Most likely alternative preferred by the author: a persistent cookie, which would differ on a test that asserts a brand-new client (no cookies) sees an empty recent-vaults area after another client visited a vault.

## T37. Which requests count as "navigation to a vault"

### Spec Text
> Trigger | Navigation to any vault through viewer

### Alternatives
1. **Every `/catalog/<name>...` request that resolves a real vault**, including the bare `/catalog/<name>` redirect and the entry route.
2. **Only rendered listing pages** (`/catalog/<name>/<category>`), since a redirect is not yet a visit.
3. Every `/catalog/<name>` request, a missing vault included.

### Choice
Every `/catalog/<name>...` request that successfully resolves a vault. "Navigation to any vault through viewer" reads as reaching the vault at all, and the bare `/catalog/<name>` URL is exactly the link the landing page and `serve <name>` use, so a visit through it must register. A vault that could not be resolved is not recorded, because the user never reached a vault.

### Risk: 15
Most likely alternative preferred by the author: recording only on the listing page, which differs for a client that requests `/catalog/<name>` without following the redirect.

## T38. Invalid category: redirect or status code

### Spec Text
> Invalid category on `GET /catalog/<name>/<category>` for v1 vault | Redirect to `/catalog/<name>/entries` or return HTTP `400`/`404`

### Alternatives
1. Redirect to the vault's default category page.
2. Answer `400` or `404`.

### Choice
Redirect to the default category page. The spec names it first and it leaves the viewer usable after a mistyped URL; both readings are explicitly conforming, so a conforming test has to accept either.

### Risk: 5
Most likely alternative preferred by the author: a `404`, which only matters for a test that pins one of the two permitted answers.

## T39. How the landing page learns that a vault was not found

### Spec Text
> Non-existent vault on any `/catalog/<name>` route | Redirect to `/`; landing page shows vault-not-found indication; response must not be HTTP `500`

### Alternatives
1. Redirect to `/?missing=<name>` and render the indication from the query string.
2. Redirect to exactly `/` and carry the name in a short-lived cookie the landing page consumes.
3. Redirect to exactly `/` and keep the pending notice in server memory.

### Choice
Redirect to exactly `/`, with the vault name in a short-lived cookie that the landing page displays and clears; the landing page also honours a `missing=<name>` query parameter, so a client that is handed the name either way sees the indication. The spec says "Redirect to `/`", and a `Location` of exactly `/` is what a test comparing the header literally expects, while the cookie keeps the indication working for any client that follows the redirect normally.

### Risk: 25
Most likely alternative preferred by the author: `/?missing=<name>`, which differs for a test that asserts on the `Location` header text or that requests `/` with a client that drops cookies.

## T40. `/catalog/<name>/<category>/<id>` for an id that is not in the category

### Spec Text
> `GET` | `/catalog/<name>/<category>/<id>` | HTML response for that viewer link target; may reuse the category listing page with the entry highlighted or otherwise surfaced

### Alternatives
1. `404`, because the entry does not exist.
2. `200` with the ordinary category listing and nothing highlighted.

### Choice
`200` with the listing. The route is defined as "HTML response for that viewer link target" and is explicitly allowed to be the listing page; an id that no longer exists (an entry dropped from a rewritten catalog, a stale link in an old digest) then still lands the reader on the right category instead of an error page.

### Risk: 30
Most likely alternative preferred by the author: `404` for an unknown id, which differs on any request for an id the category does not contain.

### Note (resolved)
The detail-page spec settles this: "Missing entry in specified category | HTTP `404`, or redirect to category listing with error indication". The `200`-with-listing answer is no longer conforming, and the route now answers `404`. See [T55](#t55-missing-entry-in-the-named-category-404-or-redirect).

## T41. Which files in `<vault>/media/` make an entry "downloaded"

### Spec Text
> Downloaded state (v2/v3) | Entry counts as downloaded when a media filename in `<vault>/media/` contains entry `id`

### Alternatives
1. Every name directly inside `<vault>/media/`, taken literally as a substring test.
2. Only finished downloads, excluding the `.part` files the download phase writes while a transfer is in flight.
3. A recursive walk of `<vault>/media/`.

### Choice
Every name directly inside `<vault>/media/`, with `id` tested as a plain substring of the file name. The spec states the rule as containment of the id in "a media filename in `<vault>/media/`" and says nothing about partial files or nested directories, and the download phase itself only ever writes into that one directory.

### Risk: 25
Most likely alternative preferred by the author: reusing the download phase's own rule, which ignores `.part` files and would show an in-flight entry as undownloaded.

### Note (confirmed)
The detail-page spec restates the same rule for media playback — "a saved filename in `<vault>/media/` contains the entry `id`" — so the plain-substring reading now governs both the listing badge and the detail page's media reference.

## T42. Changed-entry lines in the post-sync summary

### Spec Text
> Post-sync summary | Each changed-entry line includes viewer link on same line as title

### Alternatives
1. The summary keeps its counts line only, and the requirement is vacuous until an entry line exists.
2. The summary grows a per-entry section — the counts line, then the changed entries grouped by change kind, each line carrying the entry's current title and its viewer link.

### Choice
Grow a per-entry section, laid out like the `digest` report (category heading, change-kind heading, one `    - <title> <link>` line per entry) and printed after the existing counts line. The requirement presupposes that changed-entry lines exist and that each carries a title, so the summary has to name entries; keeping the counts line first preserves the previously specified summary exactly.

### Risk: 35
Most likely alternative preferred by the author: a flatter layout (for example one line per entry with no category or change-kind headings), which differs for a test that asserts on the surrounding lines rather than on the entry line itself.

## T43. Which entries get a post-sync changed-entry line

### Spec Text
> Post-sync summary | Each changed-entry line includes viewer link on same line as title

### Alternatives
1. The entries behind the run's added/removed/updated counts - one line per entry the run actually counted as a change.
2. Every entry the source returned.
3. `digest`-style classification of the whole catalog after the sync, which also reports entries changed by earlier runs.

### Choice
The entries behind this run's counts. The summary reports one sync run, its counts already define what "changed" means for that run, and listing anything else would contradict the counts printed directly above the lines.

### Risk: 20
Most likely alternative preferred by the author: a digest-style pass over the catalog after the sync, which additionally lists entries whose last change came from an earlier run.

## T44. Host and port of the links in `digest` and the post-sync summary

### Spec Text
> Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>`

> Default scheme | `http://` — Default host | `127.0.0.1` — Default port | `8840`

### Alternatives
1. `digest` and `sync` take their own `--host`/`--port` options that move the link target.
2. Reports always use the documented defaults; only `serve` has `--host`/`--port`, and they change the bind address only.

### Choice
Reports always use the defaults. The syntax table gives `--host`/`--port` to `serve` alone, and no other command's syntax is restated with them, so the "default" wording in the link table describes what the reports always emit.

### Risk: 10
Most likely alternative preferred by the author: report commands accepting the same overrides, which differs only if a test passes `--host`/`--port` to `digest` or `sync`.

## T45. `POST /` with a present but empty `catalog` field

### Spec Text
> `POST` | `/` | Accept form-encoded body; redirect to `/catalog/<value>` when `catalog` field is present, otherwise redirect to `/`

### Alternatives
1. Redirect to `/catalog/` because the field is literally present.
2. Treat an empty value like a missing field and redirect to `/`.

### Choice
Redirect to `/`. `/catalog/` names no vault and could only bounce back to `/` anyway, so an empty submission - the form submitted with nothing typed in it - is handled as "no vault requested".

### Risk: 30
Most likely alternative preferred by the author: a literal presence test, redirecting to `/catalog/` and letting the missing-vault rule take over from there.

## T46. The vault name inside a viewer link

### Spec Text
> Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>`

### Alternatives
1. The `<name>` argument exactly as it was typed on the command line.
2. The vault directory's base name, so a path like `vaults/v` links as `v`.

### Choice
The argument as typed. `<name>` is the same placeholder the command syntax uses, and the viewer resolves vaults relative to its own working directory in the same way the CLI does, so the typed name is what round-trips.

### Risk: 10
Most likely alternative preferred by the author: the same choice; the two only differ when a vault is named through a path, which no route in the spec supports.

## T47. A vault whose catalog cannot be read

### Spec Text
> Non-existent vault on any `/catalog/<name>` route | Redirect to `/`; landing page shows vault-not-found indication; response must not be HTTP `500`

### Alternatives
1. Only a missing directory is "non-existent"; unreadable or unsupported catalogs are a server error.
2. Any vault the viewer cannot read - missing, malformed JSON, missing fields, or an unsupported version - is handled exactly like a non-existent vault.

### Choice
Handle every unreadable vault like a non-existent one. The spec forbids a `500` and forbids exposing raw exceptions anywhere in the viewer, and a malformed catalog is indistinguishable from a missing one from the reader's point of view.

### Risk: 20
Most likely alternative preferred by the author: a `400`/`404` error page for a malformed catalog, which differs in status and in whether the vault-not-found indication appears.

## T48. When and how `serve` opens the browser

### Spec Text
> `serve` without `<name>` | Start server and open browser to `/`

> `serve <name>` | Start server and open browser to default category page for vault

### Alternatives
1. Open `/catalog/<name>` and let the redirect carry the browser to the default category page.
2. Resolve the vault's version up front and open the resolved default category page directly.

### Choice
Resolve up front and open the resolved URL (`/catalog/<name>/entries` or `/catalog/<name>/episodes`), falling back to `/catalog/<name>` when the vault cannot be read. The spec says the browser is opened *to the default category page*, which the resolved URL is literally. The browser is launched from a background thread after the socket is bound, so a browser command that does not return immediately cannot stop the server from serving.

### Risk: 20
Most likely alternative preferred by the author: opening `/catalog/<name>` and relying on the redirect, which differs for a test that records the URL handed to the browser.

### Note
Both readings put the browser on the same page; they differ only in the URL string the browser receives.

## T49. How the entry route surfaces its entry

### Spec Text
> ... may reuse the category listing page with the entry highlighted or otherwise surfaced

### Alternatives
1. A dedicated single-entry page.
2. The category listing with the requested entry marked.

### Choice
The category listing with the requested entry marked (a `selected` class and a marker on that row), which the spec names as an acceptable implementation and keeps one page to render and one set of listing rules to honour.

### Risk: 5
Most likely alternative preferred by the author: a dedicated entry page, which would only differ for a test that asserts the other entries are absent.

### Note (resolved)
The detail-page spec settles this: the route is an "Entry detail page for matching entry" carrying that entry's metadata, charts, media and back navigation. The listing-with-selection page is gone, along with the `selected` marker it used.

## T50. How many recent vaults the landing page keeps

### Spec Text
> Ordering | Most recently visited first

> Empty state | Area may be empty or absent

### Alternatives
1. Unbounded.
2. A fixed cap on the most recent handful.

### Choice
Keep the most recent 20 and drop older ones. Nothing in the spec requires a vault to be remembered forever, and an unbounded list would grow without limit on a long-lived viewer; 20 is far beyond the entries any ordering test needs.

### Risk: 10
Most likely alternative preferred by the author: an unbounded list, which differs only for a test that visits more than twenty vaults.

## T51. Container and key names of the embedded chart payload

### Spec Text
> Embedding style | Machine-readable structured data embedded in HTML

> Payload container and key names | Unspecified as long as the payload remains machine-readable

### Alternatives
1. One JSON document for the whole entry, in a single `<script type="application/json">` element.
2. One JSON document per charted field, in one `<script>` element each.
3. Per-point HTML markup - a `<li data-timestamp="..." data-value="...">` list, or `data-` attributes on the drawn chart element.

### Choice
One `<script id="chart-data" type="application/json">` element holding `{"views": [...], "likes": [...]}`, where each point is `{"timestamp": "<ISO 8601>", "value": <number or null>}`. The spec asks for structured, machine-readable data and explicitly frees the naming, so the reading that survives the widest range of readers is a single well-known JSON media type carrying both fields at once: one `json.loads` of the one script element yields both charts, their order and their nulls. `<` is written as its `\u003c` escape inside the payload, so no recorded value can close the element it sits in.

### Risk: 20
Most likely alternative preferred by the author: one payload per field, or point objects keyed `t`/`v` (or two-element arrays), which differs for any test that reaches into the payload by name rather than searching it.

## T52. Whether a single-point history is left out of the payload as well

### Spec Text
> Single-point history | Chart for that field may be omitted

> Point payload | Preserve timestamp/value pairing; `likes` may use `null`; no filtering or replacement

### Alternatives
1. Omit the field entirely - no drawing and no data - when its history holds one point.
2. Keep the data and omit only the drawing, so the payload always carries both fields.

### Choice
Keep the data, omit only the drawing. The permission is granted to "the chart", and a polyline through one point is what there is nothing to draw; the payload rule directly above it forbids filtering points out, and a payload whose field set depends on history length is the harder one for a reader to consume. "Missing downloaded media | Keep metadata and chart data visible" likewise treats the data as the thing that stays.

### Risk: 15
Most likely alternative preferred by the author: dropping the field from the payload too, which differs for a test that asserts the payload has no `views` key when `views` holds a single point.

## T53. A stored `source` that ends in a slash

### Spec Text
> v2 | `<source>/entry/<id>`

> v3 | `<source>/entry/<id>`

### Alternatives
1. Concatenate literally, so a `source` of `https://host/channel/c/` yields `https://host/channel/c//entry/a`.
2. Strip trailing slashes from `source` first.

### Choice
Strip trailing slashes. The download phase already reads the stored `source` that way when it builds asset URLs, so one vault resolves its source the same way everywhere, and a doubled slash is not a URL any source platform would serve. The two readings agree for every `source` without a trailing slash, which is what `init` records.

### Risk: 20
Most likely alternative preferred by the author: literal concatenation, which differs only for a fixture whose `source` ends in `/`.

## T54. Several saved media files containing the same entry id

### Spec Text
> Downloaded media discovery | A downloaded media file counts as matching the entry when a saved filename in `<vault>/media/` contains the entry `id`; the detail page uses that exact filename in the media static endpoint URL

### Alternatives
1. The first match in directory order, whatever the filesystem happens to return.
2. The first match in sorted order.
3. Prefer an exact `<id>.<ext>` match, falling back to a containing name.

### Choice
The first match in sorted order. "Deterministic for same vault and entry" is the standard the Determinism table holds the page to, and directory order is not deterministic across filesystems; sorting is the cheapest rule that is. The three readings agree whenever a vault holds one file per entry, which is all the download phase ever writes.

### Risk: 10
Most likely alternative preferred by the author: directory order, which differs only for a vault holding two media files that both contain the same id.

## T55. Missing entry in the named category: 404 or redirect

### Spec Text
> Missing entry in specified category | HTTP `404`, or redirect to category listing with error indication

### Alternatives
1. `404` with an error page.
2. A redirect to `/catalog/<name>/<category>` carrying an error indication.

### Choice
`404`. The spec names it first and it needs no channel for carrying the indication across the bounce; a reader who asked for one entry is told plainly that it is not there. This also covers the id that exists in a different category, which the lookup rules require not to resolve.

### Risk: 5
Most likely alternative preferred by the author: the same choice, since both are explicitly allowed and a conforming test has to accept either.

## T56. Content type of a stored file whose name does not reveal one

### Spec Text
> `GET` | `/vault/<name>/media/<file>` | Serve `<vault>/media/<file>` with an appropriate media MIME type

> `GET` | `/vault/<name>/preview/<id>` | Serve the matching preview image from `<vault>/previews/` ... with an appropriate image MIME type

### Alternatives
1. One fixed type per endpoint - always `video/mp4` for media, always `image/jpeg` for previews.
2. Guess from the saved file's extension, with a per-endpoint fallback when the extension says nothing.
3. Store the type at download time and serve it back.

### Choice
Guess from the saved extension, falling back to `application/octet-stream` for media and `image/jpeg` for previews. The download phase derives each saved extension from the asset's own `Content-Type`, so the extension is the type the source declared, and a vault holding `.mp4` and `.webm` files should not have both served as one type. The fallbacks keep each endpoint's answer in the family the spec names. Nothing in the vault format stores a type, so reading one back is not available.

### Risk: 25
Most likely alternative preferred by the author: a fixed type per endpoint, which differs for any saved file whose extension is absent, unknown, or names a different type from the fixture's expectation.

## T57. Whether the detail page shows the stored preview image

### Spec Text
> `GET` | `/vault/<name>/preview/<id>` | Serve the matching preview image from `<vault>/previews/` whose saved filename contains `<id>`

> Media playback reference | Use media static endpoint when downloaded media file exists

### Alternatives
1. Show nothing from `previews/`; the endpoint exists only for direct requests.
2. Show the preview image when the vault holds one, as an `<img>` pointing at the preview endpoint.

### Choice
Show it when the vault holds one. The page-content table does not list a preview, but it does not forbid one either, and an entry page that shows the vault's media but hides the vault's still image of the same entry leaves the preview endpoint reachable only by hand. The image is left out entirely when no preview file matches, so the page never points at a `404`.

### Risk: 12
Most likely alternative preferred by the author: no preview on the page, which differs only for a test asserting the detail page references nothing under `/vault/<name>/preview/`.

## T58. What "non-existent vault" means on a static route

### Spec Text
> Non-existent vault on detail or static route | Redirect to landing page with vault-not-found indication

### Alternatives
1. Only a missing directory counts; a directory whose `catalog.json` is broken still serves its files.
2. Any vault the viewer cannot read as a vault - missing, malformed, or of an unsupported version - is treated as non-existent, on static routes as well.

### Choice
Any vault the viewer cannot read, which is the rule [T47](#t47-a-vault-whose-catalog-cannot-be-read) already applies to `/catalog` routes. One definition of "the vault is not there" across every route is what keeps the landing page's indication meaningful, and a directory the viewer cannot describe is not a vault it should be serving files out of.

### Risk: 18
Most likely alternative preferred by the author: a directory-existence test on the static routes, which differs for a request for a stored file in a vault whose catalog is unreadable.

## T59. How the detail page references playable media, published dates and dimensions

### Spec Text
> Media playback reference | Use media static endpoint when downloaded media file exists

> Published date | Displayed — Dimensions | Display width and height

### Alternatives
1. A plain `<a href>` to the media endpoint.
2. An embedded player element whose `src` is the media endpoint.
3. For the metadata: reformat the values for display (date-only published text, `1920x1080`) or print them as stored.

### Choice
A `<video controls>` whose `src` is the media endpoint - the spec calls it a "playback reference", which a player element is and a download link is not. `published` is printed exactly as the catalog stores it, and the dimensions as `<width> × <height>`, because the stored text is what a test comparing against the fixture has in hand and a reformatted date could only lose information.

### Risk: 20
Most likely alternative preferred by the author: the same media endpoint under a different element, and `1920x1080` for the dimensions, which differs for a test asserting one exact dimension string rather than the two numbers.

## T60. How the static endpoints refuse a traversal sequence

### Spec Text
> Path traversal | Requests containing traversal sequences must not escape `media/` or `previews/`

> Path traversal attempt | HTTP `403` or HTTP `404`

### Alternatives
1. Detect traversal syntactically - reject a `<file>` containing `..` or a separator - and answer `403`.
2. Resolve the path and compare it against the asset directory, answering `403` when it falls outside.
3. Serve only names the asset directory itself lists, so a traversal sequence simply matches nothing and gets the ordinary `404`.

### Choice
Serve only names the directory lists. A `<file>` is one path segment matched against the directory's own listing, so `..%2Fcatalog.json`, `../../secret` and any encoding of them resolve to no file at all rather than to a file to be refused - there is no path to escape with. The spec permits `404` for a traversal attempt, and this makes the guarantee structural instead of a blocklist that a new encoding could slip past.

### Risk: 5
Most likely alternative preferred by the author: an explicit syntactic check answering `403`, which differs only for a test that requires `403` specifically rather than either allowed status.
