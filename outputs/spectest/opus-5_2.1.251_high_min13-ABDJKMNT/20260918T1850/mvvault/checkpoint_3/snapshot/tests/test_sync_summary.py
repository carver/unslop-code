"""Spec section: `sync` Post-Summary."""

import re

from conftest import payload, source_entry


def counts(stdout):
    """The added/removed/updated numbers reported by a sync run."""
    return {
        label: int(re.search(rf"(\d+)\s+{label}", stdout).group(1))
        for label in ("added", "removed", "updated")
    }


# Spec: Trigger | Successful `sync` run that includes metadata phase; Output stream | stdout
def test_successful_sync_prints_a_summary_on_stdout(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_assets("e1")
    result = run("sync", "vault")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


# Spec: Counts reported | Added, removed, updated
def test_summary_reports_additions(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1"), source_entry("e2")]))
    source.serve_assets("e1", "e2")
    assert counts(run("sync", "vault").stdout) == {"added": 2, "removed": 0, "updated": 0}


# Spec: Counts reported | Added, removed, updated
def test_summary_reports_updates(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_assets("e1")
    run("sync", "vault")

    source.serve(payload(episodes=[source_entry("e1", views=99)]))
    assert counts(run("sync", "vault").stdout) == {"added": 0, "removed": 0, "updated": 1}


# Spec: Counts reported | Added, removed, updated
def test_summary_reports_removals(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_assets("e1")
    run("sync", "vault")

    source.serve(payload())
    assert counts(run("sync", "vault").stdout) == {"added": 0, "removed": 1, "updated": 0}


# Spec: Counts reported | ... an unchanged entry counts in no group
def test_unchanged_entry_is_not_counted(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_assets("e1")
    run("sync", "vault")
    assert counts(run("sync", "vault").stdout) == {"added": 0, "removed": 0, "updated": 0}


# Spec: Trigger | Successful `sync` run that includes metadata phase
def test_skip_metadata_run_prints_no_summary(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    source.serve_assets("e1")
    run("sync", "vault", "--skip-download")
    assert run("sync", "vault", "--skip-metadata").stdout == ""


# Spec: Trigger | ... a metadata-only run still reports its counts
def test_skip_download_run_still_prints_a_summary(run, source, vault):
    source.serve(payload(episodes=[source_entry("e1")]))
    assert counts(run("sync", "vault", "--skip-download").stdout)["added"] == 1


# Spec: Post-sync counts | Deterministic for the same vault state and source metadata
def test_counts_are_deterministic(run, source, tmp_path):
    source.serve(payload(episodes=[source_entry("e1")], clips=[source_entry("c1")]))
    source.serve_assets("e1", "c1")
    outputs = []
    for name in ("a", "b"):
        assert run("init", name, source.url).returncode == 0
        outputs.append(counts(run("sync", name).stdout))
    assert outputs[0] == outputs[1]


# Spec: Counts reported | Added, removed, updated (counts span every category)
def test_counts_span_all_categories(run, source, vault):
    source.serve(
        payload(
            episodes=[source_entry("e1")],
            streams=[source_entry("s1")],
            clips=[source_entry("c1")],
        )
    )
    source.serve_assets("e1", "s1", "c1")
    assert counts(run("sync", "vault").stdout)["added"] == 3
