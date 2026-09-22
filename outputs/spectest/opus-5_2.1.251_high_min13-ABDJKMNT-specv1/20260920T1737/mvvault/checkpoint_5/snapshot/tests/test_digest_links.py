"""Spec sections: `digest` and Post-Sync Viewer Links (digest side) and
`digest` Viewer Link -- Version-Aware Category."""

from conftest import (
    EPOCH_KEY,
    ISO_KEY,
    legacy_entry,
    v1_catalog,
    v2_catalog,
    v3_catalog,
    v3_entry,
    write_vault,
)

LATER = "2024-07-01T10:00:00"

#: The default viewer endpoint every report link is built on.
VIEWER = "http://127.0.0.1:8840"


def digest_lines(tmp_path, run_cli, catalog, name="demo"):
    write_vault(tmp_path, name, catalog)
    result = run_cli("digest", name)
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def line_with(lines, needle):
    matches = [line for line in lines if needle in line]
    assert len(matches) == 1, f"expected one line with {needle} in {lines}"
    return matches[0]


# Spec: "| `digest <name>` | Each changed-entry line includes viewer link on
# same line as title |" with "| Link format |
# `http://<host>:<port>/catalog/<name>/<category>/<id>` |".
def test_changed_entry_line_carries_the_viewer_link(tmp_path, run_cli):
    catalog = v3_catalog("https://example.test/feed", episodes=[v3_entry("e1")])
    lines = digest_lines(tmp_path, run_cli, catalog)

    assert f"{VIEWER}/catalog/demo/episodes/e1" in line_with(lines, "title-e1")


# Spec: "| Default scheme | `http://` |", "| Default host | `127.0.0.1` |",
# "| Default port | `8840` |".
def test_link_uses_the_default_scheme_host_and_port(tmp_path, run_cli):
    catalog = v3_catalog("https://example.test/feed", episodes=[v3_entry("e1")])
    lines = digest_lines(tmp_path, run_cli, catalog)

    assert line_with(lines, "title-e1").count("http://127.0.0.1:8840/catalog/") == 1


# Spec: "| v2 | Category where entry resides (`episodes`, `streams`, or
# `clips`) |".
def test_v2_links_name_the_category_the_entry_lives_in(tmp_path, run_cli):
    catalog = v2_catalog(
        "https://example.test/feed",
        episodes=[legacy_entry("e1", ISO_KEY)],
        streams=[legacy_entry("s1", ISO_KEY)],
        clips=[legacy_entry("c1", ISO_KEY)],
    )
    lines = digest_lines(tmp_path, run_cli, catalog)

    assert f"{VIEWER}/catalog/demo/episodes/e1" in line_with(lines, "title-e1")
    assert f"{VIEWER}/catalog/demo/streams/s1" in line_with(lines, "title-s1")
    assert f"{VIEWER}/catalog/demo/clips/c1" in line_with(lines, "title-c1")


# Spec: "| v3 | Category where entry resides (`episodes`, `streams`, or
# `clips`) |".
def test_v3_links_name_the_category_the_entry_lives_in(tmp_path, run_cli):
    catalog = v3_catalog(
        "https://example.test/feed",
        episodes=[v3_entry("e1", views={ISO_KEY: 1, LATER: 2})],
        streams=[v3_entry("s1", removed={ISO_KEY: False, LATER: True})],
        clips=[v3_entry("c1")],
    )
    lines = digest_lines(tmp_path, run_cli, catalog)

    assert f"{VIEWER}/catalog/demo/episodes/e1" in line_with(lines, "title-e1")
    assert f"{VIEWER}/catalog/demo/streams/s1" in line_with(lines, "title-s1")
    assert f"{VIEWER}/catalog/demo/clips/c1" in line_with(lines, "title-c1")


# Spec: "| v1 | `entries` |".
def test_v1_links_use_the_entries_category(tmp_path, run_cli):
    lines = digest_lines(tmp_path, run_cli, v1_catalog(legacy_entry("e1", EPOCH_KEY)))

    assert f"{VIEWER}/catalog/demo/entries/e1" in line_with(lines, "title-e1")


# Spec: "| Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>` |"
# -- the vault name in the link is the vault the digest was run on.
def test_link_names_the_vault_the_digest_ran_on(tmp_path, run_cli):
    catalog = v3_catalog("https://example.test/feed", episodes=[v3_entry("e1")])
    lines = digest_lines(tmp_path, run_cli, catalog, name="other-vault")

    assert f"{VIEWER}/catalog/other-vault/episodes/e1" in line_with(lines, "title-e1")


# Spec: "| `digest <name>` | Each changed-entry line includes viewer link ... |"
# -- every reported entry gets one, in every group.
def test_every_changed_entry_line_has_a_link(tmp_path, run_cli):
    catalog = v3_catalog(
        "https://example.test/feed",
        episodes=[
            v3_entry("added"),
            v3_entry("updated", views={ISO_KEY: 1, LATER: 2}),
            v3_entry("gone", removed={ISO_KEY: False, LATER: True}),
        ],
    )
    lines = digest_lines(tmp_path, run_cli, catalog)

    titled = [line for line in lines if "title-" in line]
    assert len(titled) == 3
    assert all(VIEWER in line for line in titled)
