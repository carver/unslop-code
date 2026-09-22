"""Spec sections: Download Rules (failures), `catalog.json` Persistence During `sync`,
Error Handling (download failures)."""

from conftest import media_stems, payload, read_catalog, source_entry


# Spec: Permanent download failure | Warning to stderr; continue with remaining entries
def test_permanent_failure_warns_and_continues(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1"), source_entry("e2")]))
    source.serve_assets("e2")  # e1 has no asset registered -> 404

    result = run("sync", "vault")
    assert result.returncode == 0
    assert "e1" in result.stderr
    assert media_stems(vault) == ["e2"]


# Spec: Permanently unavailable content during download | stderr | `0` | Warning per entry
def test_permanent_failure_warns_per_affected_entry(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1"), source_entry("e2")]))
    result = run("sync", "vault")
    assert result.returncode == 0
    assert "e1" in result.stderr
    assert "e2" in result.stderr


# Spec: Successful run with skipped downloads due to download failures | Exit code `0`
def test_download_failures_still_exit_zero(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    assert run("sync", "vault").returncode == 0


# Spec: Transient download failure | Retry, then warn to stderr after retries exhausted
def test_transient_failure_is_retried_then_succeeds(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_assets("e1")
    source.fail_next("media/e1", [503])

    result = run("sync", "vault")
    assert result.returncode == 0, result.stderr
    assert source.hits("media/e1") >= 2
    assert media_stems(vault) == ["e1"]


# Spec: Transient download failure after retries exhausted | stderr | `0` | Warning per entry
def test_transient_failure_warns_after_retries_exhausted(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_assets("e1")
    source.fail_next("media/e1", [503, 503, 503, 503, 503])

    result = run("sync", "vault")
    assert result.returncode == 0
    assert "e1" in result.stderr
    assert media_stems(vault) == []


# Spec: Permanent download failure | ... a permanent failure is not retried
def test_permanent_failure_is_not_retried(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    run("sync", "vault")
    assert source.hits("media/e1") == 1


# Spec: Download failure interaction | Metadata save still occurs even when downloads fail
def test_metadata_is_saved_despite_download_failures(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    result = run("sync", "vault")
    assert result.returncode == 0
    assert [e["id"] for e in read_catalog(vault)["episodes"]] == ["e1"]


# Spec: Persistence boundary | Metadata changes must be durably saved before sync returns
def test_metadata_saved_before_sync_returns(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_assets("e1")
    run("sync", "vault")
    catalog = read_catalog(vault)
    assert catalog["episodes"][0]["title"]


# Spec: Partial artifacts | A failed download leaves nothing that blocks the next run
def test_failed_download_does_not_block_a_later_success(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    assert run("sync", "vault").returncode == 0
    assert media_stems(vault) == []

    source.serve_assets("e1")
    assert run("sync", "vault").returncode == 0
    assert media_stems(vault) == ["e1"]


# Spec: ... continue with remaining entries (a failing category does not stop the next)
def test_failure_in_one_category_does_not_stop_the_others(run, source, vault):
    source.serve(
        payload(
            episodes=[source_entry("e1")],
            streams=[source_entry("s1")],
            clips=[source_entry("c1")],
        )
    )
    source.serve_assets("s1", "c1")
    result = run("sync", "vault")
    assert result.returncode == 0
    assert media_stems(vault) == ["c1", "s1"]


# Spec: Source metadata fetch failure during `sync` | stderr | non-zero | Abort run
def test_source_fetch_failure_aborts_before_downloads(run, source, vault):
    source.serve_raw("not json", status=500)
    source.serve_assets("e1")
    result = run("sync", "vault")
    assert result.returncode != 0
    assert result.stderr.strip()
    assert source.asset_requests() == []


# Spec: Source metadata fetch failure ... does not apply when `--skip-metadata` is given
def test_skip_metadata_ignores_a_broken_source_document(run, source, vault):
    source.serve_raw("not json", status=500)
    assert run("sync", "vault", "--skip-metadata").returncode == 0
