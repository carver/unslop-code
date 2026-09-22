"""Spec section: Determinism, for the annotation routes."""

import pytest

from conftest import (
    annotation_titles,
    create,
    entry_route,
    location,
    read_catalog,
    stored_annotations,
    v1_catalog,
    v1_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

ROUTE = entry_route("vault", "episodes", "e1")
V1_ROUTE = entry_route("vault", "entries", "e1")


@pytest.fixture
def entry(serve, tmp_path):
    """A viewer over a v3 vault holding one episode, plus the vault directory."""
    vault_dir = write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    return serve(), vault_dir


# Spec: Timecode parsing | `"90"` = `90`, `"1:30"` = `90`, `"1:01:30"` = `3690`,
# `"90:00"` = `5400`
@pytest.mark.parametrize(
    "timecode,seconds", [("90", 90), ("1:30", 90), ("1:01:30", 3690), ("90:00", 5400)]
)
def test_the_named_timecodes_parse_exactly(entry, timecode, seconds):
    viewer, vault_dir = entry
    create(viewer, ROUTE, title="Mark", timecode=timecode)
    assert stored_annotations(vault_dir, "episodes", "e1")[-1]["timecode"] == seconds


# Spec: Create-success query parameter | Integer seconds only
@pytest.mark.parametrize("timecode,seconds", [("1:30", "90"), ("90:00", "5400")])
def test_the_create_query_parameter_is_integer_seconds(entry, timecode, seconds):
    viewer, _ = entry
    _, query = location(create(viewer, ROUTE, title="Mark", timecode=timecode))
    assert query == {"timecode": [seconds]}


# Spec: Annotation list order | Same order as stored in `catalog.json`
def test_repeated_reads_keep_the_stored_order(entry):
    viewer, vault_dir = entry
    for title in ("one", "two", "three"):
        create(viewer, ROUTE, title=title, timecode="0")
    assert annotation_titles(vault_dir, "episodes", "e1") == ["one", "two", "three"]
    assert annotation_titles(vault_dir, "episodes", "e1") == ["one", "two", "three"]


# Spec: Auto-migration timestamp | Same timestamp used for all migration-added
# `removed` fields
def test_one_timestamp_covers_every_migration_added_removed_field(serve, tmp_path):
    entries = [v1_entry(f"e{index}") for index in range(4)]
    vault_dir = write_vault(tmp_path, v1_catalog(entries=entries))
    create(serve(), V1_ROUTE, title="Chorus", timecode="90")
    stamps = {
        key for entry in read_catalog(vault_dir)["episodes"] for key in entry["removed"]
    }
    assert len(stamps) == 1


# Spec: Post auto-migration category | v1 entries always migrate to `episodes`
def test_v1_entries_always_land_in_episodes(serve, tmp_path):
    vault_dir = write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1"), v1_entry("e2")]))
    create(serve(), V1_ROUTE, title="Chorus", timecode="90")
    catalog = read_catalog(vault_dir)
    assert [entry["id"] for entry in catalog["episodes"]] == ["e1", "e2"]
    assert catalog["streams"] == [] and catalog["clips"] == []


# Spec: Redirect after v1 annotation | Uses `episodes`, not `entries`
def test_the_v1_redirect_never_names_entries(serve, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    response = create(serve(), V1_ROUTE, title="Chorus", timecode="90")
    assert response.headers["Location"].startswith(ROUTE)
    assert "entries" not in response.headers["Location"]
