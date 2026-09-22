"""Spec sections: `digest` and Post-Sync Viewer Links (post-sync side) and
Post-Sync Viewer Link -- Version-Aware Category."""

from conftest import (
    EPOCH_KEY,
    ISO_KEY,
    legacy_entry,
    source_entry,
    v1_catalog,
    v2_catalog,
    write_vault,
)
from mvaultlib.catalog import load_vault
from mvaultlib.entries import CATEGORIES
from mvaultlib.sync import ADDED, SyncSummary

#: The default viewer endpoint every report link is built on.
VIEWER = "http://127.0.0.1:8840"


def line_with(stdout, needle):
    matches = [line for line in stdout.splitlines() if needle in line]
    assert len(matches) == 1, f"expected one line with {needle} in {stdout}"
    return matches[0]


# Spec: "| Post-sync summary | Each changed-entry line includes viewer link on
# same line as title |" and "| Link format |
# `http://<host>:<port>/catalog/<name>/<category>/<id>` |".
def test_added_entry_line_carries_the_viewer_link(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])

    result = run_cli("sync", "demo", "--skip-download")

    assert result.returncode == 0, result.stderr
    assert f"{VIEWER}/catalog/demo/episodes/e1" in line_with(result.stdout, "title-e1")


# Spec: "| Post-sync summary | Each changed-entry line includes viewer link on
# same line as title |" -- updated and removed entries are changed entries too.
def test_updated_and_removed_lines_carry_links(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1"), source_entry("e2")])
    run_cli("sync", "demo", "--skip-download")
    source.serve(episodes=[source_entry("e1", title="new title")])

    result = run_cli("sync", "demo", "--skip-download")

    assert f"{VIEWER}/catalog/demo/episodes/e1" in line_with(result.stdout, "new title")
    assert f"{VIEWER}/catalog/demo/episodes/e2" in line_with(result.stdout, "title-e2")


# Spec: "| v3 vault after `sync` | Category where entry resides (`episodes`,
# `streams`, or `clips`) |".
def test_v3_sync_links_name_the_residing_category(run_cli, source, vault):
    source.serve(
        episodes=[source_entry("e1")], streams=[source_entry("s1")], clips=[source_entry("c1")]
    )

    result = run_cli("sync", "demo", "--skip-download")

    assert f"{VIEWER}/catalog/demo/episodes/e1" in line_with(result.stdout, "title-e1")
    assert f"{VIEWER}/catalog/demo/streams/s1" in line_with(result.stdout, "title-s1")
    assert f"{VIEWER}/catalog/demo/clips/c1" in line_with(result.stdout, "title-c1")


# Spec: "| v2 vault after `sync` | Category where entry resides (`episodes`,
# `streams`, or `clips`) |".
def test_v2_sync_links_name_the_residing_category(run_cli, source, tmp_path):
    catalog = v2_catalog(source.url, streams=[legacy_entry("s1", ISO_KEY)])
    write_vault(tmp_path, "legacy", catalog)
    source.serve(streams=[source_entry("s1", title="new title")], clips=[source_entry("c1")])

    result = run_cli("sync", "legacy", "--skip-download")

    assert result.returncode == 0, result.stderr
    assert f"{VIEWER}/catalog/legacy/streams/s1" in line_with(result.stdout, "new title")
    assert f"{VIEWER}/catalog/legacy/clips/c1" in line_with(result.stdout, "title-c1")


# Spec: "| v1 vault after `sync` auto-migrates it to v3 | `episodes` for
# migrated episode entries |". A v1 vault's source URL is derived as
# `https://media.example.com/...`, which a local test cannot serve, so this
# drives the same code the run does: the migrated catalog a sync merges into,
# and the summary rendered from it.
def test_v1_entries_are_summarised_under_episodes(tmp_path):
    write_vault(tmp_path, "legacy", v1_catalog(legacy_entry("e1", EPOCH_KEY)))
    catalog = load_vault(str(tmp_path / "legacy")).catalog

    summary = SyncSummary()
    for category in CATEGORIES:
        for entry in catalog[category]:
            summary.record(ADDED, category, entry)

    assert f"{VIEWER}/catalog/legacy/episodes/e1" in line_with(summary.render("legacy"), "title-e1")


# Spec: "| Post-sync summary | Each changed-entry line includes viewer link on
# same line as title |" -- a run that changed nothing has no entry lines.
def test_unchanged_sync_reports_no_entry_links(run_cli, source, vault):
    source.serve(episodes=[source_entry("e1")])
    run_cli("sync", "demo", "--skip-download")

    result = run_cli("sync", "demo", "--skip-download")

    assert VIEWER not in result.stdout
