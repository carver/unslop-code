"""`sync` post-summary: added / removed / updated counts on stdout."""

import re

from conftest import source_entry


def counts(stdout):
    """The three numbers reported by the post-sync summary line."""
    numbers = [int(value) for value in re.findall(r"\d+", stdout)]
    assert len(numbers) == 3, stdout
    return numbers


# Spec: "| Trigger | Successful `sync` run that includes metadata phase |",
# "| Output stream | stdout |", "| Counts reported | Added, removed, updated |".
def test_first_sync_reports_added_entries(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1"), source_entry("e2")])

    result = run_cli("sync", "demo", "--skip-download")

    assert result.returncode == 0, result.stderr
    assert counts(result.stdout) == [2, 0, 0]


# Spec: "| Counts reported | Added, removed, updated |" -- a source that drops an
# entry and changes another reports one removal and one update.
def test_removals_and_updates_are_counted(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1"), source_entry("e2")])
    run_cli("sync", "demo", "--skip-download")
    source.serve(episodes=[source_entry("e1", title="new title")])

    result = run_cli("sync", "demo", "--skip-download")

    assert counts(result.stdout) == [0, 1, 1]


# Spec: "| Post-sync counts | Deterministic for the same vault state and source
# metadata |" -- an unchanged source reports nothing changed.
def test_unchanged_source_reports_no_changes(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    run_cli("sync", "demo", "--skip-download")

    result = run_cli("sync", "demo", "--skip-download")

    assert counts(result.stdout) == [0, 0, 0]


# Spec: "| Trigger | Successful `sync` run that includes metadata phase |" --
# a download-only run prints no summary.
def test_skip_metadata_run_prints_no_summary(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    run_cli("sync", "demo", "--skip-download")

    result = run_cli("sync", "demo", "--skip-metadata")

    assert result.stdout.strip() == ""
