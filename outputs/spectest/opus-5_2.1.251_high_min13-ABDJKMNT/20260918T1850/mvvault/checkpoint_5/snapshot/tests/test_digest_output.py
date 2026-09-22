"""Spec sections: `digest` Output Layout, Determinism (digest ordering)."""

from conftest import V2_LATER, V2_STAMP, v3_catalog, v3_entry, write_vault

LATEST = "2024-06-17T09:40:00"


def lines(stdout):
    return [line for line in stdout.splitlines() if line.strip()]


def index_of(stdout, needle):
    """Index of the first line containing `needle`."""
    return next(i for i, line in enumerate(lines(stdout)) if needle in line)


# Spec: Category grouping | Changes grouped by category
# Spec: Digest category order | Deterministic
def test_categories_appear_in_catalog_order(run, tmp_path):
    catalog = v3_catalog(
        episodes=[v3_entry("e1")], streams=[v3_entry("s1")], clips=[v3_entry("c1")]
    )
    write_vault(tmp_path, catalog)
    stdout = run("digest", "vault").stdout
    assert index_of(stdout, "Episodes") < index_of(stdout, "Streams") < index_of(stdout, "Clips")


# Spec: Empty category | Omitted
def test_category_without_changes_is_omitted(run, tmp_path):
    write_vault(tmp_path, v3_catalog(clips=[v3_entry("c1")]))
    stdout = run("digest", "vault").stdout
    assert "Clips" in stdout
    assert "Episodes" not in stdout
    assert "Streams" not in stdout


# Spec: Grouping within category | Changes grouped by type
# Spec: Digest group order | Deterministic (removals, then additions, then updates)
def test_groups_are_ordered_by_precedence(run, tmp_path):
    entries = [
        v3_entry("e1", title={V2_STAMP: "Old", V2_LATER: "Updated one"}),
        v3_entry("e2"),
        v3_entry("e3", removed={V2_STAMP: False, V2_LATER: True}),
    ]
    write_vault(tmp_path, v3_catalog(episodes=entries))
    stdout = run("digest", "vault").stdout
    assert index_of(stdout, "Removed") < index_of(stdout, "Added") < index_of(stdout, "Updated")


# Spec: Entry order within group | Deterministic (catalog order)
def test_entries_within_a_group_follow_catalog_order(run, tmp_path):
    entries = [v3_entry("e2"), v3_entry("e1"), v3_entry("e3")]
    write_vault(tmp_path, v3_catalog(episodes=entries))
    stdout = run("digest", "vault").stdout
    assert index_of(stdout, "Title e2") < index_of(stdout, "Title e1") < index_of(stdout, "Title e3")


# Spec: Digest entry order | Deterministic (repeated runs agree)
def test_digest_output_is_stable_across_runs(run, tmp_path):
    entries = [v3_entry("e1"), v3_entry("e2", views={V2_STAMP: 1, V2_LATER: 4})]
    write_vault(tmp_path, v3_catalog(episodes=entries, clips=[v3_entry("c1")]))
    first = run("digest", "vault").stdout.splitlines()
    second = run("digest", "vault").stdout.splitlines()
    assert first[:-1] == second[:-1]


# Spec: Entry text | Current title from latest `title` history value
def test_entry_text_is_the_current_title(run, tmp_path):
    entry = v3_entry("e1", title={V2_STAMP: "Working title", V2_LATER: "Final title"})
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    stdout = run("digest", "vault").stdout
    assert "Final title" in stdout
    assert "Working title" not in stdout


# Spec: Field-update suffix | Changed field names in parentheses after title
def test_field_update_suffix_lists_changed_fields(run, tmp_path):
    entry = v3_entry(
        "e1",
        title={V2_STAMP: "Old", V2_LATER: "New title"},
        views={V2_STAMP: 1, V2_LATER: 4},
    )
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    assert "New title (title, views)" in run("digest", "vault").stdout


# Spec: Field-update suffix | ... only the fields that actually changed are listed
def test_unchanged_fields_are_not_listed(run, tmp_path):
    entry = v3_entry("e1", likes={V2_STAMP: 2, V2_LATER: 9})
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    stdout = run("digest", "vault").stdout
    assert "(likes)" in stdout
    assert "description" not in stdout


# Spec: Reappearance after removal (v3 only) | Indicate reappearance
def test_reappearance_is_indicated(run, tmp_path):
    entry = v3_entry("e1", removed={V2_STAMP: False, V2_LATER: True, LATEST: False})
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    stdout = run("digest", "vault").stdout
    assert "Title e1" in stdout
    assert "reappear" in stdout.lower()


# Spec: Reappearance after removal | ... alongside any other changed fields
def test_reappearance_is_listed_with_other_changed_fields(run, tmp_path):
    entry = v3_entry(
        "e1",
        views={V2_STAMP: 1, V2_LATER: 7},
        removed={V2_STAMP: False, V2_LATER: True, LATEST: False},
    )
    write_vault(tmp_path, v3_catalog(episodes=[entry]))
    suffix = run("digest", "vault").stdout
    assert "reappear" in suffix.lower()
    assert "views" in suffix


# Spec: Trailing line | Metadata about the digest run
def test_trailing_line_is_last_and_mentions_the_vault(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]), name="archive")
    stdout = run("digest", "archive").stdout
    assert "archive" in lines(stdout)[-1]


# Spec: Source reference | The trailing line includes the resolved source URL
def test_trailing_line_includes_the_source_url(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")], source="http://s.invalid/x.json"))
    stdout = run("digest", "vault").stdout
    assert "http://s.invalid/x.json" in lines(stdout)[-1]


# Spec: No notable changes anywhere | Indicate that no notable changes were found
# (the trailing line is still printed)
def test_trailing_line_printed_when_nothing_changed(run, tmp_path):
    write_vault(tmp_path, v3_catalog(source="http://s.invalid/x.json"))
    stdout = run("digest", "vault").stdout
    assert "no notable changes" in stdout.lower()
    assert "http://s.invalid/x.json" in lines(stdout)[-1]


# Spec: Digest trailing line | Deterministic format
def test_trailing_line_format_is_stable(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    shapes = set()
    for _ in range(2):
        last = lines(run("digest", "vault").stdout)[-1]
        shapes.add("".join("#" if character.isdigit() else character for character in last))
    assert len(shapes) == 1
