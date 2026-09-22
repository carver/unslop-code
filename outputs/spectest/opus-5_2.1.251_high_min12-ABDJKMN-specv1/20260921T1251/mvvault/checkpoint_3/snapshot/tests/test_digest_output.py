"""Spec sections: `digest` Output Layout and the digest rows of Determinism."""

from __future__ import annotations


# ---------------------------------------------------------------------------
# | Category grouping | Changes grouped by category (v1: single `Entries`
#   group; v2/v3: per-category) |
# ---------------------------------------------------------------------------

# Spec: | Category grouping | ... v2/v3: per-category |
def test_v3_changes_are_grouped_per_category(
    run_cli, make_vault, catalogs, digest
):
    make_vault(catalogs.catalog(
        episodes=[catalogs.entry("e1")],
        streams=[catalogs.entry("s1")],
        clips=[catalogs.entry("c1")],
    ))
    result = run_cli("digest", "vault")
    headers = digest.headers(result.stdout)
    assert "Episodes" in headers
    assert "Streams" in headers
    assert "Clips" in headers


# Spec: | Category grouping | ... |
# Context: each entry is listed under its own category.
def test_v3_entries_appear_under_their_category(
    run_cli, make_vault, catalogs, digest
):
    make_vault(catalogs.catalog(
        episodes=[catalogs.entry("e1")], clips=[catalogs.entry("c1")]))
    result = run_cli("digest", "vault")
    episodes = "\n".join(digest.section(result.stdout, "Episodes"))
    clips = "\n".join(digest.section(result.stdout, "Clips"))
    assert "Title e1" in episodes and "Title c1" not in episodes
    assert "Title c1" in clips and "Title e1" not in clips


# Spec: | Category grouping | ... (v1: single `Entries` group ...) |
def test_v1_uses_a_single_entries_group(run_cli, make_vault, legacy, digest):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    result = run_cli("digest", "vault")
    headers = digest.headers(result.stdout)
    assert "Entries" in headers
    assert "Episodes" not in headers
    assert "Streams" not in headers
    assert "Clips" not in headers


# Spec: | v2 | `Episodes`, `Streams`, `Clips` | ... |
def test_v2_uses_per_category_groups(run_cli, make_vault, legacy, digest):
    make_vault(legacy.v2_catalog(
        episodes=[legacy.v2_entry("e1")], streams=[legacy.v2_entry("s1")]))
    result = run_cli("digest", "vault")
    headers = digest.headers(result.stdout)
    assert "Episodes" in headers and "Streams" in headers
    assert "Entries" not in headers


# ---------------------------------------------------------------------------
# | Grouping within category | Changes grouped by type |
# ---------------------------------------------------------------------------

# Spec: | Grouping within category | Changes grouped by type |
def test_changes_are_grouped_by_type_within_a_category(
    run_cli, make_vault, catalogs, digest
):
    added = catalogs.entry("e1")
    updated = catalogs.entry("e2")
    updated["title"] = {catalogs.STAMP_1: "Old", catalogs.STAMP_2: "Updated e2"}
    removed = catalogs.entry("e3")
    removed["removed"] = {catalogs.STAMP_1: False, catalogs.STAMP_2: True}
    make_vault(catalogs.catalog(episodes=[added, updated, removed]))
    result = run_cli("digest", "vault")
    assert any("Title e1" in line
               for line in digest.group(result.stdout, "Episodes", "Additions"))
    assert any("Updated e2" in line
               for line in digest.group(result.stdout, "Episodes", "Field updates"))
    assert any("Title e3" in line
               for line in digest.group(result.stdout, "Episodes", "Removals"))


# ---------------------------------------------------------------------------
# | Entry text | Current title from latest `title` history value |
# ---------------------------------------------------------------------------

# Spec: | Entry text | Current title from latest `title` history value |
def test_entry_text_is_the_current_title(run_cli, make_vault, catalogs, digest):
    entry = catalogs.entry("e1")
    entry["title"] = {catalogs.STAMP_1: "Stale Title",
                      catalogs.STAMP_2: "Current Title"}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    lines = digest.group(result.stdout, "Episodes", "Field updates")
    assert any("Current Title" in line for line in lines)
    assert "Stale Title" not in result.stdout


# Spec: | Entry text | Current title from latest `title` history value |
# Context: a removed entry is still named by its latest known title.
def test_removed_entry_text_is_its_latest_title(
    run_cli, make_vault, catalogs, digest
):
    entry = catalogs.entry("e1")
    entry["title"] = {catalogs.STAMP_1: "Gone Title"}
    entry["removed"] = {catalogs.STAMP_1: False, catalogs.STAMP_2: True}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert any("Gone Title" in line
               for line in digest.group(result.stdout, "Episodes", "Removals"))


# ---------------------------------------------------------------------------
# | Field-update suffix | Changed field names in parentheses after title |
# ---------------------------------------------------------------------------

# Spec: | Field-update suffix | Changed field names in parentheses after title |
def test_field_update_names_the_changed_field_in_parentheses(
    run_cli, make_vault, catalogs, digest
):
    entry = catalogs.entry("e1")
    entry["views"] = {catalogs.STAMP_1: 1, catalogs.STAMP_2: 2}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    line = digest.group(result.stdout, "Episodes", "Field updates")[0]
    assert "Title e1" in line
    suffix = line[line.index("("):]
    assert suffix.startswith("(") and suffix.rstrip().endswith(")")
    assert "views" in suffix
    assert line.index("Title e1") < line.index("(")


# Spec: | Field-update suffix | Changed field names in parentheses ... |
# Context: several changed fields are all named.
def test_field_update_names_every_changed_field(
    run_cli, make_vault, catalogs, digest
):
    entry = catalogs.entry("e1")
    entry["views"] = {catalogs.STAMP_1: 1, catalogs.STAMP_2: 2}
    entry["likes"] = {catalogs.STAMP_1: 1, catalogs.STAMP_2: 3}
    entry["description"] = {catalogs.STAMP_1: "a", catalogs.STAMP_2: "b"}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    line = digest.group(result.stdout, "Episodes", "Field updates")[0]
    for field in ("views", "likes", "description"):
        assert field in line, line


# Spec: | Field-update suffix | Changed field names ... |
# Context: fields whose latest two values match are not named.
def test_field_update_omits_unchanged_fields(
    run_cli, make_vault, catalogs, digest
):
    entry = catalogs.entry("e1")
    entry["views"] = {catalogs.STAMP_1: 1, catalogs.STAMP_2: 2}
    entry["likes"] = {catalogs.STAMP_1: 7, catalogs.STAMP_2: 7}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    line = digest.group(result.stdout, "Episodes", "Field updates")[0]
    assert "views" in line
    assert "likes" not in line


# ---------------------------------------------------------------------------
# | Reappearance after removal (v3 only) | Indicate reappearance alongside any
#   other changed fields |
# ---------------------------------------------------------------------------

# Spec: | Reappearance after removal (v3 only) | Indicate reappearance ... |
def test_reappearance_is_indicated(run_cli, make_vault, catalogs, digest):
    entry = catalogs.entry("e1")
    entry["removed"] = {
        catalogs.STAMP_1: False, catalogs.STAMP_2: True, catalogs.STAMP_3: False}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    body = "\n".join(digest.lines(result.stdout)).lower()
    assert "reappear" in body, result.stdout


# Spec: | Reappearance after removal (v3 only) | Indicate reappearance
#   alongside any other changed fields |
def test_reappearance_is_listed_with_other_changed_fields(
    run_cli, make_vault, catalogs, digest
):
    entry = catalogs.entry("e1")
    entry["removed"] = {
        catalogs.STAMP_1: False, catalogs.STAMP_2: True, catalogs.STAMP_3: False}
    entry["views"] = {catalogs.STAMP_1: 1, catalogs.STAMP_3: 9}
    make_vault(catalogs.catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    line = [ln for ln in digest.lines(result.stdout) if "Title e1" in ln][0]
    assert "reappear" in line.lower()
    assert "views" in line


# Spec: | Reappearance after removal (v3 only) | ... |
# Context: a v1/v2 vault has no `removed` field and so never reappears.
def test_no_reappearance_reported_for_v2(run_cli, make_vault, legacy):
    entry = legacy.v2_entry("e1")
    entry["views"] = {"2024-06-15T09:40:00": 1, "2024-06-16T09:40:00": 2}
    make_vault(legacy.v2_catalog(episodes=[entry]))
    result = run_cli("digest", "vault")
    assert "reappear" not in result.stdout.lower()


# ---------------------------------------------------------------------------
# | Empty category | Omitted |
# | No notable changes anywhere | Indicate that no notable changes were found |
# ---------------------------------------------------------------------------

# Spec: | Empty category | Omitted |
def test_category_without_changes_is_omitted(
    run_cli, make_vault, catalogs, digest
):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    result = run_cli("digest", "vault")
    headers = digest.headers(result.stdout)
    assert "Episodes" in headers
    assert "Streams" not in headers
    assert "Clips" not in headers


# Spec: | Empty category | Omitted |
# Context: a category whose entries have no notable change is also omitted.
def test_category_with_only_unremarkable_entries_is_omitted(
    run_cli, make_vault, catalogs, digest
):
    quiet = catalogs.entry("s1")
    quiet["views"] = {catalogs.STAMP_1: 5, catalogs.STAMP_2: 5}
    make_vault(catalogs.catalog(
        episodes=[catalogs.entry("e1")], streams=[quiet]))
    result = run_cli("digest", "vault")
    assert "Streams" not in digest.headers(result.stdout)


# Spec: | No notable changes anywhere | Indicate that no notable changes were
#   found |
def test_empty_vault_reports_no_notable_changes(run_cli, make_vault, catalogs):
    make_vault(catalogs.catalog())
    result = run_cli("digest", "vault")
    assert result.returncode == 0, result.stderr
    assert "no notable changes" in result.stdout.lower()


# Spec: | No notable changes anywhere | Indicate that no notable changes were
#   found |
# Context: entries that exist but changed nothing notable also produce the
# no-changes message.
def test_vault_without_notable_changes_reports_none(
    run_cli, make_vault, catalogs
):
    quiet = catalogs.entry("e1")
    quiet["views"] = {catalogs.STAMP_1: 5, catalogs.STAMP_2: 5}
    make_vault(catalogs.catalog(episodes=[quiet]))
    result = run_cli("digest", "vault")
    assert "no notable changes" in result.stdout.lower()


# ---------------------------------------------------------------------------
# | Trailing line | Metadata about the digest run |
# | Source reference | The trailing line includes the resolved source URL ... |
# ---------------------------------------------------------------------------

# Spec: | Trailing line | Metadata about the digest run |
def test_trailing_line_is_last(run_cli, make_vault, catalogs, source, digest):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    result = run_cli("digest", "vault")
    assert source.url in digest.trailing(result.stdout)
    assert "Title e1" not in digest.trailing(result.stdout)


# Spec: | Trailing line | Metadata about the digest run |
# Context: present even when there are no notable changes.
def test_trailing_line_present_without_changes(
    run_cli, make_vault, catalogs, source, digest
):
    make_vault(catalogs.catalog())
    result = run_cli("digest", "vault")
    assert source.url in digest.trailing(result.stdout)


# Spec: | Digest trailing line | Deterministic format |
def test_trailing_line_format_is_stable(run_cli, make_vault, catalogs, digest):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    first = digest.trailing(run_cli("digest", "vault").stdout)
    second = digest.trailing(run_cli("digest", "vault").stdout)
    assert first.split() [:3] == second.split()[:3]
    assert len(first.split()) == len(second.split())


# ---------------------------------------------------------------------------
# | Digest category order | Deterministic |
# | Digest group order | Deterministic |
# | Digest entry order | Deterministic |
# ---------------------------------------------------------------------------

# Spec: | Digest category order | Deterministic |
def test_category_order_is_stable_across_runs(
    run_cli, make_vault, catalogs, digest
):
    make_vault(catalogs.catalog(
        episodes=[catalogs.entry("e1")],
        streams=[catalogs.entry("s1")],
        clips=[catalogs.entry("c1")],
    ))
    first = digest.headers(run_cli("digest", "vault").stdout)
    second = digest.headers(run_cli("digest", "vault").stdout)
    assert first == second
    categories = [h for h in first if h in ("Episodes", "Streams", "Clips")]
    assert len(categories) == 3


# Spec: | Digest group order | Deterministic |
def test_group_order_is_stable_across_runs(run_cli, make_vault, catalogs, digest):
    added = catalogs.entry("e1")
    updated = catalogs.entry("e2")
    updated["views"] = {catalogs.STAMP_1: 1, catalogs.STAMP_2: 2}
    removed = catalogs.entry("e3")
    removed["removed"] = {catalogs.STAMP_1: False, catalogs.STAMP_2: True}
    make_vault(catalogs.catalog(episodes=[added, updated, removed]))
    first = digest.headers(run_cli("digest", "vault").stdout)
    second = digest.headers(run_cli("digest", "vault").stdout)
    assert first == second
    assert {"Additions", "Removals", "Field updates"} <= set(first)


# Spec: | Digest entry order | Deterministic |
def test_entry_order_is_stable_across_runs(run_cli, make_vault, catalogs, digest):
    entries = [catalogs.entry(f"e{n}") for n in range(1, 5)]
    make_vault(catalogs.catalog(episodes=entries))
    first = digest.group(run_cli("digest", "vault").stdout, "Episodes", "Additions")
    second = digest.group(run_cli("digest", "vault").stdout, "Episodes", "Additions")
    assert first == second
    assert len(first) == 4


# Spec: | Digest entry order | Deterministic |
# Context: the whole body (everything but the trailing line) is reproducible.
def test_digest_body_is_reproducible(run_cli, make_vault, catalogs, digest):
    entries = [catalogs.entry(f"e{n}") for n in range(1, 4)]
    entries[0]["views"] = {catalogs.STAMP_1: 1, catalogs.STAMP_2: 2}
    make_vault(catalogs.catalog(episodes=entries, clips=[catalogs.entry("c1")]))
    first = digest.lines(run_cli("digest", "vault").stdout)
    second = digest.lines(run_cli("digest", "vault").stdout)
    assert first == second


# Spec: | Digest entry order | Deterministic |
# Context: the order does not depend on JSON key order inside a history.
def test_entry_order_ignores_history_key_order(
    run_cli, make_vault, catalogs, digest
):
    first_entry = catalogs.entry("e1")
    first_entry["title"] = {catalogs.STAMP_2: "B title", catalogs.STAMP_1: "A"}
    second_entry = catalogs.entry("e2")
    second_entry["title"] = {catalogs.STAMP_1: "C", catalogs.STAMP_2: "D title"}
    make_vault(catalogs.catalog(episodes=[first_entry, second_entry]))
    result = run_cli("digest", "vault")
    lines = digest.group(result.stdout, "Episodes", "Field updates")
    assert [ln.split("(")[0].strip() for ln in lines][0].endswith("B title")
