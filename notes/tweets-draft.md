# Poll tweets: could you pass Slop Code Bench?

Thread draft. Each poll is one of the five datagate sentences; the correct answer is the
one the hidden tests take, and Opus 5 picked the other one 195 times out of 200 blind
readings. Reveal thread after the polls close.

**1 / opener**
We all mock the AI's slop in @GOrlanski's Slop Code Bench. Could you do better? Five spec
sentences, five polls. The benchmark's hidden tests already decided each one. (cc @dexhorthy)

**2 / force**
> `force` is a presence flag. If present once, it forces re-ingestion and replaces the cached dataset.
> Any additional `force` value is `HTTP 400`.

What is `?force=1`?
- 400: a value beyond mere presence
- fine: "additional" means a second `force`

**3 / rowid**
> `_shape=objects`: `rows` is objects and includes `rowid` (1-based source-file row number).

A file has a header line and then Alice. Alice's `rowid` is:
- 1
- 2

**4 / charset on a spreadsheet**
> `charset` applies only to text CSV sources.
> (earlier) Unsupported or malformed `charset` → 400

`/convert?charset=bad-charset-name` on an `.xlsx` source:
- 400, the parameter is malformed
- 200, it doesn't apply to spreadsheets

**5 / charset on upload**
> `POST /upload` accepts multipart form with field `file` or `attachment`.

Does `POST /upload?charset=iso-8859-1` decode the file as latin-1?
- yes, same parameter as `/convert`
- no, upload lists no parameters

**6 / encoding**
> `charset` … If omitted, detect encoding from content.

Six bytes: `name\ncafé\n` in latin-1, no charset given. A conforming server returns:
- `café`
- whatever a charset detector guesses

**7 / reveal**
Tests say: 400, 2, 200, yes, `café`. Opus 5 read them the other way in 195 of 200 blind
readings, and argued well for each. Five reworded sentences later it passes all 405
tests. The spec, not the model, was the slop. Full writeup: [five sentences link]

## Candidates from the v8B run (2026-09-03), a different kind of miss

Two more sentences, from `problems/datagate-clarified-2.patch`. Not the same story as the
five above: on the first, blind judges read it the tests' way 20 of 20 and only the tester
disagreed; on the second, the tester declared the case unresolved and the implementation
fell through to a library default. Poll-worthy on their own terms, since a human reader
splits on both, but the reveal line would be "the tester lost its nerve", not "the spec
was slop".

**8 / blank CACHE_ENABLED**
> `CACHE_ENABLED` accepts strict case-insensitive values: `1`, `true`, `yes`, `on` / `0`, `false`, `no`, `off`.
> Invalid values fail startup.
> (later) Boolean values are strict (case-insensitive, trimmed).

`CACHE_ENABLED="   "`, three spaces. The service:
- fails startup, it's an invalid value
- starts with the default, trimming left no value

**9 / enrich twice**
> Only exact `enrich=yes` enables enrichment.
> All other states keep enrichment off.

`/convert?source=…&enrich=yes&enrich=no`. Enrichment is:
- off, a repeated parameter is one of the "other states"
- on, the first `enrich=yes` is exact

Tests say: fails startup, off. Reference solution: strip then reject anything outside the
eight tokens; enrich only when the parameter list is exactly `["yes"]`.
