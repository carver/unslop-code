"""`sync` Post-Summary table."""

import re

import pytest

from conftest import source_entry

COUNT = re.compile(r"(\d+)")


@pytest.fixture
def sync(run_cli, vault, source):
    """Run `sync --skip-download` on the vault 'v' and return the result."""

    def run(*options, episodes=(), streams=(), clips=()):
        source.payload = {
            "episodes": list(episodes),
            "streams": list(streams),
            "clips": list(clips),
        }
        result = run_cli("sync", "v", "--skip-download", *options)
        assert result.returncode == 0, result.stderr
        return result

    return run


def counts(result):
    """The added/removed/updated numbers from the post-sync summary line."""
    line = next(line for line in result.stdout.splitlines() if COUNT.search(line) and "added" in line)
    return [int(number) for number in COUNT.findall(line)]


# Spec: Trigger | Successful `sync` run that includes metadata phase
def test_summary_is_printed_after_a_metadata_phase(sync):
    assert counts(sync(episodes=[source_entry("a")])) == [1, 0, 0]


# Spec: Output stream | stdout
def test_summary_goes_to_stdout(sync):
    result = sync(episodes=[source_entry("a")])
    assert "added" in result.stdout
    assert result.stderr == ""


# Spec: Counts reported | Added, removed, updated
def test_added_entries_are_counted(sync):
    assert counts(sync(episodes=[source_entry("a")], clips=[source_entry("c")])) == [2, 0, 0]


# Spec: Counts reported | Added, removed, updated
def test_removed_entries_are_counted(sync):
    sync(episodes=[source_entry("a"), source_entry("b")])
    assert counts(sync(episodes=[source_entry("a")])) == [0, 1, 0]


# Spec: Counts reported | Added, removed, updated
def test_updated_entries_are_counted(sync):
    sync(episodes=[source_entry("a", views=1)])
    assert counts(sync(episodes=[source_entry("a", views=2)])) == [0, 0, 1]


# Spec: Counts reported | ... (an unchanged entry is counted in no group)
def test_unchanged_entries_are_not_counted(sync):
    sync(episodes=[source_entry("a")])
    assert counts(sync(episodes=[source_entry("a")])) == [0, 0, 0]


# Spec: Counts reported | ... (an entry that comes back counts as an update)
def test_reappearing_entry_counts_as_updated(sync):
    sync(episodes=[source_entry("a")])
    sync(episodes=[])
    assert counts(sync(episodes=[source_entry("a")])) == [0, 0, 1]


# Spec: Counts reported | ... (an entry already removed is not counted again)
def test_entry_removed_twice_is_counted_once(sync):
    sync(episodes=[source_entry("a")])
    sync(episodes=[])
    assert counts(sync(episodes=[])) == [0, 0, 0]


# Spec: Post-sync counts | Deterministic for the same vault state and source metadata
def test_counts_are_deterministic_for_the_same_state(sync):
    first = counts(sync(episodes=[source_entry("a"), source_entry("b")]))
    second = counts(sync(episodes=[source_entry("a"), source_entry("b")]))
    assert first == [2, 0, 0] and second == [0, 0, 0]


# Spec: Trigger | Successful `sync` run that includes metadata phase (a
# `--skip-metadata` run reports no counts)
def test_skip_metadata_prints_no_summary(run_cli, vault, source):
    source.payload = {"episodes": [source_entry("a")], "streams": [], "clips": []}
    run_cli("sync", "v", "--skip-download")
    result = run_cli("sync", "v", "--skip-metadata", "--skip-download")
    assert result.returncode == 0, result.stderr
    assert "added" not in result.stdout
