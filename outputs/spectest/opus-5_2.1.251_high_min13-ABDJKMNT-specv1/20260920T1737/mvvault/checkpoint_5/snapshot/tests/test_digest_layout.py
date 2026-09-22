"""`digest` output layout: grouping, ordering, omissions and the trailing line."""

from conftest import ISO_KEY, v3_catalog, v3_entry, write_vault

LATER = "2024-07-01T10:00:00"


def lines_of(tmp_path, run_cli, **categories):
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed", **categories))
    result = run_cli("digest", "demo")
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def index_of(lines, needle):
    return next(number for number, line in enumerate(lines) if needle in line)


# Spec: "| Category grouping | Changes grouped by category (v1: single `Entries`
# group; v2/v3: per-category) |" and "| Digest category order | Deterministic |".
def test_categories_appear_in_catalog_order(tmp_path, run_cli):
    lines = lines_of(
        tmp_path,
        run_cli,
        episodes=[v3_entry("e1")],
        streams=[v3_entry("s1")],
        clips=[v3_entry("c1")],
    )

    assert index_of(lines, "Episodes") < index_of(lines, "Streams") < index_of(lines, "Clips")


# Spec: "| Grouping within category | Changes grouped by type |" with the
# precedence order "1 Removals, 2 Additions, 3 Field updates".
def test_groups_within_a_category_follow_the_precedence_order(tmp_path, run_cli):
    lines = lines_of(
        tmp_path,
        run_cli,
        episodes=[
            v3_entry("updated", views={ISO_KEY: 1, LATER: 2}),
            v3_entry("added"),
            v3_entry("gone", removed={ISO_KEY: False, LATER: True}),
        ],
    )

    assert index_of(lines, "Removed") < index_of(lines, "Added") < index_of(lines, "Updated")


# Spec: "| Entry order within group | Deterministic |" -- catalog order.
def test_entries_within_a_group_follow_catalog_order(tmp_path, run_cli):
    lines = lines_of(tmp_path, run_cli, episodes=[v3_entry("second"), v3_entry("first")])

    assert index_of(lines, "title-second") < index_of(lines, "title-first")


# Spec: "| Empty category | Omitted |".
def test_category_without_changes_is_omitted(tmp_path, run_cli):
    lines = lines_of(tmp_path, run_cli, episodes=[v3_entry("e1")])

    assert not [line for line in lines if "Streams" in line or "Clips" in line]


# Spec: "| No notable changes anywhere | Indicate that no notable changes were
# found |".
def test_vault_without_notable_changes_says_so(tmp_path, run_cli):
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed"))

    result = run_cli("digest", "demo")

    assert result.returncode == 0, result.stderr
    assert "no notable changes" in result.stdout.lower()


# Spec: "| Entry text | Current title from latest `title` history value |".
def test_entry_text_is_the_current_title(tmp_path, run_cli):
    lines = lines_of(tmp_path, run_cli, episodes=[v3_entry("e1", title={ISO_KEY: "old", LATER: "current"})])

    assert index_of(lines, "current")
    assert not [line for line in lines if "old" in line]


# Spec: "| Digest trailing line | Deterministic format |" -- the same vault
# yields the same trailing line shape on every run.
def test_trailing_line_shape_is_stable(tmp_path, run_cli):
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed", episodes=[v3_entry("e1")]))

    first = run_cli("digest", "demo").stdout.splitlines()[-1]
    second = run_cli("digest", "demo").stdout.splitlines()[-1]

    assert first.split() [:2] == second.split()[:2]
    assert "https://example.test/feed" in first
