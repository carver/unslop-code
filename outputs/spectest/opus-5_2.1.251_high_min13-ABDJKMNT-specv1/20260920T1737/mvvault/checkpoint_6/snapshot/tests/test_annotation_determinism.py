"""Spec section: Determinism (annotations)."""

import pytest
from annotation_fixtures import V1_ENTRY, V3_ENTRY, created, mark, post, stored, v1_pair_vault
from conftest import REDIRECT_STATUSES, read_catalog
from detail_fixtures import v1_vault, v3_vault


# Phrase: "| Timecode parsing | `\"90\"` = `90`, `\"1:30\"` = `90`,
# `\"1:01:30\"` = `3690`, `\"90:00\"` = `5400` |"
@pytest.mark.parametrize("text, seconds", [("90", 90), ("1:30", 90), ("1:01:30", 3690), ("90:00", 5400)])
def test_the_documented_timecodes_parse_to_their_documented_seconds(viewer, tmp_path, text, seconds):
    vault = v3_vault(tmp_path)

    created(viewer, vault, mark(timecode=text))

    assert stored(vault)[0]["timecode"] == seconds


# Phrase: "| Create-success query parameter | Integer seconds only |"
def test_the_create_query_parameter_is_only_the_seconds(viewer, tmp_path):
    v3_vault(tmp_path)

    location = post(viewer, mark(timecode="90:00")).location

    assert location.endswith("?timecode=5400")


# Phrase: "| Annotation list order | Same order as stored in `catalog.json` |"
def test_the_page_lists_annotations_in_stored_order(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    for title, timecode in [("gamma", "5:00"), ("alpha", "0:30"), ("beta", "2:00")]:
        created(viewer, vault, mark(title=title, timecode=timecode))

    body = viewer.client.get(V3_ENTRY).body

    positions = [body.index(note["title"]) for note in stored(vault)]
    assert positions == sorted(positions)
    assert [note["title"] for note in stored(vault)] == ["gamma", "alpha", "beta"]


# Phrase: "| Auto-migration timestamp | Same timestamp used for all
# migration-added `removed` fields |"
def test_one_timestamp_dates_every_migration_added_removed_field(viewer, tmp_path):
    vault = v1_pair_vault(tmp_path)

    post(viewer, path=V1_ENTRY)

    stamps = {key for entry in read_catalog(vault)["episodes"] for key in entry["removed"]}
    assert len(stamps) == 1


# Phrase: "| Post auto-migration category | v1 entries always migrate to `episodes` |"
def test_v1_entries_always_land_in_episodes(viewer, tmp_path):
    vault = v1_pair_vault(tmp_path)

    post(viewer, path=V1_ENTRY)

    catalog = read_catalog(vault)
    assert [entry["id"] for entry in catalog["episodes"]] == ["e1", "e2"]
    assert catalog["streams"] == [] and catalog["clips"] == []


# Phrase: "| Redirect after v1 annotation | Uses `episodes`, not `entries` |"
def test_the_v1_redirect_never_names_the_entries_category(viewer, tmp_path):
    v1_vault(tmp_path)

    response = post(viewer, path=V1_ENTRY)

    assert response.status in REDIRECT_STATUSES
    assert "/episodes/e1" in response.location
    assert "entries" not in response.location
