"""Spec sections: `timecode` Grammar and `timecode` Parsing Rules."""

import pytest
from annotation_fixtures import V3_ENTRY, created, mark, post, stored
from conftest import REDIRECT_STATUSES, write_media
from detail_fixtures import v3_vault


# Phrase: "| `SS` | `\"90\"` | `90` |", "| `MM:SS` | `\"1:30\"` | `90` |" and
# "| `HH:MM:SS` | `\"1:01:30\"` | `3690` |"
@pytest.mark.parametrize("text, seconds", [("90", 90), ("1:30", 90), ("1:01:30", 3690)])
def test_each_grammar_form_parses_to_its_documented_seconds(viewer, tmp_path, text, seconds):
    vault = v3_vault(tmp_path)

    created(viewer, vault, mark(timecode=text))

    assert stored(vault)[0]["timecode"] == seconds


# Phrase: "| Component type | Non-negative integer |" -- zero is a valid component.
def test_zero_components_are_accepted(viewer, tmp_path):
    vault = v3_vault(tmp_path)

    created(viewer, vault, mark(timecode="0:00:00"))

    assert stored(vault)[0]["timecode"] == 0


# Phrase: "| Component type | Non-negative integer |" -- a negative component is not.
@pytest.mark.parametrize("text", ["-5", "-1:30", "1:-30"])
def test_negative_components_are_rejected(viewer, tmp_path, text):
    v3_vault(tmp_path)

    assert post(viewer, mark(timecode=text)).status == 400


# Phrase: "| Leading zeros | Allowed |"
@pytest.mark.parametrize("text, seconds", [("007", 7), ("01:05", 65), ("00:02:00", 120)])
def test_leading_zeros_are_allowed(viewer, tmp_path, text, seconds):
    vault = v3_vault(tmp_path)

    created(viewer, vault, mark(timecode=text))

    assert stored(vault)[0]["timecode"] == seconds


# Phrase: "| Conventional clock bounds | Not required; `\"90:00\"` is valid in
# `MM:SS` form |"
def test_out_of_clock_range_components_are_valid(viewer, tmp_path):
    vault = v3_vault(tmp_path)

    created(viewer, vault, mark(timecode="90:00"))

    assert stored(vault)[0]["timecode"] == 5400


# Phrase: "| Conventional clock bounds | Not required |" -- a seconds component
# above 59 is accepted too.
def test_seconds_above_fifty_nine_are_valid(viewer, tmp_path):
    vault = v3_vault(tmp_path)

    created(viewer, vault, mark(timecode="1:120"))

    assert stored(vault)[0]["timecode"] == 180


# Phrase: "| Invalid pattern | Return error |"
@pytest.mark.parametrize(
    "text", ["", "abc", "1.5", "9:", ":30", "1:2:3:4", "90s", " 90", "90 ", "1::30", "1,30"]
)
def test_an_invalid_pattern_is_an_error(viewer, tmp_path, text):
    v3_vault(tmp_path)

    assert post(viewer, mark(timecode=text)).status == 400


# Phrase: "| Invalid pattern | Return error |" -- an invalid create stores nothing.
def test_an_invalid_pattern_stores_no_annotation(viewer, tmp_path):
    vault = v3_vault(tmp_path)

    post(viewer, mark(timecode="nope"))

    assert stored(vault) == []


# Phrase: "| Create-success redirect value | Integer whole seconds |"
@pytest.mark.parametrize("text, seconds", [("90", 90), ("1:30", 90), ("1:01:30", 3690)])
def test_the_create_redirect_carries_integer_seconds(viewer, tmp_path, text, seconds):
    v3_vault(tmp_path)

    response = post(viewer, mark(timecode=text))

    assert response.status in REDIRECT_STATUSES
    assert response.location.endswith(f"?timecode={seconds}")


# Phrase: "| Entry detail page effect | Seek playback to `timecode` query value |"
def test_the_detail_page_seeks_to_the_query_timecode(viewer, tmp_path):
    v3_vault(tmp_path)

    response = viewer.client.get(f"{V3_ENTRY}?timecode=3690")

    assert response.status == 200
    assert "3690" in response.body


# Phrase: "| Entry detail page effect | Seek playback to `timecode` query value |"
# -- without the query the page names no offset.
def test_the_detail_page_names_no_offset_without_the_query(viewer, tmp_path):
    v3_vault(tmp_path)

    assert "3690" not in viewer.client.get(V3_ENTRY).body


# Phrase: "| Entry detail page effect | Seek playback to `timecode` query value |"
# -- the stored media is referenced at the requested offset.
def test_stored_media_is_referenced_at_the_requested_offset(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    write_media(vault, "e1.mp4")

    body = viewer.client.get(f"{V3_ENTRY}?timecode=90").body

    assert "#t=90" in body


# Phrase: "| Entry detail page effect | Seek playback to `timecode` query value |"
# -- the query is read with the same grammar the request body uses.
def test_a_clock_form_query_seeks_to_its_seconds(viewer, tmp_path):
    v3_vault(tmp_path)

    body = viewer.client.get(f"{V3_ENTRY}?timecode=1:30").body

    assert "90" in body
    assert "1:30" not in body


# Phrase: "| Invalid pattern | Return error |" -- an unreadable query value asks
# for no offset rather than breaking the page.
def test_an_unreadable_query_timecode_leaves_the_page_intact(viewer, tmp_path):
    v3_vault(tmp_path)

    response = viewer.client.get(f"{V3_ENTRY}?timecode=halfway")

    assert response.status == 200
    assert "halfway" not in response.body
