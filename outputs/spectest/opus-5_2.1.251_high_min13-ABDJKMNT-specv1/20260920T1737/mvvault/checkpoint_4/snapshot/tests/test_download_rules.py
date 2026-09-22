"""Download rules: candidate selection, ordering, limits and partial artifacts."""

from conftest import names_in, read_catalog, source_entry


def published(day):
    """A `published` value that puts later days first in catalog order."""
    return f"2024-01-{day:02d}T00:00:00"


# Spec: "| Candidate selection | Only entries without a corresponding media file
# in `<vault>/media/` are candidates; A file matches if the name contains entry
# `id` ... |".
def test_entry_with_an_existing_media_file_is_not_a_candidate(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    (vault / "media").mkdir()
    (vault / "media" / "already-e1-here.mp4").write_bytes(b"kept")

    run_cli("sync", "demo")

    assert source.asset_requests["media/e1"] == 0
    assert (vault / "media" / "already-e1-here.mp4").read_bytes() == b"kept"


# Spec: "... apart from partial downloads" and "| Partial artifacts | Stale
# partial-download artifacts must not block a later successful download |".
def test_stale_partial_artifact_does_not_block_download(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    (vault / "media").mkdir()
    (vault / "media" / "e1.mp4.part").write_bytes(b"half")

    result = run_cli("sync", "demo")

    assert result.returncode == 0, result.stderr
    assert source.asset_requests["media/e1"] == 1
    assert (vault / "media" / "e1.mp4").read_bytes() == b"media/e1-bytes"


# Spec: "| Candidate order | Catalog order within category |" and
# "| Per-category limit | Download first `N` candidates in candidate order |".
def test_episode_limit_takes_the_first_candidates_in_catalog_order(run_cli, source, vault):
    source.serve(
        episodes=[
            source_entry("older", published=published(1)),
            source_entry("newest", published=published(3)),
            source_entry("middle", published=published(2)),
        ]
    )
    run_cli("sync", "demo", "--skip-download")
    order = [entry["id"] for entry in read_catalog(vault)["episodes"]]

    result = run_cli("sync", "demo", "--skip-metadata", "--episodes=2")

    assert result.returncode == 0, result.stderr
    assert names_in(vault / "media") == sorted(f"{entry_id}.mp4" for entry_id in order[:2])


# Spec: "| `--episodes=<n>` | non-negative integer | Maximum number of episode
# media downloads |" -- a limit of zero downloads nothing in that category.
def test_zero_limit_downloads_nothing_in_that_category(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")], clips=[source_entry("c1")])

    result = run_cli("sync", "demo", "--episodes=0")

    assert result.returncode == 0, result.stderr
    assert names_in(vault / "media") == ["c1.mp4"]


# Spec: "| Omitted limit | No limit for that category |".
def test_omitted_limit_downloads_every_candidate(run_cli, source, vault):
    source.serve(
        episodes=[source_entry(f"e{index}") for index in range(4)],
        streams=[source_entry("s1")],
    )

    result = run_cli("sync", "demo", "--episodes=1")

    assert result.returncode == 0, result.stderr
    assert names_in(vault / "media").count("s1.mp4") == 1
    assert len([name for name in names_in(vault / "media") if name.startswith("e")]) == 1


# Spec: "| `--streams=<n>` | ... |" and "| `--clips=<n>` | ... |" -- limits are
# per category and do not leak into one another.
def test_limits_are_independent_per_category(run_cli, source, vault):
    source.serve(
        episodes=[source_entry("e1"), source_entry("e2")],
        streams=[source_entry("s1"), source_entry("s2")],
        clips=[source_entry("c1"), source_entry("c2")],
    )

    run_cli("sync", "demo", "--episodes=1", "--streams=0", "--clips=2")

    downloaded = names_in(vault / "media")
    assert len([name for name in downloaded if name.startswith("e")]) == 1
    assert [name for name in downloaded if name.startswith("s")] == []
    assert len([name for name in downloaded if name.startswith("c")]) == 2


# Spec: "| Candidate selection | Only entries without a corresponding media file
# ... |" -- a second sync re-downloads nothing.
def test_second_sync_downloads_nothing_new(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    run_cli("sync", "demo")

    run_cli("sync", "demo")

    assert source.asset_requests["media/e1"] == 1
