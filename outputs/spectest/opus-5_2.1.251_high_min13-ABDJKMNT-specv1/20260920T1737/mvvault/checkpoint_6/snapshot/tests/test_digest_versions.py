"""`digest` format-aware loading: grouping, value resolution and source URLs."""

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

LATER_EPOCH = "1721000000"
LATER_ISO = "2024-07-01T10:00:00"


# Spec: "| v1 | Single group: `Entries` | Not available (no `removed` field) |
# UNIX-epoch string keys |".
def test_v1_groups_everything_under_entries(tmp_path, run_cli):
    write_vault(tmp_path, "demo", v1_catalog(legacy_entry("e1", EPOCH_KEY)))

    result = run_cli("digest", "demo")

    assert result.returncode == 0, result.stderr
    assert "Entries" in result.stdout
    assert "Episodes" not in result.stdout


# Spec: "| v2 | `Episodes`, `Streams`, `Clips` | ... |".
def test_v2_groups_by_category(tmp_path, run_cli):
    write_vault(
        tmp_path,
        "demo",
        v2_catalog(
            "https://example.test/feed",
            episodes=[legacy_entry("e1", ISO_KEY)],
            clips=[legacy_entry("c1", ISO_KEY)],
        ),
    )

    result = run_cli("digest", "demo")

    assert "Episodes" in result.stdout
    assert "Clips" in result.stdout
    assert "Entries" not in result.stdout


# Spec: "| v1 | Value at the latest key by **numeric** comparison of UNIX-epoch
# strings |" -- lexicographic order would pick the shorter, older key.
def test_v1_current_title_uses_numeric_key_comparison(tmp_path, run_cli):
    entry = legacy_entry("e1", EPOCH_KEY, title={"999999999": "lexicographically-largest", "1718444400": "newest"})
    write_vault(tmp_path, "demo", v1_catalog(entry))

    result = run_cli("digest", "demo")

    assert "newest" in result.stdout
    assert "lexicographically-largest" not in result.stdout


# Spec: "| v2 | Value at the latest key by **lexicographic** comparison of
# ISO 8601 strings |".
def test_v2_current_title_uses_lexicographic_key_comparison(tmp_path, run_cli):
    entry = legacy_entry("e1", ISO_KEY, title={ISO_KEY: "older", LATER_ISO: "current"})
    write_vault(tmp_path, "demo", v2_catalog("https://example.test/feed", episodes=[entry]))

    result = run_cli("digest", "demo")

    assert "current" in result.stdout


# Spec: "| v3 | Value at the latest key by **lexicographic** comparison of
# ISO 8601 strings |".
def test_v3_current_title_uses_lexicographic_key_comparison(tmp_path, run_cli):
    entry = v3_entry("e1", title={ISO_KEY: "older", LATER_ISO: "current"})
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed", episodes=[entry]))

    result = run_cli("digest", "demo")

    assert "current" in result.stdout


# Spec: "| v1 | `https://media.example.com/channel/<source_id>` |".
def test_v1_source_url_is_derived_from_source_id(tmp_path, run_cli):
    write_vault(tmp_path, "demo", v1_catalog(legacy_entry("e1", EPOCH_KEY), source_id="chan42"))

    result = run_cli("digest", "demo")

    assert "https://media.example.com/channel/chan42" in result.stdout


# Spec: "| v2 | `source` field value |".
def test_v2_source_url_is_the_source_field(tmp_path, run_cli):
    write_vault(tmp_path, "demo", v2_catalog("https://v2.example.test/feed.json"))

    result = run_cli("digest", "demo")

    assert "https://v2.example.test/feed.json" in result.stdout


# Spec: "| v3 | `source` field value |".
def test_v3_source_url_is_the_source_field(tmp_path, run_cli):
    write_vault(tmp_path, "demo", v3_catalog("https://v3.example.test/feed.json"))

    result = run_cli("digest", "demo")

    assert "https://v3.example.test/feed.json" in result.stdout


# Spec: "| v1 | ... | Not available (no `removed` field) | ... |" and
# "| Removals | ... | Not applicable; removals group is omitted entirely |".
def test_v1_never_shows_a_removals_group(tmp_path, run_cli):
    entry = legacy_entry("e1", EPOCH_KEY, title={EPOCH_KEY: "old", LATER_EPOCH: "new"})
    write_vault(tmp_path, "demo", v1_catalog(entry))

    result = run_cli("digest", "demo")

    assert "Removed" not in result.stdout


# Spec: "| v2 | ... | Not available (no `removed` field) | ... |" -- a v2 entry
# is classified on its five available tracked fields only.
def test_v2_never_shows_a_removals_group(tmp_path, run_cli):
    entry = legacy_entry("e1", ISO_KEY, views={ISO_KEY: 10, LATER_ISO: 20})
    write_vault(tmp_path, "demo", v2_catalog("https://example.test/feed", episodes=[entry]))

    result = run_cli("digest", "demo")

    assert "Removed" not in result.stdout
