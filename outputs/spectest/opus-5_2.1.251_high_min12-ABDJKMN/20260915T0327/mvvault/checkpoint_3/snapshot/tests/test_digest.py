"""Spec sections: `digest` Command, `digest` Format-Aware Loading, `digest`
Change Classification, Group Precedence, Current Value Resolution, Source URL
Resolution, `digest` Output Layout, and the `digest` Error Handling rows."""
import os

import pytest

from conftest import (
    LEGACY_SOURCE_PREFIX,
    backup_path,
    catalog_text,
    entry,
    lines,
    payload,
    trailing_line,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

T1 = "2024-01-01T00:00:00"
T2 = "2024-02-01T00:00:00"
T3 = "2024-03-01T00:00:00"


def body(text):
    """Digest output without its trailing metadata line."""
    return "\n".join(lines(text)[:-1])


def digest_of(run, tmp_path, catalog, name="vault"):
    write_vault(tmp_path, catalog, name)
    result = run("digest", name)
    assert result.returncode == 0, result
    return result


# --- Phrase: "| Syntax | `python mvault.py digest <name>` |"
def test_digest_runs_on_a_v3_vault(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    result = run("digest", "vault")
    assert result.returncode == 0, result


def test_digest_requires_a_vault_name(run, tmp_path):
    assert run("digest").returncode != 0


# --- Phrase: "| Output stream | stdout |"
def test_digest_writes_to_stdout(run, tmp_path):
    result = digest_of(run, tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    assert result.stdout.strip(), result
    assert result.stderr == "", result


# --- Phrase: "| Input | Existing vault of any supported version |" +
#     "The `digest` command works on vaults of any supported version without
#     requiring prior migration."
@pytest.mark.parametrize(
    "catalog",
    [
        v1_catalog(entries=[v1_entry("e1")]),
        v2_catalog(episodes=[v2_entry("e1")]),
        v3_catalog(episodes=[v3_entry("e1")]),
    ],
)
def test_digest_accepts_every_supported_version(run, tmp_path, catalog):
    write_vault(tmp_path, catalog)
    result = run("digest", "vault")
    assert result.returncode == 0, result


# --- Phrase: "`digest` must work directly on v1, v2, and v3 catalogs without
#     migrating."
@pytest.mark.parametrize(
    "catalog",
    [
        v1_catalog(entries=[v1_entry("e1")]),
        v2_catalog(episodes=[v2_entry("e1")]),
    ],
)
def test_digest_does_not_migrate_the_catalog(run, tmp_path, catalog):
    write_vault(tmp_path, catalog)
    before = catalog_text(tmp_path)
    run("digest", "vault")
    assert catalog_text(tmp_path) == before


# --- Phrase: "| Catalog modification | `digest` is read-only; it never writes
#     `catalog.json` or `catalog.bak` |"
def test_digest_never_writes_catalog_or_backup(run, tmp_path):
    catalog = v3_catalog(
        episodes=[v3_entry("e1", title={T1: "Old", T2: "New"})]
    )
    write_vault(tmp_path, catalog)
    before = catalog_text(tmp_path)
    assert run("digest", "vault").returncode == 0
    assert catalog_text(tmp_path) == before
    assert not os.path.exists(backup_path(tmp_path))


def test_digest_creates_no_extra_files(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    run("digest", "vault")
    assert os.listdir(os.path.join(str(tmp_path), "vault")) == ["catalog.json"]


# --- Phrase: "| Missing vault | Error to stderr including vault name; exit
#     non-zero |"
def test_digest_missing_vault_errors_with_the_name(run, tmp_path):
    result = run("digest", "ghost")
    assert result.returncode != 0, result
    assert "ghost" in result.stderr, result
    assert result.stdout.strip() == "", result


def test_digest_vault_without_catalog_errors(run, tmp_path):
    (tmp_path / "broken").mkdir()
    result = run("digest", "broken")
    assert result.returncode != 0, result
    assert "broken" in result.stderr, result


# --- Phrase: "| `digest` on vault with unsupported version | stderr |
#     non-zero | Message includes version value |"
@pytest.mark.parametrize("version", [0, 4, 99, -1])
def test_digest_unsupported_version_reports_the_value(run, tmp_path, version):
    catalog = v3_catalog()
    catalog["version"] = version
    write_vault(tmp_path, catalog)
    result = run("digest", "vault")
    assert result.returncode != 0, result
    assert str(version) in result.stderr, result


def test_digest_non_integer_version_reports_the_value(run, tmp_path):
    catalog = v3_catalog()
    catalog["version"] = "three"
    write_vault(tmp_path, catalog)
    result = run("digest", "vault")
    assert result.returncode != 0, result
    assert "three" in result.stderr, result


# ---------------------------------------------------------------------------
# Change classification
# ---------------------------------------------------------------------------

# --- Phrase: "| Additions | Entry has only initial observations; no tracked
#     field has a second history entry |"
def test_entry_with_only_initial_observations_is_an_addition(run, tmp_path):
    result = digest_of(run, tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    assert "Title e1" in result.stdout, result
    assert "addition" in body(result.stdout).lower(), result


# --- Phrase: "| Field updates | At least one tracked field has two or more
#     history entries and the latest two values differ |"
def test_changed_field_makes_the_entry_a_field_update(run, tmp_path):
    catalog = v3_catalog(
        episodes=[v3_entry("e1", title={T1: "Old title", T2: "New title"})]
    )
    result = digest_of(run, tmp_path, catalog)
    assert "update" in body(result.stdout).lower(), result
    assert "addition" not in body(result.stdout).lower(), result


# --- Phrase: "| Field-update suffix | Changed field names in parentheses
#     after title |"
def test_field_update_names_the_changed_field(run, tmp_path):
    catalog = v3_catalog(
        episodes=[v3_entry("e1", views={T1: 1, T2: 2})]
    )
    result = digest_of(run, tmp_path, catalog)
    assert "(views)" in result.stdout, result


def test_field_update_names_every_changed_field(run, tmp_path):
    catalog = v3_catalog(
        episodes=[
            v3_entry(
                "e1",
                title={T1: "A", T2: "B"},
                views={T1: 1, T2: 2},
                likes={T1: 1, T2: None},
            )
        ]
    )
    result = digest_of(run, tmp_path, catalog)
    for field in ("title", "views", "likes"):
        assert field in result.stdout, (field, result.stdout)
    assert "description" not in result.stdout, result


# --- Phrase: "the latest two values differ" (context: a repeated value is not
#     a change -- see AMBIGUITIES T35)
def test_repeated_value_is_not_a_field_update(run, tmp_path):
    catalog = v3_catalog(
        episodes=[v3_entry("e1", views={T1: 5, T2: 5})]
    )
    result = digest_of(run, tmp_path, catalog)
    assert "no notable changes" in result.stdout.lower(), result


# --- Phrase: "| Additions | Entry has only initial observations; no tracked
#     field has a second history entry |" (context: a second history entry
#     disqualifies the addition even when the value repeats, AMBIGUITIES T35)
def test_repeated_value_is_not_an_addition_either(run, tmp_path):
    catalog = v3_catalog(episodes=[v3_entry("e1", views={T1: 5, T2: 5})])
    result = digest_of(run, tmp_path, catalog)
    assert "Title e1" not in result.stdout, result


# --- Phrase: "| Removals | Latest `removed` value is `true` and prior
#     `removed` value, if present, is `false` |"
def test_removed_entry_is_a_removal(run, tmp_path):
    catalog = v3_catalog(
        episodes=[v3_entry("e1", removed={T1: False, T2: True})]
    )
    result = digest_of(run, tmp_path, catalog)
    assert "remov" in body(result.stdout).lower(), result
    assert "Title e1" in result.stdout, result


def test_entry_still_present_is_not_a_removal(run, tmp_path):
    catalog = v3_catalog(
        episodes=[v3_entry("e1", removed={T1: False})]
    )
    result = digest_of(run, tmp_path, catalog)
    assert "Title e1" in result.stdout, result
    assert "addition" in body(result.stdout).lower(), result


# --- Phrase: "prior `removed` value, if present, is `false`" (context: a
#     single `true` observation with no prior value still qualifies)
def test_removal_with_no_prior_value_qualifies(run, tmp_path):
    catalog = v3_catalog(episodes=[v3_entry("e1", removed={T1: True})])
    result = digest_of(run, tmp_path, catalog)
    assert "remov" in body(result.stdout).lower(), result
    assert "Title e1" in result.stdout, result


# --- Phrase: "| Reappearance after removal (v3 only) | Indicate reappearance
#     alongside any other changed fields |" (see AMBIGUITIES T31/T32)
def test_reappearance_is_reported(run, tmp_path):
    catalog = v3_catalog(
        episodes=[v3_entry("e1", removed={T1: False, T2: True, T3: False})]
    )
    result = digest_of(run, tmp_path, catalog)
    assert "Title e1" in result.stdout, result
    assert "reappear" in result.stdout.lower(), result


def test_reappearance_lists_other_changed_fields_too(run, tmp_path):
    catalog = v3_catalog(
        episodes=[
            v3_entry(
                "e1",
                title={T1: "Old", T2: "Back"},
                removed={T1: False, T2: True, T3: False},
            )
        ]
    )
    result = digest_of(run, tmp_path, catalog)
    entry_text = [ln for ln in lines(result.stdout) if "Back" in ln]
    assert len(entry_text) == 1, result.stdout
    assert "title" in entry_text[0]
    assert "reappear" in entry_text[0].lower()


# ---------------------------------------------------------------------------
# Group precedence
# ---------------------------------------------------------------------------

# --- Phrase: "Each entry may appear once." +
#     "| `1` | Removals (v3 only) | `2` | Additions | `3` | Field updates |"
def test_removed_entry_with_field_changes_appears_once_as_a_removal(
    run, tmp_path
):
    catalog = v3_catalog(
        episodes=[
            v3_entry(
                "e1",
                title={T1: "Old", T2: "Renamed"},
                removed={T1: False, T2: True},
            )
        ]
    )
    result = digest_of(run, tmp_path, catalog)
    hits = [ln for ln in lines(result.stdout) if "Renamed" in ln]
    assert len(hits) == 1, result.stdout
    assert "(" not in hits[0], hits


def test_each_entry_appears_once(run, tmp_path):
    catalog = v3_catalog(
        episodes=[
            v3_entry("a", removed={T1: False, T2: True}),
            v3_entry("b", title={T1: "x", T2: "Title b"}),
            v3_entry("c"),
        ]
    )
    result = digest_of(run, tmp_path, catalog)
    for eid in ("a", "b", "c"):
        hits = [ln for ln in lines(result.stdout) if "Title %s" % eid in ln]
        assert len(hits) == 1, (eid, result.stdout)


# --- Phrase: "| Priority | Group | `1` | Removals | `2` | Additions |
#     `3` | Field updates |" (context: group order within a category)
def test_groups_appear_in_precedence_order(run, tmp_path):
    catalog = v3_catalog(
        episodes=[
            v3_entry("a", removed={T1: False, T2: True}),
            v3_entry("b"),
            v3_entry("c", views={T1: 1, T2: 2}),
        ]
    )
    result = digest_of(run, tmp_path, catalog)
    text = result.stdout
    assert text.index("Title a") < text.index("Title b") < text.index("Title c")


# ---------------------------------------------------------------------------
# Format-aware loading: grouping and removal availability
# ---------------------------------------------------------------------------

# --- Phrase: "| v1 | Single group: `Entries` |"
def test_v1_uses_a_single_entries_group(run, tmp_path):
    catalog = v1_catalog(entries=[v1_entry("e1")])
    result = digest_of(run, tmp_path, catalog)
    assert "Entries" in result.stdout, result
    assert "Episodes" not in result.stdout, result


# --- Phrase: "| v2 | `Episodes`, `Streams`, `Clips` |" and the v3 row
def test_v2_groups_by_category(run, tmp_path):
    catalog = v2_catalog(
        episodes=[v2_entry("e1")],
        streams=[v2_entry("s1")],
        clips=[v2_entry("c1")],
    )
    result = digest_of(run, tmp_path, catalog)
    for label in ("Episodes", "Streams", "Clips"):
        assert label in result.stdout, (label, result.stdout)


def test_v3_groups_by_category(run, tmp_path):
    catalog = v3_catalog(
        episodes=[v3_entry("e1")],
        streams=[v3_entry("s1")],
        clips=[v3_entry("c1")],
    )
    result = digest_of(run, tmp_path, catalog)
    for label in ("Episodes", "Streams", "Clips"):
        assert label in result.stdout, (label, result.stdout)


# --- Phrase: "| Removal Detection | v1: Not available (no `removed` field) |"
#     + "| Removals | ... | Not applicable; removals group is omitted
#     entirely |"
def test_v1_has_no_removals_group(run, tmp_path):
    catalog = v1_catalog(entries=[v1_entry("e1")])
    result = digest_of(run, tmp_path, catalog)
    assert "Removals" not in result.stdout, result


def test_v2_has_no_removals_group(run, tmp_path):
    catalog = v2_catalog(episodes=[v2_entry("e1")])
    result = digest_of(run, tmp_path, catalog)
    assert "Removals" not in result.stdout, result


# --- Phrase: "| Additions | ... | Same rule applied to available tracked
#     fields |" (v1/v2 have five tracked fields, not six)
def test_v2_entry_with_only_initial_observations_is_an_addition(run, tmp_path):
    catalog = v2_catalog(episodes=[v2_entry("e1")])
    result = digest_of(run, tmp_path, catalog)
    assert "Title e1" in result.stdout, result
    assert "addition" in body(result.stdout).lower(), result


# --- Phrase: "| Field updates | ... | Same rule applied to available tracked
#     fields |"
def test_v2_field_update_is_detected(run, tmp_path):
    catalog = v2_catalog(
        episodes=[v2_entry("e1", description={T1: "old", T2: "new"})]
    )
    result = digest_of(run, tmp_path, catalog)
    assert "(description)" in result.stdout, result


def test_v1_field_update_is_detected(run, tmp_path):
    catalog = v1_catalog(
        entries=[v1_entry("e1", views={"1700000000": 1, "1718444400": 2})]
    )
    result = digest_of(run, tmp_path, catalog)
    assert "(views)" in result.stdout, result


# ---------------------------------------------------------------------------
# Current value resolution
# ---------------------------------------------------------------------------

# --- Phrase: "| v1 | Value at the latest key by **numeric** comparison of
#     UNIX-epoch strings |" + "| v1 history ordering in digest | Numeric
#     comparison of epoch-second strings |"
def test_v1_latest_value_uses_numeric_key_comparison(run, tmp_path):
    # Lexicographically "999999999" > "1000000000"; numerically it is smaller.
    catalog = v1_catalog(
        entries=[
            v1_entry(
                "e1",
                title={"999999999": "Older title", "1000000000": "Newer title"},
            )
        ]
    )
    result = digest_of(run, tmp_path, catalog)
    assert "Newer title" in result.stdout, result
    assert "Older title" not in result.stdout, result


# --- Phrase: "| v2 | Value at the latest key by **lexicographic** comparison
#     of ISO 8601 strings |"
def test_v2_latest_value_uses_lexicographic_key_comparison(run, tmp_path):
    # Lexicographically "2024-9-01..." > "2024-10-01..." even though the
    # calendar order is the other way round.
    catalog = v2_catalog(
        episodes=[
            v2_entry(
                "e1",
                title={
                    "2024-10-01T00:00:00": "October title",
                    "2024-9-01T00:00:00": "September title",
                },
            )
        ]
    )
    result = digest_of(run, tmp_path, catalog)
    assert "September title" in result.stdout, result


# --- Phrase: "| v3 | Value at the latest key by **lexicographic** comparison
#     of ISO 8601 strings |"
def test_v3_latest_value_uses_lexicographic_key_comparison(run, tmp_path):
    catalog = v3_catalog(
        episodes=[
            v3_entry(
                "e1",
                title={
                    "2024-10-01T00:00:00": "October title",
                    "2024-9-01T00:00:00": "September title",
                },
            )
        ]
    )
    result = digest_of(run, tmp_path, catalog)
    assert "September title" in result.stdout, result


# --- Phrase: "| Entry text | Current title from latest `title` history
#     value |"
def test_entry_text_is_the_current_title(run, tmp_path):
    catalog = v3_catalog(
        episodes=[v3_entry("e1", title={T1: "Stale name", T2: "Current name"})]
    )
    result = digest_of(run, tmp_path, catalog)
    assert "Current name" in result.stdout, result
    assert "Stale name" not in result.stdout, result


# ---------------------------------------------------------------------------
# Source URL resolution
# ---------------------------------------------------------------------------

# --- Phrase: "| Source reference | The trailing line includes the resolved
#     source URL for the loaded vault version |" +
#     "| v1 | `https://media.example.com/channel/<source_id>` |"
def test_v1_source_url_is_derived_from_source_id(run, tmp_path):
    catalog = v1_catalog(source_id="chan-77", entries=[v1_entry("e1")])
    result = digest_of(run, tmp_path, catalog)
    assert LEGACY_SOURCE_PREFIX + "chan-77" in trailing_line(result.stdout), result


# --- Phrase: "| v2 | `source` field value |"
def test_v2_source_url_is_the_source_field(run, tmp_path):
    url = "https://v2.example.test/feed.json"
    catalog = v2_catalog(source=url, episodes=[v2_entry("e1")])
    result = digest_of(run, tmp_path, catalog)
    assert url in trailing_line(result.stdout), result


# --- Phrase: "| v3 | `source` field value |"
def test_v3_source_url_is_the_source_field(run, tmp_path):
    url = "https://v3.example.test/feed.json"
    catalog = v3_catalog(source=url, episodes=[v3_entry("e1")])
    result = digest_of(run, tmp_path, catalog)
    assert url in trailing_line(result.stdout), result


# ---------------------------------------------------------------------------
# Output layout
# ---------------------------------------------------------------------------

# --- Phrase: "| Empty category | Omitted |"
def test_category_without_changes_is_omitted(run, tmp_path):
    catalog = v3_catalog(episodes=[v3_entry("e1")])
    result = digest_of(run, tmp_path, catalog)
    assert "Episodes" in result.stdout, result
    assert "Streams" not in result.stdout, result
    assert "Clips" not in result.stdout, result


def test_category_whose_entries_have_no_changes_is_omitted(run, tmp_path):
    catalog = v3_catalog(
        episodes=[v3_entry("e1")],
        clips=[v3_entry("c1", views={T1: 5, T2: 5})],
    )
    result = digest_of(run, tmp_path, catalog)
    assert "Clips" not in result.stdout, result


# --- Phrase: "| No notable changes anywhere | Indicate that no notable
#     changes were found |"
def test_empty_catalog_reports_no_notable_changes(run, tmp_path):
    result = digest_of(run, tmp_path, v3_catalog())
    assert "no notable changes" in result.stdout.lower(), result


def test_no_notable_changes_still_prints_the_trailing_line(run, tmp_path):
    url = "https://quiet.example.test/feed.json"
    result = digest_of(run, tmp_path, v3_catalog(source=url))
    assert url in trailing_line(result.stdout), result


# --- Phrase: "| Trailing line | Metadata about the digest run |" (see
#     AMBIGUITIES T33 for the chosen content)
def test_trailing_line_is_the_last_line(run, tmp_path):
    url = "https://tail.example.test/feed.json"
    catalog = v3_catalog(source=url, episodes=[v3_entry("e1")])
    result = digest_of(run, tmp_path, catalog)
    assert url in lines(result.stdout)[-1], result


def test_trailing_line_names_the_vault(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]), name="myvault")
    result = run("digest", "myvault")
    assert result.returncode == 0, result
    assert "myvault" in trailing_line(result.stdout), result


# --- Phrase: "| Digest trailing line | Deterministic format |"
def test_trailing_line_format_is_stable_across_runs(run, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    first = trailing_line(run("digest", "vault").stdout)
    second = trailing_line(run("digest", "vault").stdout)
    # Only a timestamp may differ; the surrounding structure must not.
    assert len(first.split("|")) == len(second.split("|"))
    assert first.split("|")[:-1] == second.split("|")[:-1]


# --- Phrase: "| Category grouping | Changes grouped by category |" (context:
#     an entry is listed under its own category)
def test_changes_are_listed_under_their_category(run, tmp_path):
    catalog = v3_catalog(
        episodes=[v3_entry("e1")],
        clips=[v3_entry("c1")],
    )
    result = digest_of(run, tmp_path, catalog)
    text = result.stdout
    assert text.index("Episodes") < text.index("Title e1") < text.index("Clips")
    assert text.index("Clips") < text.index("Title c1")


# --- Phrase: "| Digest category order | Deterministic |"
def test_category_order_is_deterministic(run, tmp_path):
    catalog = v3_catalog(
        episodes=[v3_entry("e1")],
        streams=[v3_entry("s1")],
        clips=[v3_entry("c1")],
    )
    result = digest_of(run, tmp_path, catalog)
    text = result.stdout
    assert text.index("Episodes") < text.index("Streams") < text.index("Clips")


# --- Phrase: "| Entry order within group | Deterministic |" (catalog order --
#     see AMBIGUITIES T30)
def test_entry_order_within_a_group_is_deterministic(run, tmp_path):
    catalog = v3_catalog(
        episodes=[v3_entry("b"), v3_entry("a"), v3_entry("c")]
    )
    result = digest_of(run, tmp_path, catalog)
    text = result.stdout
    assert text.index("Title b") < text.index("Title a") < text.index("Title c")


def test_digest_output_is_identical_across_runs(run, tmp_path):
    catalog = v3_catalog(
        episodes=[
            v3_entry("a", removed={T1: False, T2: True}),
            v3_entry("b", title={T1: "x", T2: "Title b"}),
            v3_entry("c"),
        ]
    )
    write_vault(tmp_path, catalog)
    first = body(run("digest", "vault").stdout)
    second = body(run("digest", "vault").stdout)
    assert first == second


# --- Phrase: "| Grouping within category | Changes grouped by type |"
def test_changes_are_grouped_by_type_within_a_category(run, tmp_path):
    catalog = v3_catalog(
        episodes=[
            v3_entry("added-1"),
            v3_entry("updated-1", views={T1: 1, T2: 2}),
            v3_entry("added-2"),
        ]
    )
    result = digest_of(run, tmp_path, catalog)
    text = result.stdout
    assert text.index("Title added-1") < text.index("Title added-2")
    assert text.index("Title added-2") < text.index("Title updated-1")


# --- Phrase: "| Purpose | Human-readable summary of notable changes derived
#     from tracked-field history |" (context: an entry with no history at all
#     falls back to something identifying, see AMBIGUITIES T38)
def test_entry_without_title_history_still_digests(run, tmp_path):
    catalog = v3_catalog(episodes=[v3_entry("e1", title={})])
    write_vault(tmp_path, catalog)
    result = run("digest", "vault")
    assert result.returncode == 0, result
    assert "e1" in result.stdout, result


# --- Phrase: "| Missing vault | ... |" (context: `digest` on a vault whose
#     entries are partly malformed is still read-only and non-fatal, T38)
def test_digest_tolerates_odd_entry_shapes(run, tmp_path):
    catalog = v3_catalog(episodes=[v3_entry("e1"), {"id": "e2"}])
    write_vault(tmp_path, catalog)
    result = run("digest", "vault")
    assert result.returncode == 0, result


# --- Phrase: "| Input | Existing vault of any supported version |" (context:
#     a digest after a real sync reflects that sync's changes)
def test_digest_after_sync_reports_the_new_entries(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    assert run("sync", "vault", "--skip-download").returncode == 0
    result = run("digest", "vault")
    assert result.returncode == 0, result
    assert "Title e1" in result.stdout, result
    assert "addition" in body(result.stdout).lower(), result
