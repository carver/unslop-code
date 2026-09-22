"""Download failure handling: warnings, retries, continuation and exit code."""

from conftest import find_entry, names_in, read_catalog, source_entry


# Spec: "| Permanent download failure | Warning to stderr; continue with
# remaining entries |" and "| Permanently unavailable content during download |
# stderr | `0` | Warning per affected entry; continue |".
def test_permanent_failure_warns_and_continues(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1"), source_entry("e2")])
    source.asset_status["media/e1"] = 404

    result = run_cli("sync", "demo")

    assert result.returncode == 0
    assert "e1" in result.stderr
    assert names_in(vault / "media") == ["e2.mp4"]


# Spec: "| Transient download failure | Retry, then warn to stderr after retries
# exhausted; continue with remaining entries |".
def test_transient_failure_is_retried_before_giving_up(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    source.asset_status["media/e1"] = 503

    result = run_cli("sync", "demo")

    assert result.returncode == 0
    assert source.asset_requests["media/e1"] > 1
    assert "e1" in result.stderr


# Spec: "| Transient download failure | Retry, then warn ... |" -- a retry that
# succeeds leaves no warning and stores the file.
def test_transient_failure_that_recovers_produces_the_file(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    source.transient_failures["media/e1"] = 1

    result = run_cli("sync", "demo")

    assert result.returncode == 0, result.stderr
    assert names_in(vault / "media") == ["e1.mp4"]
    assert "e1" not in result.stderr


# Spec: "| Successful run with skipped downloads due to download failures |
# Exit code `0` |".
def test_run_with_only_failing_downloads_still_exits_zero(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")], clips=[source_entry("c1")])
    source.asset_status["media/e1"] = 410
    source.asset_status["media/c1"] = 404

    result = run_cli("sync", "demo")

    assert result.returncode == 0
    assert names_in(vault / "media") == []


# Spec: "| Persistence boundary | Metadata changes must be durably saved before
# successful sync returns, including runs with download failures |" and
# "| Download failure interaction | Metadata save still occurs even when one or
# more downloads fail |".
def test_metadata_is_saved_despite_download_failures(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    source.asset_status["media/e1"] = 404
    source.asset_status["preview/e1"] = 404

    result = run_cli("sync", "demo")

    assert result.returncode == 0
    assert find_entry(read_catalog(vault), "episodes", "e1")


# Spec: "| Permanently unavailable content during download | ... | Warning per
# affected entry; continue |" -- a failed preview does not fail the media file.
def test_failing_preview_does_not_block_media(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    source.asset_status["preview/e1"] = 404

    result = run_cli("sync", "demo")

    assert result.returncode == 0
    assert names_in(vault / "media") == ["e1.mp4"]
    assert names_in(vault / "previews") == []


# Spec: "| Partial artifacts | Stale partial-download artifacts must not block a
# later successful download |" -- a failure leaves no finished file behind.
def test_failed_download_leaves_no_finished_file(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    source.asset_status["media/e1"] = 404
    run_cli("sync", "demo")
    source.asset_status.pop("media/e1")

    result = run_cli("sync", "demo", "--skip-metadata")

    assert result.returncode == 0, result.stderr
    assert names_in(vault / "media") == ["e1.mp4"]
