"""Spec sections: `sync` Command (phases and skip flags), `sync` Options,
and the Error Handling rows for CLI option parsing."""
import os

import pytest

from conftest import (
    catalog_text,
    entry,
    media_path,
    media_files,
    payload,
    preview_path,
    read_catalog,
)


# --- Phrase: "Syntax | `python mvault.py sync <name> [options]`"
#     (context: options are optional -- the bare form still works)
def test_sync_without_options_still_succeeds(run, source, vault):
    source.set_payload(payload())
    assert run("sync", "vault").returncode == 0


# --- Phrase: "Metadata phase | Load vault, optionally fetch source metadata,
#     update catalog history, persist metadata"
def test_metadata_phase_persists_history(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    assert run("sync", "vault", "--skip-download").returncode == 0
    catalog = read_catalog(tmp_path)
    assert [e["id"] for e in catalog["episodes"]] == ["e1"]


# --- Phrase: "Download phase | Retrieve media and preview files after
#     metadata phase"
def test_download_phase_runs_after_metadata_phase(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_entry_assets("e1")
    assert run("sync", "vault").returncode == 0
    # The entry only becomes a download candidate once the metadata phase has
    # put it in the catalog, so a single run must do both in that order.
    assert media_path("e1") in [path for _m, path in source.requests]
    assert [e["id"] for e in read_catalog(tmp_path)["episodes"]] == ["e1"]


def test_download_requests_follow_the_metadata_request(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_entry_assets("e1")
    run("sync", "vault")
    paths = [path for _m, path in source.requests]
    assert paths[0] == "/source.json"
    assert paths.index(media_path("e1")) > 0


# --- Phrase: "Metadata-only run | `--skip-download`"
def test_skip_download_performs_no_downloads(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    source.set_entry_assets("e1")
    assert run("sync", "vault", "--skip-download").returncode == 0
    paths = [path for _m, path in source.requests]
    assert media_path("e1") not in paths
    assert preview_path("e1") not in paths
    assert media_files(tmp_path) == []


# --- Phrase: "`--skip-download` | flag | Skip download phase; fetch and
#     persist metadata only"
def test_skip_download_still_fetches_and_persists(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault", "--skip-download")
    assert ("GET", "/source.json") in source.requests
    assert read_catalog(tmp_path)["episodes"], "metadata was not persisted"


# --- Phrase: "Download-only run | `--skip-metadata`"
def test_skip_metadata_does_not_fetch_the_source(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault", "--skip-download")
    source.requests.clear()
    source.set_entry_assets("e1")
    assert run("sync", "vault", "--skip-metadata").returncode == 0
    assert ("GET", "/source.json") not in source.requests


# --- Phrase: "`--skip-metadata` | flag | Skip source fetch and metadata
#     update; run download phase against existing vault state"
def test_skip_metadata_runs_the_download_phase(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault", "--skip-download")
    source.set_entry_assets("e1")
    assert run("sync", "vault", "--skip-metadata").returncode == 0
    assert media_files(tmp_path) == ["e1.mp4"]


# --- Phrase: "Skip source fetch and metadata update" (context: no history is
#     appended, so the catalog file is left as the metadata phase wrote it)
def test_skip_metadata_leaves_the_catalog_unchanged(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault", "--skip-download")
    before = catalog_text(tmp_path)
    source.set_payload(payload(episodes=[entry("e1", title="Changed")]))
    source.set_entry_assets("e1")
    run("sync", "vault", "--skip-metadata")
    assert catalog_text(tmp_path) == before


# --- Phrase: "Metadata-only run | `--skip-download`" +
#     "Download-only run | `--skip-metadata`" (context: both together is a
#     no-op run, not an error)
def test_both_skip_flags_together_succeed(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault", "--skip-download")
    source.requests.clear()
    result = run("sync", "vault", "--skip-metadata", "--skip-download")
    assert result.returncode == 0, result
    assert source.requests == []
    assert media_files(tmp_path) == []


# --- Phrase: "Successful run with skipped downloads due to download failures
#     | Exit code `0`"
def test_download_failures_still_exit_zero(run, source, vault):
    source.set_payload(payload(episodes=[entry("e1")]))
    # No asset configured: every media/preview path answers 404.
    result = run("sync", "vault")
    assert result.returncode == 0, result
    assert result.stderr.strip(), "expected a warning on stderr"


# --- Phrase: "| `--episodes=<n>` | non-negative integer | Maximum number of
#     episode media downloads |" and the `--streams` / `--clips` rows
@pytest.mark.parametrize("option", ["--episodes", "--streams", "--clips"])
def test_category_limit_options_are_accepted(run, source, vault, option):
    source.set_payload(payload())
    result = run("sync", "vault", "%s=2" % option)
    assert result.returncode == 0, result


# --- Phrase: "| `--format=<str>` | string | Override media download format
#     and output extension |"
def test_format_option_is_accepted(run, source, vault):
    source.set_payload(payload())
    assert run("sync", "vault", "--format=mp4").returncode == 0


# --- Phrase: "| Malformed numeric category limit | stderr | non-zero |
#     Abort before any sync work |"
@pytest.mark.parametrize(
    "value", ["abc", "", "1.5", "-1", "2x", "0x10", " ", "1e3"]
)
@pytest.mark.parametrize("option", ["--episodes", "--streams", "--clips"])
def test_malformed_category_limit_exits_non_zero(run, source, vault, option, value):
    source.set_payload(payload(episodes=[entry("e1")]))
    result = run("sync", "vault", "%s=%s" % (option, value))
    assert result.returncode != 0, result
    assert result.stderr.strip(), result


def test_malformed_category_limit_aborts_before_any_sync_work(
    run, source, vault, tmp_path
):
    source.set_payload(payload(episodes=[entry("e1")]))
    before = catalog_text(tmp_path)
    result = run("sync", "vault", "--episodes=abc")
    assert result.returncode != 0, result
    assert source.requests == [], source.requests
    assert catalog_text(tmp_path) == before
    assert not os.path.exists(os.path.join(str(tmp_path), "vault", "media"))


# --- Phrase: "non-negative integer" (context: `0` is a valid limit, see
#     AMBIGUITIES T37)
def test_zero_is_a_valid_category_limit(run, source, vault):
    source.set_payload(payload())
    assert run("sync", "vault", "--episodes=0").returncode == 0


# --- Phrase: "| Unrecognized CLI option | stderr | non-zero | Abort before
#     any sync work |"
@pytest.mark.parametrize("option", ["--bogus", "--episodes2=1", "--fmt=mp4",
                                    "--skip", "-z"])
def test_unrecognized_option_exits_non_zero(run, source, vault, option):
    source.set_payload(payload(episodes=[entry("e1")]))
    result = run("sync", "vault", option)
    assert result.returncode != 0, result
    assert result.stderr.strip(), result


def test_unrecognized_option_aborts_before_any_sync_work(
    run, source, vault, tmp_path
):
    source.set_payload(payload(episodes=[entry("e1")]))
    before = catalog_text(tmp_path)
    result = run("sync", "vault", "--bogus")
    assert result.returncode != 0, result
    assert source.requests == [], source.requests
    assert catalog_text(tmp_path) == before
