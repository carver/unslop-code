"""Spec section: `timecode` Grammar and `timecode` Parsing Rules."""

from __future__ import annotations

import pytest


def one_episode(catalogs, make_vault, entry_id="e1"):
    make_vault(catalogs.catalog(episodes=[catalogs.entry(entry_id)]))


def create_timecode(client, annotate, text):
    return annotate.create(client, "vault", "episodes", "e1",
                           {"title": "Note", "timecode": text})


# ---------------------------------------------------------------------------
# | Format | Example | Parsed Seconds |
# ---------------------------------------------------------------------------

# Spec: | `SS` | `"90"` | `90` |
def test_seconds_form(serve, make_vault, catalogs, annotate, workdir):
    one_episode(catalogs, make_vault)
    create_timecode(serve().client, annotate, "90")
    assert annotate.only(workdir, "vault", "e1")["timecode"] == 90


# Spec: | `MM:SS` | `"1:30"` | `90` |
def test_minutes_seconds_form(serve, make_vault, catalogs, annotate, workdir):
    one_episode(catalogs, make_vault)
    create_timecode(serve().client, annotate, "1:30")
    assert annotate.only(workdir, "vault", "e1")["timecode"] == 90


# Spec: | `HH:MM:SS` | `"1:01:30"` | `3690` |
def test_hours_minutes_seconds_form(serve, make_vault, catalogs, annotate,
                                    workdir):
    one_episode(catalogs, make_vault)
    create_timecode(serve().client, annotate, "1:01:30")
    assert annotate.only(workdir, "vault", "e1")["timecode"] == 3690


# Spec: | Timecode parsing | `"90"` = `90`, `"1:30"` = `90`,
#   `"1:01:30"` = `3690`, `"90:00"` = `5400` | (Determinism)
@pytest.mark.parametrize("text,seconds", [
    ("90", 90),
    ("1:30", 90),
    ("1:01:30", 3690),
    ("90:00", 5400),
])
def test_determinism_table_of_timecodes(serve, make_vault, catalogs, annotate,
                                        workdir, text, seconds):
    one_episode(catalogs, make_vault)
    create_timecode(serve().client, annotate, text)
    assert annotate.only(workdir, "vault", "e1")["timecode"] == seconds


# ---------------------------------------------------------------------------
# | Rule Area | Required Behavior |
# ---------------------------------------------------------------------------

# Spec: | Component type | Non-negative integer |
@pytest.mark.parametrize("text,seconds", [
    ("0", 0),
    ("0:00", 0),
    ("0:00:00", 0),
])
def test_zero_components_are_non_negative_integers(serve, make_vault, catalogs,
                                                   annotate, workdir, text,
                                                   seconds):
    one_episode(catalogs, make_vault)
    create_timecode(serve().client, annotate, text)
    assert annotate.only(workdir, "vault", "e1")["timecode"] == seconds


# Spec: | Component type | Non-negative integer | | Invalid pattern | Return
#   error |
@pytest.mark.parametrize("text", ["-1", "-1:30", "1:-30"])
def test_negative_components_are_rejected(serve, make_vault, catalogs,
                                          annotate, text):
    one_episode(catalogs, make_vault)
    assert create_timecode(serve().client, annotate, text).status == 400


# Spec: | Leading zeros | Allowed |
@pytest.mark.parametrize("text,seconds", [
    ("090", 90),
    ("01:30", 90),
    ("00:01:30", 90),
    ("0000090", 90),
])
def test_leading_zeros_are_allowed(serve, make_vault, catalogs, annotate,
                                   workdir, text, seconds):
    one_episode(catalogs, make_vault)
    create_timecode(serve().client, annotate, text)
    assert annotate.only(workdir, "vault", "e1")["timecode"] == seconds


# Spec: | Conventional clock bounds | Not required; `"90:00"` is valid in
#   `MM:SS` form |
def test_out_of_range_minutes_are_valid(serve, make_vault, catalogs, annotate,
                                        workdir):
    one_episode(catalogs, make_vault)
    create_timecode(serve().client, annotate, "90:00")
    assert annotate.only(workdir, "vault", "e1")["timecode"] == 5400


# Spec: | Conventional clock bounds | Not required | ...
# Context: the same freedom applies to the seconds component and to `HH:MM:SS`.
@pytest.mark.parametrize("text,seconds", [
    ("1:90", 150),           # 60 + 90
    ("0:0:90", 90),
    ("1:99:99", 9639),       # 3600 + 5940 + 99
    ("100:00:00", 360000),
])
def test_components_are_unbounded(serve, make_vault, catalogs, annotate,
                                  workdir, text, seconds):
    one_episode(catalogs, make_vault)
    create_timecode(serve().client, annotate, text)
    assert annotate.only(workdir, "vault", "e1")["timecode"] == seconds


# Spec: | Invalid pattern | Return error |
# Context: T72 - the grammar is exactly one to three colon-separated runs of
# digits, so everything else is an invalid pattern.
@pytest.mark.parametrize("text", [
    "",                 # nothing at all
    "abc",              # not digits
    "1:2:3:4",          # a fourth component
    ":30",              # empty leading component
    "1:",               # empty trailing component
    "1::30",            # empty middle component
    "1.5",              # decimal
    "90s",              # unit suffix
    " 90",              # leading space
    "90 ",              # trailing space
    "1;30",             # wrong separator
    "+90",              # explicit sign
    "9_0",              # digit separator
])
def test_invalid_timecode_patterns_are_rejected(serve, make_vault, catalogs,
                                                annotate, text):
    one_episode(catalogs, make_vault)
    assert create_timecode(serve().client, annotate, text).status == 400


# Spec: | Invalid pattern | Return error | + | `timecode` | string | yes |
# Context: T72 - a JSON number is not the string the field table requires.
@pytest.mark.parametrize("value", [90, 1.5, True, None, ["90"], {"s": 90}])
def test_non_string_timecode_is_rejected(serve, make_vault, catalogs, annotate,
                                         value):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1",
                               {"title": "Note", "timecode": value})
    assert response.status == 400, response.status


# Spec: | Invalid pattern | Return error |
# Context: a rejected timecode stores nothing.
def test_rejected_timecode_stores_nothing(serve, make_vault, catalogs,
                                          annotate, workdir):
    one_episode(catalogs, make_vault)
    create_timecode(serve().client, annotate, "nope")
    assert annotate.stored(workdir, "vault", "e1") == []


# ---------------------------------------------------------------------------
# | Create-success redirect value | Integer whole seconds |
# ---------------------------------------------------------------------------

# Spec: | Create-success redirect value | Integer whole seconds |
@pytest.mark.parametrize("text,seconds", [
    ("90", "90"),
    ("1:30", "90"),
    ("1:01:30", "3690"),
    ("90:00", "5400"),
    ("01:30", "90"),
    ("0", "0"),
])
def test_redirect_carries_whole_seconds(serve, make_vault, catalogs, annotate,
                                        text, seconds):
    one_episode(catalogs, make_vault)
    response = create_timecode(serve().client, annotate, text)
    assert annotate.timecode(response) == seconds


# Spec: | Create-success query parameter | Integer seconds only | (Determinism)
# Context: the query value is the parsed number, never the submitted text.
def test_redirect_never_echoes_clock_text(serve, make_vault, catalogs,
                                          annotate):
    one_episode(catalogs, make_vault)
    response = create_timecode(serve().client, annotate, "1:01:30")
    assert "1:01:30" not in (response.location or "")
    assert annotate.timecode(response) == "3690"


# ---------------------------------------------------------------------------
# | Entry detail page effect | Seek playback to `timecode` query value |
# ---------------------------------------------------------------------------

# Spec: | Entry detail page effect | Seek playback to `timecode` query value |
# Context: T75 - the seek is expressed in the rendered media reference, so the
# fixture puts a downloaded media file in place for the page to point at.
def test_detail_page_seeks_to_the_timecode_query(serve, make_vault, catalogs,
                                                 detail, workdir):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_media(vault, "e1.mp4")
    page = serve().client.get("/catalog/vault/episodes/e1?timecode=90").body
    assert "90" in page
    assert "#t=90" in page or 'data-timecode="90"' in page, page


# Spec: | Entry detail page effect | Seek playback to `timecode` query value |
# Context: without the query the page carries no seek position.
def test_detail_page_without_timecode_has_no_seek(serve, make_vault, catalogs,
                                                  detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_media(vault, "e1.mp4")
    page = serve().client.get("/catalog/vault/episodes/e1").body
    assert "#t=" not in page, page


# Spec: | Entry detail page effect | Seek playback to `timecode` query value |
# Context: the create redirect is meant to be followed, so the page it lands
# on is seeked to the new annotation.
def test_create_redirect_lands_on_a_seeked_page(serve, make_vault, catalogs,
                                                annotate, detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_media(vault, "e1.mp4")
    client = serve().client
    response = annotate.create(client, "vault", "episodes", "e1",
                               {"title": "Note", "timecode": "1:30"},
                               follow=True)
    assert response.status == 200
    assert "#t=90" in response.body or 'data-timecode="90"' in response.body


# Spec: | Entry detail page effect | Seek playback to `timecode` query value |
# Context: T75 - the query value is a `timecode`, so clock text seeks to the
# same place as the equivalent second count.
def test_clock_text_in_the_query_seeks_to_the_same_place(serve, make_vault,
                                                         catalogs, detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_media(vault, "e1.mp4")
    client = serve().client
    from_clock = client.get("/catalog/vault/episodes/e1?timecode=1:30").body
    from_seconds = client.get("/catalog/vault/episodes/e1?timecode=90").body
    assert from_clock == from_seconds


# Spec: | Entry detail page effect | Seek playback to `timecode` query value |
# Context: T75 - the error table covers request bodies, so a junk query value
# still renders the page.
def test_unparsable_timecode_query_still_renders(serve, make_vault, catalogs,
                                                 detail):
    vault = make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    detail.write_media(vault, "e1.mp4")
    response = serve().client.get("/catalog/vault/episodes/e1?timecode=abc")
    assert response.status == 200, response.status
    assert "Title e1" in response.body
