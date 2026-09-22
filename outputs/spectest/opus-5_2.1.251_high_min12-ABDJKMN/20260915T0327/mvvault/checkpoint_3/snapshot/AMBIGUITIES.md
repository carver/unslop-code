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

---

## T21. Building media and preview URLs from the `source` value

### Spec Text
> | Media | `<source>/media/<entry_id>` | `<vault>/media/` | Filename contains entry `id` |

> | Preview | `<source>/preview/<entry_id>` | `<vault>/previews/` | Filename contains entry `id` |

### Alternatives
1. Literal string concatenation: take the stored `source` verbatim and append
   `/media/<id>`, so a `source` of `http://host/source.json` yields
   `http://host/source.json/media/e1`.
2. Treat `source` as a document URL and resolve the asset paths against its
   parent directory (`urllib.parse.urljoin`), yielding
   `http://host/media/e1`.
3. Concatenate, but first strip a trailing `/` so a `source` of
   `http://host/` does not produce a doubled separator.

### Choice
Alternative 1 plus the trailing-slash guard from 3: `source.rstrip("/") +
"/media/" + id`. The spec writes the remote path as a template with `<source>`
substituted literally, and nothing in the spec mentions relative-URL
resolution; `urljoin` would silently discard the last path segment of every
`source` that names a file.

### Risk: 20
Author most likely prefers: the same literal concatenation; a `urljoin`-based
implementation differs on every `source` that ends in a filename, which is the
shape `init` fixtures normally use.

---

## T22. Deriving the media extension from `Content-Type`

### Spec Text
> | Media extension without override | Derive from HTTP `Content-Type` |

### Alternatives
1. Use Python's `mimetypes.guess_extension`, whose answers vary by
   interpreter version (`image/jpeg` has historically mapped to both `.jpe`
   and `.jpg`).
2. Use an explicit table for the common media/image types with a
   `mimetypes` fallback and a final default for unknown or missing headers.
3. Use the subtype text after the slash verbatim (`video/mp4` -> `mp4`,
   `image/jpeg` -> `jpeg`).

### Choice
Alternative 2, with `image/jpeg` -> `jpg`, `audio/mpeg` -> `mp3`,
`video/mp4` -> `mp4`, `image/png` -> `png`, and `bin` when the header is
missing or unrecognized. Parameters after `;` are ignored. This is the
mapping a human would call "derived from `Content-Type`", and it is stable
across interpreter versions.

### Risk: 35
Author most likely prefers: the same table for `video/mp4` and `image/jpeg`
(the types a fixture would actually serve); the readings diverge on
`image/jpeg` (`jpg` vs `jpeg`) and on unknown types (`bin` vs no extension).

---

## T23. Extension of downloaded preview files

### Spec Text
> | Preview | `<source>/preview/<entry_id>` | `<vault>/previews/` | Filename contains entry `id` |

(The "Media extension" rows of Download Rules mention only media.)

### Alternatives
1. Previews get no extension: the file is named exactly `<entry_id>`.
2. Previews derive their extension from `Content-Type`, the same way media
   does without an override.
3. Previews always use a fixed extension such as `.jpg`.

### Choice
Alternative 2. The only extension-derivation rule the spec states is
`Content-Type`-based, and applying it uniformly keeps the single stated
filename requirement ("filename contains entry `id`") true. The `--format`
override is described as a *media* download format, so it is not applied to
previews.

### Risk: 40
Author most likely prefers: the same `Content-Type` derivation; a test that
asserts an exact preview filename would fail an implementation that writes a
bare `<entry_id>`, and vice versa. Any test that only asserts the id appears
in the filename passes either way.

---

## T24. Whether previews follow media candidate selection and limits

### Spec Text
> | Candidate selection | Only entries without a corresponding media file in `<vault>/media/` are candidates |

> | Per-category limit | Download first `N` candidates in candidate order |

### Alternatives
1. Candidate selection and the per-category limit choose entries; each chosen
   entry gets both its media and its preview downloaded.
2. Previews are selected independently, by the presence of a file in
   `<vault>/previews/`, and are not subject to `--episodes`/`--streams`/
   `--clips`.
3. Previews are downloaded for every catalog entry on every run.

### Choice
Alternative 1. The spec defines exactly one candidate notion, keyed on the
media directory, and one limit per category; `--episodes=<n>` is described as
"Maximum number of episode media downloads", which implies the selected set is
a set of entries whose media is fetched, with the preview riding along.

### Risk: 30
Author most likely prefers: the same entry-level selection; the readings
diverge when a media file already exists but its preview does not (choice 1
re-downloads nothing, choice 2 still fetches the preview).

---

## T25. Are removed entries download candidates?

### Spec Text
> | Candidate selection | Only entries without a corresponding media file in `<vault>/media/` are candidates |

> | Candidate order | Catalog order within category |

### Alternatives
1. Every catalog entry is considered, including entries whose latest `removed`
   value is `true`.
2. Entries currently marked removed are excluded from candidacy, since their
   media is no longer expected to be available.

### Choice
Alternative 1. The stated candidate filter is exactly one condition — absence
of a local media file — and the spec elsewhere treats vanished remote content
as a per-entry warning (`Permanently unavailable content during download` ->
warning, exit `0`) rather than something to pre-filter.

### Risk: 25
Author most likely prefers: the same single filter; the readings diverge on a
vault holding removed entries, where excluding them shifts which entries a
per-category limit selects.

---

## T26. Transient vs. permanent download failure, and the retry budget

### Spec Text
> | Permanent download failure | Warning to stderr; continue with remaining entries |

> | Transient download failure | Retry, then warn to stderr after retries exhausted; continue with remaining entries |

### Alternatives
1. Classify by HTTP status: `4xx` is permanent (no retry), `5xx` and
   transport-level errors (timeout, connection reset) are transient.
2. Retry everything a fixed number of times, treating the distinction as
   descriptive only.
3. Treat only specific codes (`404`, `410`) as permanent and retry all others.

### Choice
Alternative 1, with three total attempts (two retries) and no sleep between
them. A `4xx` other than `408`/`429` cannot be fixed by repeating the request,
which is the ordinary meaning of "permanent"; `408` and `429` are grouped with
`5xx` as transient. The retry count is unspecified, so the smallest number
that is still observably "retry" behavior is used, and zero backoff keeps a
failing sync fast.

### Risk: 30
Author most likely prefers: the same 4xx/5xx split; a test that serves `503`
and counts requests would pass for any count above one, but a test that
asserts an exact attempt count (commonly `3`, sometimes `2`) could differ.

---

## T27. When the metadata save happens relative to the download phase

### Spec Text
> | Persistence boundary | Metadata changes must be durably saved before successful sync returns, including runs with download failures |

> | Save timing | Metadata phase persists before successful `sync` returns |

### Alternatives
1. Save at the end of the metadata phase, before any download is attempted.
2. Save after the download phase completes, on the way out of a successful run.

### Choice
Alternative 1. Both readings satisfy the literal wording, but saving first is
the only one that also survives an interruption during downloads, and the
phase table describes the metadata phase as ending with "persist metadata"
before the "Download phase" row. Either way the catalog is on disk when a run
with download failures returns `0`.

### Risk: 8
Author most likely prefers: the same save-before-download ordering; the
readings are indistinguishable from outside a completed run.

---

## T28. `--skip-metadata` on a v1 or v2 vault

### Spec Text
> | `--skip-metadata` | flag | Skip source fetch and metadata update; run download phase against existing vault state |

> Because `sync` auto-migrates v1 and v2 vaults to v3 during the metadata
> phase, the download phase always operates against a v3 catalog. The source
> URL for downloads is the migrated `source` value.

### Alternatives
1. `--skip-metadata` skips the fetch, the history update, and the save, but the
   catalog is still read through the version-aware loader, so a v1/v2 vault is
   migrated **in memory** and downloads use the migrated `source`. Nothing is
   written.
2. `--skip-metadata` also skips migration, so a legacy vault cannot supply a
   download source and the run errors out.
3. `--skip-metadata` still persists the migration (a write, despite "skip
   metadata update").

### Choice
Alternative 1. "Skip source fetch and metadata update" names two things, and
loading is neither; the downloads paragraph states unconditionally that the
download phase operates against a v3 catalog with the migrated `source`. Not
writing keeps the flag from having a persistence side effect the spec never
mentions.

### Risk: 22
Author most likely prefers: the same in-memory migration; an implementation
that persists would leave a v3 `catalog.json` and a `catalog.bak` behind after
a `--skip-metadata` run, which a fixture could detect.

---

## T29. What the post-sync summary counts, and how it is worded

### Spec Text
> | Trigger | Successful `sync` run that includes metadata phase |

> | Counts reported | Added, removed, updated |

> | Wording | Unspecified |

### Alternatives
1. Counts describe the changes this run made: entries created, entries newly
   flipped to `removed: true`, and entries that had at least one tracked-field
   value change — with each entry counted in exactly one bucket, using the
   `digest` precedence (removed > added > updated).
2. Each entry may be counted in several buckets (a newly removed entry that
   also changed its title counts as both removed and updated).
3. Counts restate the whole `digest` classification over the entire catalog
   history rather than this run's changes.

### Choice
Alternative 1. The summary follows a `sync`, so "added/removed/updated" most
naturally describes what that `sync` did, and the `digest` section already
establishes "Each entry may appear once" as this spec's grouping convention.
The line is printed on every metadata-phase run, including one where all three
counts are zero.

### Risk: 30
Author most likely prefers: the same per-run counting; the readings diverge
only for an entry that is removed and whose other fields also changed in the
same run, and on whether a zero-change sync prints the line at all.

---

## T30. `digest` entry order within a group

### Spec Text
> | Entry order within group | Deterministic |

> | Download candidate order | Same as catalog order within category |

### Alternatives
1. Catalog order (the order entries appear in the category array).
2. Sorted by entry `id`.
3. Sorted by displayed title.

### Choice
Alternative 1. The spec's only other "deterministic order" requirement in this
document is explicitly resolved as catalog order, and the catalog's own
ordering rules already make that order deterministic, so reusing it needs no
new tiebreak rule.

### Risk: 28
Author most likely prefers: the same catalog order; a fixture with several
changed entries in one group would distinguish it from id- or title-sorted
output.

---

## T31. Naming changed fields in the field-update suffix

### Spec Text
> | Field-update suffix | Changed field names in parentheses after title |

> | Reappearance after removal (v3 only) | Indicate reappearance alongside any other changed fields |

### Alternatives
1. List the tracked field names verbatim, comma-separated, in the spec's
   tracked-field order, and render a `removed: true -> false` transition as a
   word such as `reappeared` inside the same parentheses.
2. Render the reappearance as the literal field name `removed`.
3. Put the reappearance note outside the parentheses, as separate text.

### Choice
Alternative 1: `Title e1 (title, views, reappeared)`. "Indicate reappearance
**alongside** any other changed fields" reads as one combined list, and
`removed` is a poor label for an entry that just came back.

### Risk: 35
Author most likely prefers: the combined parenthesized list; the exact token
(`reappeared` vs `removed` vs `restored`) is unconstrained, so a test matching
an exact suffix string could differ.

---

## T32. Does `removed` count as a tracked field for field updates?

### Spec Text
> | Field updates | At least one tracked field has two or more history entries and the latest two values differ |

> | Additions | Entry has only initial observations; no tracked field has a second history entry |

### Alternatives
1. `removed` is a tracked field like the other five, so a v3 entry whose only
   change is `true -> false` qualifies as a field update (and is exactly the
   "reappearance" case the output layout describes).
2. Field updates consider only the five value fields, and a reappearance is a
   fourth, implicit group.

### Choice
Alternative 1. The spec's tracked-field set includes `removed`, the removals
rule is written in terms of that same history, and the layout table says
reappearance is shown "alongside any other changed fields" — i.e. inside the
field-update presentation, not as its own group.

### Risk: 18
Author most likely prefers: the same treatment; the readings diverge for an
entry whose `removed` history is `true -> false` with no other change, which
choice 2 would omit from the digest entirely.

---

## T33. Content of the `digest` trailing line

### Spec Text
> | Trailing line | Metadata about the digest run |

> | Source reference | The trailing line includes the resolved source URL for the loaded vault version |

> | Digest trailing line | Deterministic format |

### Alternatives
1. One line naming the vault, the catalog version actually loaded, the
   resolved source URL, and a generation timestamp.
2. Only the source URL.
3. Several trailing lines.

### Choice
Alternative 1, as a single line:
`Digest for vault '<name>' | catalog version <n> | source: <url> | generated <ISO timestamp>`.
"Metadata about the digest run" is plural in spirit, the version is what
distinguishes the three loaders, and the Determinism table's carve-out for
"wall-clock usage outside digest trailing line" implies the trailing line is
the one place a timestamp is allowed.

### Risk: 30
Author most likely prefers: a single trailing line containing the source URL;
the surrounding fields and separators are unconstrained, so only a test
asserting the URL's presence (rather than the whole line) passes both.

---

## T34. Group headings and the "no notable changes" message

### Spec Text
> | Empty category | Omitted |

> | No notable changes anywhere | Indicate that no notable changes were found |

### Alternatives
1. Human-readable headings taken from the spec's own group names —
   `Removals`, `Additions`, `Field updates` — under a category heading, with
   the single line `No notable changes found.` when nothing qualifies.
2. Machine-ish labels (`removed:`, `added:`, `updated:`).
3. No group headings at all, only per-entry markers.

### Choice
Alternative 1. The spec names the groups in its own tables, and reusing those
names keeps the output self-describing; the trailing line is still printed in
the "no notable changes" case, since it is metadata about the run rather than
part of any category.

### Risk: 30
Author most likely prefers: some heading per group and a distinct no-changes
sentence; the exact words are unspecified, so exact-string assertions could
differ while substring checks on the entry titles pass either way.

---

## T35. Fields with two history entries holding the same value

### Spec Text
> | Additions | Entry has only initial observations; no tracked field has a second history entry |

> | Field updates | At least one tracked field has two or more history entries and the latest two values differ |

### Alternatives
1. Take both rules literally: such an entry is not an addition (a field does
   have a second history entry) and not a field update (the latest two values
   match), so it appears in no group.
2. Treat "only initial observations" loosely as "no value ever changed", so
   the entry is still reported as an addition.

### Choice
Alternative 1. The two rules are written with different tests — existence of a
second entry versus inequality of the latest two values — and reading them
literally is the only way both sentences do work. A vault whose catalog is
written only by this implementation never produces such a history anyway,
since `sync` appends only on change.

### Risk: 20
Author most likely prefers: the same literal reading, which is what a direct
transcription of the two rules produces; a hand-built fixture with a repeated
value is the only way to tell.

---

## T36. `--format` handling: leading dots, and scope

### Spec Text
> | `--format=<str>` | string | Override media download format and output extension |

> | Media with format override | `<source>/media/<entry_id>.<format>` | `<vault>/media/` | Extension = format string |

### Alternatives
1. Use the string exactly as given in both the URL and the extension, so
   `--format=mp4` yields `.../media/e1.mp4` and `e1.mp4`.
2. Normalize a leading dot (`--format=.mp4` behaves like `mp4`).
3. Apply the override to previews as well.

### Choice
Alternatives 1 and 2 combined: the string is used verbatim after stripping any
single leading `.`, so the URL template `<entry_id>.<format>` never produces
`e1..mp4`. Previews are untouched — the spec calls it a *media* download
format and gives no preview row for the override.

### Risk: 15
Author most likely prefers: verbatim use of the string; the readings diverge
only for a caller who passes a leading dot, which no natural fixture does.

---

## T37. `--episodes=0`

### Spec Text
> | `--episodes=<n>` | non-negative integer | Maximum number of episode media downloads |

> | Omitted limit | No limit for that category |

### Alternatives
1. `0` is a real limit: download nothing from that category.
2. `0` means "unlimited" (a sentinel), with omission meaning the same.

### Choice
Alternative 1. The type is explicitly "non-negative integer", which only
matters if `0` is a legal and meaningful value, and the spec gives omission —
not zero — as the way to express "no limit".

### Risk: 7
Author most likely prefers: the same, since the spec distinguishes an omitted
limit from a supplied one.

---

## T38. `digest` leniency on malformed or partial legacy catalogs

### Spec Text
> `digest` must work directly on v1, v2, and v3 catalogs without migrating.

> | Missing vault | Error to stderr including vault name; exit non-zero |

### Alternatives
1. `digest` applies the same strict legacy validation `migrate`/`sync` apply,
   erroring on any malformed entry.
2. `digest` validates only what it needs — the file parses, the version is
   supported — and skips or degrades gracefully on individual entries with
   missing or oddly-typed history (an entry with no `title` history shows its
   `id`).

### Choice
Alternative 2. `digest` is specified as read-only and as working "directly"
on every version; the error table lists only two failure modes for it
(missing vault, unsupported version), which suggests other conditions are not
meant to abort a digest.

### Risk: 25
Author most likely prefers: leniency for the listed failure modes; an
implementation that reuses the strict legacy loader would exit non-zero on a
malformed-entry fixture where this one prints a digest.

---

## T39. How "stale partial-download artifacts must not block a later download"
    is achieved

### Spec Text
> | Partial artifacts | Stale partial-download artifacts must not block a later successful download |

### Alternatives
1. Download to a temporary `<name>.part` file and rename into place only on
   success, and treat any `*.part` file in `<vault>/media/` as not being a
   "corresponding media file" for candidate selection.
2. Write directly to the final filename and delete it if the download fails.
3. Do nothing special and rely on the HTTP layer.

### Choice
Alternative 1. It satisfies the requirement from both directions: a crashed
run never leaves a file that would be mistaken for a completed download, and
a leftover artifact from any earlier run is ignored by candidate selection and
overwritten by the next attempt. A failed attempt also removes its own
`.part` file.

### Risk: 20
Author most likely prefers: some temp-then-rename scheme; a fixture that
pre-creates `<vault>/media/e1.mp4.part` and expects the next `sync` to still
download `e1` passes here, while an implementation keying candidacy on any
filename starting with the id would fail it.

---

## T40. Post-summary and downloads on a run with `--skip-download`

### Spec Text
> | Metadata-only run | `--skip-download` |

> | Trigger | Successful `sync` run that includes metadata phase |

### Alternatives
1. `--skip-download` still runs the full metadata phase, so it still saves the
   catalog and still prints the post-sync summary.
2. `--skip-download` suppresses the summary too, since nothing was downloaded.

### Choice
Alternative 1. The summary's trigger is stated as the presence of the metadata
phase, and `--skip-download` is defined as "fetch and persist metadata only" —
the metadata phase is exactly what remains.

### Risk: 6
Author most likely prefers: the same, since the trigger names the metadata
phase explicitly.
