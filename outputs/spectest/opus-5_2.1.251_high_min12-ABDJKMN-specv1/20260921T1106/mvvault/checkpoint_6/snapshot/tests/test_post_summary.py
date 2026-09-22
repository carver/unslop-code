"""Spec section: `sync` Post-Summary / Determinism (post-sync counts)."""
import re

from conftest import entry, make_vault, payload, v2_catalog, v2_entry


def init(run, source, name="v"):
    assert run("init", name, source.url).returncode == 0
    return name


def counts(text):
    """The three integers reported by the post-sync summary, in order.

    Read from the counts line alone: since the viewer-link spec, the summary
    also carries changed-entry lines whose URLs contain digits.
    """
    for line in text.splitlines():
        if "added" in line and "removed" in line and "updated" in line:
            numbers = [int(n) for n in re.findall(r"\d+", line)]
            assert len(numbers) >= 3, "summary line lacks three counts: %r" % line
            return numbers[:3]
    raise AssertionError("no post-sync counts line: %r" % text)


def sync(run, name="v", *options):
    result = run("sync", name, "--skip-download", *options)
    assert result.returncode == 0, result.stderr
    return result


# Phrase: "Trigger | Successful `sync` run that includes metadata phase" +
#         "Output stream | stdout"
def test_summary_printed_on_stdout_after_sync(run, source, tmp_path):
    init(run, source)
    source.payload = payload(episodes=[entry("e1")])
    result = sync(run)
    assert result.stdout.strip(), "no post-sync summary on stdout"


# Phrase: "Counts reported | Added, removed, updated"
# Context: a first sync of one entry adds exactly one.
def test_first_sync_reports_one_addition(run, source, tmp_path):
    init(run, source)
    source.payload = payload(episodes=[entry("e1")])
    assert counts(sync(run).stdout) == [1, 0, 0]


# Phrase: "Counts reported | Added, removed, updated"
# Context: additions are counted across every category.
def test_additions_counted_across_categories(run, source, tmp_path):
    init(run, source)
    source.payload = payload(episodes=[entry("e1"), entry("e2")],
                             streams=[entry("s1")], clips=[entry("c1")])
    assert counts(sync(run).stdout) == [4, 0, 0]


# Phrase: "Counts reported | Added, removed, updated"
# Context: an entry that disappears from the source is a removal.
def test_removal_counted(run, source, tmp_path):
    init(run, source)
    source.payload = payload(episodes=[entry("e1"), entry("e2")])
    sync(run)
    source.payload = payload(episodes=[entry("e1")])
    assert counts(sync(run).stdout) == [0, 1, 0]


# Phrase: "Counts reported | Added, removed, updated"
# Context: a changed tracked field on an existing entry is an update.
def test_update_counted(run, source, tmp_path):
    init(run, source)
    source.payload = payload(episodes=[entry("e1", title="One")])
    sync(run)
    source.payload = payload(episodes=[entry("e1", title="Two")])
    assert counts(sync(run).stdout) == [0, 0, 1]


# Phrase: "Counts reported | Added, removed, updated"
# Context: an unchanged entry contributes to none of the three counts.
def test_unchanged_entry_counts_nowhere(run, source, tmp_path):
    init(run, source)
    source.payload = payload(episodes=[entry("e1", title="Same")])
    sync(run)
    assert counts(sync(run).stdout) == [0, 0, 0]


# Phrase: "Counts reported | Added, removed, updated"
# Context: all three kinds in one run.
def test_all_three_counts_in_one_run(run, source, tmp_path):
    init(run, source)
    source.payload = payload(episodes=[entry("e1", title="A"),
                                       entry("e2", title="B")])
    sync(run)
    source.payload = payload(episodes=[entry("e1", title="A2"),
                                       entry("e3", title="C")])
    assert counts(sync(run).stdout) == [1, 1, 1]


# Phrase: "Trigger | Successful `sync` run that includes metadata phase"
# Context: `--skip-metadata` has no metadata phase, so no summary is produced.
def test_no_summary_when_metadata_phase_is_skipped(run, source, tmp_path):
    init(run, source)
    source.payload = payload(episodes=[entry("e1")])
    sync(run)
    result = run("sync", "v", "--skip-metadata")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ""


# Phrase: "Trigger | Successful `sync` run that includes metadata phase"
# Context: `--skip-download` still runs the metadata phase, so it still reports.
def test_summary_reported_with_skip_download(run, source, tmp_path):
    init(run, source)
    source.payload = payload(episodes=[entry("e1")])
    result = run("sync", "v", "--skip-download")
    assert result.returncode == 0, result.stderr
    assert counts(result.stdout) == [1, 0, 0]


# Phrase: "Post-sync counts | Deterministic for the same vault state and
#          source metadata"
def test_counts_are_deterministic_for_the_same_inputs(run, source, tmp_path):
    for name in ("a", "b"):
        init(run, source, name)
    source.payload = payload(episodes=[entry("e1"), entry("e2")],
                             clips=[entry("c1")])
    first = sync(run, "a").stdout
    second = sync(run, "b").stdout
    assert counts(first) == counts(second) == [3, 0, 0]


# Phrase: "Trigger | Successful `sync` run that includes metadata phase"
# Context: a legacy vault migrated during the metadata phase still reports; its
# migrated entries already exist, so re-observing them adds nothing.
def test_summary_after_legacy_migration(run, source, tmp_path):
    make_vault(tmp_path, "v", v2_catalog(source=source.url,
                                         episodes=[v2_entry("e1", title="T")]))
    # e1's source values match what the v2 fixture already recorded, so the
    # only notable change is the new e2.
    same = entry("e1", title="T", description="D", views=5, likes=1, preview="p")
    source.payload = payload(episodes=[same, entry("e2")])
    result = run("sync", "v", "--skip-download")
    assert result.returncode == 0, result.stderr
    assert counts(result.stdout) == [1, 0, 0]


# Phrase: "Output stream | stdout"
# Context: a failed sync produces no summary at all.
def test_no_summary_when_sync_fails(run, source, tmp_path):
    init(run, source)
    source.status = 500
    result = run("sync", "v")
    assert result.returncode != 0
    assert result.stdout.strip() == ""


# Phrase: "Successful run with skipped downloads due to download failures |
#          Exit code `0`"
# Context: the summary is still printed when downloads fail.
def test_summary_printed_despite_download_failures(run, source, tmp_path):
    init(run, source)
    source.payload = payload(episodes=[entry("e1")])
    result = run("sync", "v")             # no asset routes -> 404
    assert result.returncode == 0
    assert counts(result.stdout) == [1, 0, 0]
