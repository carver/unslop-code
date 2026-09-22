"""Spec: Download Rules (failures) and Error Handling rows for downloads."""
import os

from conftest import (make_entry, media_files, preview_files, read_catalog,
                      media_dir)


# Spec: "| Permanent download failure | Warning to stderr; continue with
# remaining entries |" -- stream and continuation.
def test_permanent_failure_warns_and_continues(run, source, tmp_path, vault):
    source.serve(episodes=[
        make_entry(id="e1", published="2024-03-01T00:00:00"),
        make_entry(id="e2", published="2024-02-01T00:00:00"),
    ])
    source.fail_asset("media", "e1", status=404)
    source.fail_asset("preview", "e1", status=404)
    source.serve_entry_assets("e2")
    res = run("sync", "vault")
    assert res.returncode == 0, res
    assert "e1" in res.stderr
    assert media_files(tmp_path) == ["e2.mp4"]


# Spec: "| Permanently unavailable content during download | stderr | `0` |
# Warning per affected entry; continue |" -- one warning per affected entry.
def test_warning_per_affected_entry(run, source, vault):
    source.serve(episodes=[make_entry(id="e1"), make_entry(id="e2")])
    for i in ("e1", "e2"):
        source.fail_asset("media", i, status=404)
        source.fail_asset("preview", i, status=404)
    res = run("sync", "vault")
    assert res.returncode == 0, res
    assert "e1" in res.stderr and "e2" in res.stderr


# Spec: "Permanent download failure" -- a permanent status is not retried.
def test_permanent_failure_is_not_retried(run, source, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.fail_asset("media", "e1", status=404)
    source.fail_asset("preview", "e1", status=404)
    run("sync", "vault")
    assert source.hits("media", "e1") == 1


# Spec: "| Transient download failure | Retry, then warn to stderr after
# retries exhausted; continue with remaining entries |" -- retry happens.
def test_transient_failure_is_retried(run, source, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.flaky_asset("media", "e1", failures=1, status=503)
    source.serve_preview("e1")
    res = run("sync", "vault")
    assert res.returncode == 0, res
    assert source.hits("media", "e1") >= 2


# Spec: "Transient download failure | Retry, ..." -- a retry that succeeds
# stores the file and emits no warning for that entry.
def test_retry_that_succeeds_stores_the_file(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.flaky_asset("media", "e1", failures=2, status=500)
    source.serve_preview("e1")
    res = run("sync", "vault")
    assert res.returncode == 0, res
    assert media_files(tmp_path) == ["e1.mp4"]


# Spec: "| Transient download failure after retries exhausted | stderr | `0` |
# Warning per affected entry; continue |"
def test_transient_failure_exhausted_warns_and_exits_zero(run, source,
                                                          tmp_path, vault):
    source.serve(episodes=[
        make_entry(id="e1", published="2024-03-01T00:00:00"),
        make_entry(id="e2", published="2024-02-01T00:00:00"),
    ])
    source.fail_asset("media", "e1", status=503)
    source.fail_asset("preview", "e1", status=503)
    source.serve_entry_assets("e2")
    res = run("sync", "vault")
    assert res.returncode == 0
    assert "e1" in res.stderr
    assert media_files(tmp_path) == ["e2.mp4"]
    assert source.hits("media", "e1") > 1


# Spec: "continue with remaining entries" -- a failing entry does not consume
# the whole run; later categories are still processed.
def test_failure_in_one_category_does_not_stop_others(run, source, tmp_path,
                                                      vault):
    source.serve(episodes=[make_entry(id="e1")], clips=[make_entry(id="c1")])
    source.fail_asset("media", "e1", status=404)
    source.fail_asset("preview", "e1", status=404)
    source.serve_entry_assets("c1")
    res = run("sync", "vault")
    assert res.returncode == 0
    assert media_files(tmp_path) == ["c1.mp4"]


# Spec: "| Persistence boundary | Metadata changes must be durably saved before
# successful sync returns, including runs with download failures |" +
# "| Download failure interaction | Metadata save still occurs even when one or
# more downloads fail |"
def test_catalog_saved_when_downloads_fail(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1", views=99)])
    source.fail_asset("media", "e1", status=500)
    source.fail_asset("preview", "e1", status=500)
    assert run("sync", "vault").returncode == 0
    catalog = read_catalog(tmp_path)
    assert list(catalog["episodes"][0]["views"].values()) == [99]


# Spec: a media failure does not suppress the preview attempt for the same
# entry, and vice versa -- each asset is reported independently.
def test_preview_failure_alone_still_stores_media(run, source, tmp_path,
                                                  vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.serve_media("e1")
    source.fail_asset("preview", "e1", status=404)
    res = run("sync", "vault")
    assert res.returncode == 0
    assert media_files(tmp_path) == ["e1.mp4"]
    assert preview_files(tmp_path) == []
    assert "e1" in res.stderr


# Spec: "Stale partial-download artifacts must not block a later successful
# download" -- a failed download must not leave a finished-looking file.
def test_failed_download_writes_no_final_file(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    source.fail_asset("media", "e1", status=500)
    source.fail_asset("preview", "e1", status=500)
    run("sync", "vault")
    assert media_files(tmp_path) == []


# Spec: "| Source metadata fetch failure during `sync` | stderr | non-zero |
# Abort run |" -- a metadata failure is *not* downgraded to a warning the way
# download failures are.
def test_metadata_fetch_failure_aborts_run(run, source, tmp_path, vault):
    source.fail(status=500)
    res = run("sync", "vault")
    assert res.returncode != 0
    assert res.stderr != ""
    assert media_files(tmp_path) == []


# Spec: "Source metadata fetch failure during `sync` ... Abort run" -- the
# download phase does not run after an aborted metadata phase.
def test_no_downloads_after_metadata_failure(run, source, tmp_path, vault):
    source.serve(episodes=[make_entry(id="e1")])
    run("sync", "vault", "--skip-download")
    source.serve_entry_assets("e1")
    source.fail(status=500)
    res = run("sync", "vault")
    assert res.returncode != 0
    assert source.hits("media", "e1") == 0
