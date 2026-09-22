"""Spec: `digest` Output Layout and the digest Determinism rows."""
from digest_helpers import (K1, K2, K3, E1, E2, E3, v1, v2, v3, v3_entry,
                            legacy_entry, v1_entry, sections, entry_titles,
                            trailing_line)


# Spec: "| Category grouping | Changes grouped by category (v1: single
# `Entries` group; v2/v3: per-category) |" -- v3 per-category.
def test_v3_groups_by_category(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Ep")],
                  streams=[v3_entry(id="s1", title="St")],
                  clips=[v3_entry(id="c1", title="Cl")]))
    parsed = sections(run("digest", "vault").stdout)
    assert list(parsed) == ["Episodes", "Streams", "Clips"]
    assert parsed["Episodes"]["Added"] == ["Ep"]
    assert parsed["Streams"]["Added"] == ["St"]
    assert parsed["Clips"]["Added"] == ["Cl"]


# Spec: "| v2 | `Episodes`, `Streams`, `Clips` |"
def test_v2_groups_by_category(run, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1", title="Ep")],
                  clips=[legacy_entry(id="c1", title="Cl")]))
    parsed = sections(run("digest", "vault").stdout)
    assert list(parsed) == ["Episodes", "Clips"]


# Spec: "| v1 | Single group: `Entries` |"
def test_v1_uses_a_single_entries_group(run, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", title="One"),
                           v1_entry(id="e2", title="Two")]))
    parsed = sections(run("digest", "vault").stdout)
    assert list(parsed) == ["Entries"]
    assert parsed["Entries"]["Added"] == ["One", "Two"]


# Spec: "| Empty category | Omitted |" -- a category with no changes at all.
def test_empty_category_omitted(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Ep")]))
    assert list(sections(run("digest", "vault").stdout)) == ["Episodes"]


# Spec: "| Empty category | Omitted |" -- a category whose entries exist but
# have no notable changes is omitted too.
def test_category_with_only_unchanged_entries_omitted(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Ep")],
                  streams=[v3_entry(id="s1", title={K1: "S", K2: "S"})]))
    assert list(sections(run("digest", "vault").stdout)) == ["Episodes"]


# Spec: "| Grouping within category | Changes grouped by type |"
def test_changes_grouped_by_type_within_category(run, make_vault):
    make_vault(v3(episodes=[
        v3_entry(id="e1", title="Added One"),
        v3_entry(id="e2", title={K1: "x", K2: "Updated One"}),
        v3_entry(id="e3", title="Removed One", removed={K1: False, K2: True}),
    ]))
    groups = sections(run("digest", "vault").stdout)["Episodes"]
    assert groups["Removed"] == ["Removed One"]
    assert groups["Added"] == ["Added One"]
    assert groups["Updated"] == ["Updated One (title)"]


# Spec: "| Digest group order | Deterministic |" -- groups follow the
# documented precedence order: removals, additions, field updates.
def test_group_order_is_deterministic(run, make_vault):
    make_vault(v3(episodes=[
        v3_entry(id="e1", title={K1: "x", K2: "Upd"}),
        v3_entry(id="e2", title="Add"),
        v3_entry(id="e3", title="Rem", removed={K1: False, K2: True}),
    ]))
    groups = sections(run("digest", "vault").stdout)["Episodes"]
    assert list(groups) == ["Removed", "Added", "Updated"]


# Spec: "| Digest category order | Deterministic |" -- categories follow the
# catalog's own category order regardless of which ones carry changes.
def test_category_order_is_deterministic(run, make_vault):
    make_vault(v3(clips=[v3_entry(id="c1", title="C")],
                  episodes=[v3_entry(id="e1", title="E")],
                  streams=[v3_entry(id="s1", title="S")]))
    assert list(sections(run("digest", "vault").stdout)) == \
        ["Episodes", "Streams", "Clips"]


# Spec: "| Entry order within group | Deterministic |" -- catalog order.
def test_entry_order_within_group_is_catalog_order(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e%d" % n, title="T%d" % n)
                            for n in (3, 1, 2)]))
    assert entry_titles(run("digest", "vault").stdout, "Episodes", "Added") \
        == ["T3", "T1", "T2"]


# Spec: "| Digest entry order | Deterministic |" -- repeated runs agree.
def test_digest_output_is_stable_across_runs(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="A"),
                            v3_entry(id="e2", title={K1: "x", K2: "B"})],
                  clips=[v3_entry(id="c1", title="C",
                                  removed={K1: False, K2: True})]))
    first = run("digest", "vault").stdout
    second = run("digest", "vault").stdout
    assert sections(first) == sections(second)


# Spec: "| Entry text | Current title from latest `title` history value |"
def test_entry_text_is_the_latest_title(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1",
                                     title={K1: "First", K3: "Latest",
                                            K2: "Middle"})]))
    assert entry_titles(run("digest", "vault").stdout, "Episodes", "Updated") \
        == ["Latest (title)"]


# Spec: "| Field-update suffix | Changed field names in parentheses after
# title |"
def test_field_update_suffix_is_in_parentheses(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="T",
                                     views={K1: 1, K2: 2})]))
    line = entry_titles(run("digest", "vault").stdout, "Episodes", "Updated")[0]
    assert line == "T (views)"


# Spec: "Field-update suffix | Changed field names ..." -- deterministic order
# for multiple fields.
def test_field_suffix_order_is_deterministic(run, make_vault):
    make_vault(v3(episodes=[v3_entry(
        id="e1", title={K1: "a", K2: "T"}, description={K1: "d", K2: "D"},
        views={K1: 1, K2: 2}, likes={K1: 1, K2: 2},
        preview={K1: "p", K2: "P"})]))
    line = entry_titles(run("digest", "vault").stdout, "Episodes", "Updated")[0]
    assert line == "T (title, description, views, likes, preview)"


# Spec: "| Trailing line | Metadata about the digest run |" + "| Source
# reference | The trailing line includes the resolved source URL for the loaded
# vault version |" -- v3 uses the `source` field.
def test_trailing_line_includes_v3_source(run, make_vault):
    make_vault(v3(source="https://example.test/v3.json",
                  episodes=[v3_entry(id="e1")]))
    assert "https://example.test/v3.json" in \
        trailing_line(run("digest", "vault").stdout)


# Spec: "| v2 | `source` field value |"
def test_trailing_line_includes_v2_source(run, make_vault):
    make_vault(v2(source="https://example.test/v2.json",
                  episodes=[legacy_entry(id="e1")]))
    assert "https://example.test/v2.json" in \
        trailing_line(run("digest", "vault").stdout)


# Spec: "| v1 | `https://media.example.com/channel/<source_id>` |"
def test_trailing_line_derives_v1_source(run, make_vault):
    make_vault(v1(source_id="chan99", entries=[v1_entry(id="e1")]))
    assert "https://media.example.com/channel/chan99" in \
        trailing_line(run("digest", "vault").stdout)


# Spec: "| Digest trailing line | Deterministic format |" -- same shape on two
# runs, up to the wall-clock value the format may carry.
def test_trailing_line_format_is_deterministic(run, make_vault):
    import re
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    shape = lambda text: re.sub(r"\d", "#", text)
    first = trailing_line(run("digest", "vault").stdout)
    second = trailing_line(run("digest", "vault").stdout)
    assert shape(first) == shape(second)


# Spec: "| Trailing line | Metadata about the digest run |" -- it reports the
# catalog version that was loaded.
def test_trailing_line_reports_loaded_version(run, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    assert "1" in trailing_line(run("digest", "vault").stdout)


# Spec: "| Wall-clock usage outside digest trailing line | Not part of file
# naming or vault content |" -- the digest body itself carries no timestamp.
def test_body_carries_no_wall_clock(run, make_vault):
    import re
    from digest_helpers import body_lines
    make_vault(v3(episodes=[v3_entry(id="e1", title="Plain")]))
    out = run("digest", "vault").stdout
    for line in body_lines(out):
        assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", line)
