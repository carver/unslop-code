"""Spec: the `timecode` grammar, its parsing rules and the detail-page seek."""
import pytest

from annotation_helpers import (assert_clean, create, only_annotation,
                                redirect_timecode, stored_annotations)
from digest_helpers import v3, v3_entry
from viewer_helpers import text_of


@pytest.fixture
def vault3(make_vault):
    def _make(entries=None, **kwargs):
        return make_vault(v3(episodes=entries or [v3_entry(id="e1")]),
                          **kwargs)
    return _make


# --------------------------------------------------------------------------
# `timecode` Grammar
# --------------------------------------------------------------------------
# Spec: "| `SS` | `"90"` | `90` |"
def test_seconds_only_form(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="90")
    assert only_annotation(tmp_path)["timecode"] == 90


# Spec: "| `MM:SS` | `"1:30"` | `90` |"
def test_minutes_seconds_form(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="1:30")
    assert only_annotation(tmp_path)["timecode"] == 90


# Spec: "| `HH:MM:SS` | `"1:01:30"` | `3690` |"
def test_hours_minutes_seconds_form(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="1:01:30")
    assert only_annotation(tmp_path)["timecode"] == 3690


# Spec: Determinism -- "`"90"` = `90`, `"1:30"` = `90`, `"1:01:30"` = `3690`,
# `"90:00"` = `5400`".
@pytest.mark.parametrize("text,seconds", [("90", 90), ("1:30", 90),
                                          ("1:01:30", 3690), ("90:00", 5400)])
def test_determinism_table(serve, tmp_path, vault3, text, seconds):
    vault3()
    create(serve(), title="Note", timecode=text)
    assert only_annotation(tmp_path)["timecode"] == seconds


# --------------------------------------------------------------------------
# `timecode` Parsing Rules
# --------------------------------------------------------------------------
# Spec: "| Component type | Non-negative integer |" -- zero is fine.
def test_zero_is_a_valid_timecode(serve, tmp_path, vault3):
    vault3()
    response = create(serve(), title="Note", timecode="0")
    assert response.is_redirect, response
    assert only_annotation(tmp_path)["timecode"] == 0


# Spec: "| Component type | Non-negative integer |" -- a negative component is
# not an accepted component.
@pytest.mark.parametrize("text", ["-1", "-1:30", "1:-30", "1:-1:30"])
def test_negative_components_are_rejected(serve, vault3, text):
    vault3()
    response = create(serve(), title="Note", timecode=text)
    assert response.status == 400, response
    assert_clean(response)


# Spec: "| Component type | Non-negative integer |" -- fractional seconds are
# not an integer component.
@pytest.mark.parametrize("text", ["1.5", "90.0", "1:30.5"])
def test_fractional_components_are_rejected(serve, vault3, text):
    vault3()
    assert create(serve(), title="Note", timecode=text).status == 400


# Spec: "| Leading zeros | Allowed |"
@pytest.mark.parametrize("text,seconds", [("090", 90), ("0090", 90),
                                          ("01:30", 90), ("00:01:30", 90),
                                          ("01:01:30", 3690), ("00", 0)])
def test_leading_zeros_are_allowed(serve, tmp_path, vault3, text, seconds):
    vault3()
    response = create(serve(), title="Note", timecode=text)
    assert response.is_redirect, response
    assert only_annotation(tmp_path)["timecode"] == seconds


# Spec: "| Conventional clock bounds | Not required; `"90:00"` is valid in
# `MM:SS` form |"
def test_out_of_range_minutes_are_valid(serve, tmp_path, vault3):
    vault3()
    response = create(serve(), title="Note", timecode="90:00")
    assert response.is_redirect, response
    assert only_annotation(tmp_path)["timecode"] == 5400


# Spec: "| Conventional clock bounds | Not required ... |" -- seconds beyond
# 59 and minutes beyond 59 in the three-component form are equally fine.
@pytest.mark.parametrize("text,seconds", [("0:99", 99), ("1:99", 159),
                                          ("0:0:99", 99), ("0:99:00", 5940),
                                          ("100:00:00", 360000)])
def test_unconventional_components_are_valid(serve, tmp_path, vault3, text,
                                             seconds):
    vault3()
    response = create(serve(), title="Note", timecode=text)
    assert response.is_redirect, response
    assert only_annotation(tmp_path)["timecode"] == seconds


# Spec: "| Invalid pattern | Return error |" -- non-numeric text.
@pytest.mark.parametrize("text", ["abc", "1m30s", "one:thirty", "90s", "1:3a"])
def test_non_numeric_timecode_is_an_error(serve, vault3, text):
    vault3()
    response = create(serve(), title="Note", timecode=text)
    assert response.status == 400, response
    assert_clean(response)


# Spec: "| Invalid pattern | Return error |" -- too many components, empty
# components and stray separators.
@pytest.mark.parametrize("text", ["1:2:3:4", "", ":", "1:", ":30", "1::30",
                                  "1:2:", "90 ", " 90", "1 : 30"])
def test_malformed_timecode_patterns_are_errors(serve, vault3, text):
    vault3()
    response = create(serve(), title="Note", timecode=text)
    assert response.status == 400, response
    assert_clean(response)


# Spec: "| Invalid pattern | Return error |" -- nothing is stored when the
# timecode does not parse.
def test_invalid_timecode_stores_nothing(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="nope")
    assert stored_annotations(tmp_path) == []


# Spec: "| Create-success redirect value | Integer whole seconds |"
@pytest.mark.parametrize("text,seconds", [("90", "90"), ("1:30", "90"),
                                          ("1:01:30", "3690"),
                                          ("90:00", "5400"), ("0", "0")])
def test_redirect_value_is_integer_seconds(serve, vault3, text, seconds):
    vault3()
    response = create(serve(), title="Note", timecode=text)
    assert redirect_timecode(response) == seconds


# Spec: "| Create-success redirect value | Integer whole seconds |" -- the
# submitted clock text is not echoed back in the query.
def test_redirect_value_is_not_the_submitted_text(serve, vault3):
    vault3()
    response = create(serve(), title="Note", timecode="01:30")
    assert redirect_timecode(response) == "90"
    assert "01:30" not in (response.location or "")


# --------------------------------------------------------------------------
# Entry detail page effect
# --------------------------------------------------------------------------
# Spec: "| Entry detail page effect | Seek playback to `timecode` query value |"
def test_detail_page_uses_the_timecode_query(serve, vault3, save_asset):
    vault3()
    save_asset("media", "e1.mp4")
    page = serve().get("/catalog/vault/episodes/e1?timecode=137")
    assert page.status == 200, page
    assert "137" in page.body


# Spec: "| Entry detail page effect | Seek playback to `timecode` query value |"
# -- the requested position reaches the media element itself.
def test_timecode_query_reaches_the_media_element(serve, vault3, save_asset):
    vault3()
    save_asset("media", "e1.mp4")
    server = serve()
    with_seek = server.get("/catalog/vault/episodes/e1?timecode=125").body
    without = server.get("/catalog/vault/episodes/e1").body
    assert "125" in with_seek
    assert "125" not in without
    assert "<video" in with_seek


# Spec: "| Entry detail page effect | Seek playback to `timecode` query
# value |" -- the page still renders when the query value is unusable.
@pytest.mark.parametrize("value", ["", "abc", "-5", "1:30"])
def test_unusable_timecode_query_still_renders(serve, vault3, value):
    vault3()
    page = serve().get("/catalog/vault/episodes/e1?timecode=%s" % value)
    assert page.status == 200, page
    assert_clean(page)


# Spec: "| Entry detail page effect | Seek playback to `timecode` query
# value |" -- following a create redirect lands on a page carrying the seek.
def test_create_redirect_lands_on_a_seeking_page(serve, vault3, save_asset):
    vault3()
    save_asset("media", "e1.mp4")
    server = serve()
    response = create(server, title="Note", timecode="2:05")
    followed = server.request("GET", response.location)
    assert followed.status == 200, followed
    assert "125" in followed.body


# Spec: "| `timecode` | integer | Whole seconds |" -- the rendered annotation
# shows its position to the reader.
def test_stored_timecode_is_visible_on_the_page(serve, vault3):
    vault3()
    server = serve()
    create(server, title="Marker", timecode="1:30")
    visible = text_of(server.get("/catalog/vault/episodes/e1").body)
    assert "Marker" in visible
    assert "90" in visible or "1:30" in visible
