# mvvault: the v0 misses, by sentence (2026-09-20)

Step 1 and the first half of step 2 of `/solve-one-problem`, from the eight opus-5 runs on the
unpatched spec (just-solve 221 and 214, anti-slop 213, min11 222, min12 220 and 223, min13 215
and 216, of 227). Nineteen tests fail somewhere. Counts below are `bin/test-history` over all
twelve mvvault runs, the sonnet and fable ones included. No patch is written; the pitch went to
the user first.

## Readings

1. **The error message must carry the condition's name.** checkpoint_1.md:83 "`sync` must fail
   as a source metadata fetch failure" and the error table's row `Source metadata fetch
   failure | stderr | non-zero | Error message; malformed source entries are included in this
   case`. Tests `test_sync_rejects_source_entry_missing_tracked_field` and
   `…_with_wrong_field_type` want stderr to contain "Source metadata fetch failure"
   (case-insensitive); the reference prints `Source metadata fetch failure: {exc}`. Every run
   rejects the entry, exits non-zero and leaves the vault alone, then says what was wrong in
   its own words ("'episodes' entry in … is missing the 'title' field"). 0 pass, 11 fail. The
   other rows of the same table say "Message includes vault name"; this row says only "Error
   message". Two tests, carried as regressions through all six checkpoints.
2. **Any file whose name contains the id counts as downloaded.** checkpoint_3.md:36 "Filename
   contains entry `id`" (the rule for naming a download) and :45 "Only entries without a
   corresponding media file in `<vault>/media/` are candidates". `test_skip_downloaded_candidate`
   plants `media/archive-already_ep-copy.bin` and wants no request for `/media/already_ep`. The
   reference: `entry_id in path.name and not path.name.endswith(".part")`. Runs match `<id>.<ext>`.
   1 pass, 10 fail. The "Partial artifacts" row pulls the other way, since a stale partial file
   contains the id too, which is why the reference carves out `.part`.
3. **The browser opens the bind address as given.** checkpoint_4.md:15-17, "Default bind address
   `127.0.0.1:8840`", "`serve` without `<name>` | Start server and open browser to `/`".
   `test_serve_custom_addr` binds `0.0.0.0:<port>` and wants the browser sent to
   `http://0.0.0.0:<port>/`; runs open `http://127.0.0.1:<port>/`, the address a browser can
   reach. 4 pass, 7 fail. Taste as much as reading: the runs' choice is the better program.
4. **Entries `sync` creates carry `annotations: []`.** checkpoint_1's stored-fields table has no
   `annotations`; checkpoint_2.md:17 gives it as part of the v3 shape and :115/:125 add `[]`
   "to every entry" on migration only. `test_sync_v1_adds_new_entries_in_v3_shape` reads
   `entry["annotations"]` on an entry a post-migration sync added: `KeyError`. Two real misses
   (the just-solve control, min12's first run); the other five failures of this test are the
   `requests` family below. Both min12 and min13 registries carry it as T12 at Risk 35 and 45,
   and the runs that chose "always present" pass.
5. **A missing vault redirects to the bare root.** checkpoint_4.md:110 "Redirect to `/`; landing
   page shows vault-not-found indication". `test_missing_vault_route` wants the `Location` to
   be exactly the root; three opus runs (anti-slop, min13's first, min11) redirect to
   `/?missing=<name>` to carry the indication. 6 pass, 5 fail.
6. **An annotation's timecode is shown in seconds.** checkpoint_6.md:77 "visibly rendering stored
   annotations", :65 "`timecode` | integer | Whole seconds". `test_post_create` looks for `90`
   in the page; anti-slop and both min13 runs print `1:30`. 6 pass, 5 fail. Taste: `1:30` is
   the kinder page.

## Not the spec: the `requests` family (process, upstream)

Seven tests (the five v1 cases at checkpoint 2, v3-shape among them, `test_sync_v1_download_url`
at 3 and `test_sync_links` at 4) fail together in exactly the four opus runs whose implementation imports `requests`: just-solve's repeat,
anti-slop, and both min13 runs. The tests reroute the v1 source host by patching
`urllib.request.urlopen` (`notes/upstream-prs.md`, "mvvault's v1 tests only reroute…"), so any
other client asks DNS for media.example.com and exits 1. The spec names no client. It is the
largest block, seven tests a run, and it follows the HTTP library, not the prompt:
min12 used urllib twice and min13 `requests` twice.

## Singles

`test_serve_named_v1`/`_v3` (anti-slop only), the detail-route error pair (just-solve's repeat
only), `test_migration_atomic` x2 (min12's first run: a 302 where the test wants a 500). One
run each; noise until they recur.
