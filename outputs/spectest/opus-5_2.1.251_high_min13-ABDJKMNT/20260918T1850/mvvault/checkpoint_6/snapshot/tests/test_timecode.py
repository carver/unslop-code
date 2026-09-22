"""Spec sections: `timecode` Grammar and `timecode` Parsing Rules."""

import pytest

from conftest import (
    add_media,
    assert_clean,
    create,
    entry_route,
    location,
    stored_annotations,
    v3_catalog,
    v3_entry,
    write_vault,
)

ROUTE = entry_route("vault", "episodes", "e1")


def posted(viewer, vault_dir, timecode):
    """Create one annotation at `timecode` and return the seconds stored."""
    create(viewer, ROUTE, title="Mark", timecode=timecode)
    return stored_annotations(vault_dir, "episodes", "e1")[-1]["timecode"]


@pytest.fixture
def entry(serve, tmp_path):
    """A running viewer over a v3 vault with one episode, plus its directory."""
    vault_dir = write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    return serve(), vault_dir


# Spec: `SS` | `"90"` | `90`
def test_seconds_only_form(entry):
    viewer, vault_dir = entry
    assert posted(viewer, vault_dir, "90") == 90


# Spec: `MM:SS` | `"1:30"` | `90`
def test_minutes_and_seconds_form(entry):
    viewer, vault_dir = entry
    assert posted(viewer, vault_dir, "1:30") == 90


# Spec: `HH:MM:SS` | `"1:01:30"` | `3690`
def test_hours_minutes_and_seconds_form(entry):
    viewer, vault_dir = entry
    assert posted(viewer, vault_dir, "1:01:30") == 3690


# Spec: Leading zeros | Allowed
def test_leading_zeros_are_allowed(entry):
    viewer, vault_dir = entry
    assert posted(viewer, vault_dir, "007") == 7
    assert posted(viewer, vault_dir, "00:00:09") == 9


# Spec: Conventional clock bounds | Not required; `"90:00"` is valid in `MM:SS` form
def test_clock_bounds_are_not_enforced(entry):
    viewer, vault_dir = entry
    assert posted(viewer, vault_dir, "90:00") == 5400
    assert posted(viewer, vault_dir, "0:0:999") == 999


# Spec: Component type | Non-negative integer
def test_zero_is_a_valid_timecode(entry):
    viewer, vault_dir = entry
    assert posted(viewer, vault_dir, "0") == 0


# Spec: Invalid pattern | Return error
@pytest.mark.parametrize(
    "timecode",
    ["", "abc", "1:30:00:00", "1:", ":30", "1::30", "1.5", "-1", "1:-30", "90s", "1 : 30"],
)
def test_an_invalid_pattern_is_refused(entry, timecode):
    viewer, vault_dir = entry
    response = viewer.send("POST", ROUTE, {"title": "Mark", "timecode": timecode})
    assert response.status_code == 400
    assert stored_annotations(vault_dir, "episodes", "e1") == []


# Spec: Invalid pattern | Return error (T68: surrounding whitespace is not trimmed)
def test_surrounding_whitespace_is_an_invalid_pattern(entry):
    viewer, _ = entry
    assert viewer.send("POST", ROUTE, {"title": "Mark", "timecode": " 90"}).status_code == 400


# Spec: Component type | Non-negative integer (T67: a JSON number is not a timecode)
def test_a_non_string_timecode_is_refused(entry):
    viewer, _ = entry
    assert viewer.send("POST", ROUTE, {"title": "Mark", "timecode": 90}).status_code == 400


# Spec: Create-success redirect value | Integer whole seconds
def test_the_redirect_carries_integer_seconds(entry):
    viewer, _ = entry
    _, query = location(create(viewer, ROUTE, title="Mark", timecode="1:01:30"))
    assert query == {"timecode": ["3690"]}


# Spec: Entry detail page effect | Seek playback to `timecode` query value
def test_the_detail_page_seeks_to_the_timecode_query_value(entry):
    viewer, _ = entry
    body = viewer.get(f"{ROUTE}?timecode=90").text
    assert 'data-timecode="90"' in body


# Spec: Entry detail page effect | ... (the seek reaches the media player)
def test_the_media_player_starts_at_the_timecode(serve, tmp_path):
    vault_dir = write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    add_media(vault_dir, "e1.mp4")
    body = serve().get(f"{ROUTE}?timecode=90").text
    assert "#t=90" in body


# Spec: Entry detail page effect | ... (T70: an unparsable query value is ignored)
def test_an_unparsable_timecode_query_still_renders_the_page(entry):
    viewer, _ = entry
    response = viewer.get(f"{ROUTE}?timecode=banana")
    assert response.status_code == 200
    assert "Title e1" in response.text
    assert_clean(response)


# Spec: Entry detail page effect | ... (the grammar is shared with create)
def test_the_query_value_accepts_the_same_grammar(entry):
    viewer, _ = entry
    assert 'data-timecode="90"' in viewer.get(f"{ROUTE}?timecode=1:30").text


# Spec: Entry detail page effect | ... (no query means no seek)
def test_a_page_without_the_query_does_not_seek(entry):
    viewer, _ = entry
    assert "data-timecode" not in viewer.get(ROUTE).text
