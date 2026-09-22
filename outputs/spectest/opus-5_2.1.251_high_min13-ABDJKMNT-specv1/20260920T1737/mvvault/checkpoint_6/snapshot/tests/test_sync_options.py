"""`sync` option surface: limits, skip flags, format override and CLI errors."""

from conftest import find_entry, names_in, read_catalog, source_entry


# Spec: "| `--skip-download` | flag | Skip download phase; fetch and persist
# metadata only |" and "| Metadata-only run | `--skip-download` |".
def test_skip_download_persists_metadata_and_downloads_nothing(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])

    result = run_cli("sync", "demo", "--skip-download")

    assert result.returncode == 0, result.stderr
    assert find_entry(read_catalog(vault), "episodes", "e1")
    assert names_in(vault / "media") == []
    assert names_in(vault / "previews") == []


# Spec: "| `--skip-metadata` | flag | Skip source fetch and metadata update; run
# download phase against existing vault state |".
def test_skip_metadata_leaves_catalog_untouched_and_still_downloads(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    run_cli("sync", "demo", "--skip-download")
    before = (vault / "catalog.json").read_text()
    requests_before = source.requests

    result = run_cli("sync", "demo", "--skip-metadata")

    assert result.returncode == 0, result.stderr
    assert (vault / "catalog.json").read_text() == before
    assert source.requests == requests_before
    assert names_in(vault / "media") == ["e1.mp4"]


# Spec: "| Download-only run | `--skip-metadata` |" combined with
# "| Metadata-only run | `--skip-download` |" -- both flags together do neither.
def test_both_skip_flags_do_no_work(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])

    result = run_cli("sync", "demo", "--skip-metadata", "--skip-download")

    assert result.returncode == 0, result.stderr
    assert source.requests == 0
    assert names_in(vault / "media") == []


# Spec: "| Malformed numeric category limit | stderr | non-zero | Abort before
# any sync work |".
def test_malformed_limit_aborts_before_any_sync_work(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    before = (vault / "catalog.json").read_text()

    result = run_cli("sync", "demo", "--episodes=many")

    assert result.returncode != 0
    assert result.stderr.strip()
    assert source.requests == 0
    assert (vault / "catalog.json").read_text() == before


# Spec: "| `--episodes=<n>` | non-negative integer | ...".
def test_negative_limit_is_malformed(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])

    result = run_cli("sync", "demo", "--streams=-1")

    assert result.returncode != 0
    assert result.stderr.strip()
    assert source.requests == 0


# Spec: "| Unrecognized CLI option | stderr | non-zero | Abort before any sync
# work |".
def test_unrecognized_option_aborts_before_any_sync_work(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])

    result = run_cli("sync", "demo", "--nonsense=1")

    assert result.returncode != 0
    assert result.stderr.strip()
    assert source.requests == 0


# Spec: "| Source metadata fetch failure during `sync` | stderr | non-zero |
# Abort run |" -- the download phase must not run either.
def test_metadata_fetch_failure_aborts_the_run(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    source.status = 500

    result = run_cli("sync", "demo")

    assert result.returncode != 0
    assert result.stderr.strip()
    assert names_in(vault / "media") == []
