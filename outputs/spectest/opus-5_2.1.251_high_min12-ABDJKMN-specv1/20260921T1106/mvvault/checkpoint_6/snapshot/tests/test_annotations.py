"""Spec sections: `/catalog/<name>/<category>/<id>` Annotation Methods /
`POST` Annotation Fields / `PATCH` Annotation Fields / `DELETE` Annotation
Fields / `timecode` Grammar / `timecode` Parsing Rules / `annotations` Storage
/ `annotations` Storage Location / Annotation Auto-Migration / Auto-Migration
Rules / Auto-Migration — Category Transition / Annotation Error Handling /
Determinism."""
import json
import os

import pytest
from conftest import (EPOCH, EPOCH_ISO, V1_SOURCE_PREFIX, find, has_backup,
                      make_vault, read_backup, read_catalog, v1_entry,
                      v2_entry, v3_entry)

REDIRECTS = (302, 303)
V2_SOURCE = "http://example.invalid/f.json"


# --------------------------------------------------------------------------
# vault fixtures
# --------------------------------------------------------------------------

def v1_vault(tmp_path, entries=(), name="v", source_id="chan42"):
    return make_vault(tmp_path, name, {"version": 1, "source_id": source_id,
                                       "entries": list(entries)})


def v2_vault(tmp_path, episodes=(), streams=(), clips=(), name="v",
             source=V2_SOURCE):
    return make_vault(tmp_path, name,
                      {"version": 2, "source": source,
                       "episodes": list(episodes), "streams": list(streams),
                       "clips": list(clips)})


def v3_vault(tmp_path, episodes=(), streams=(), clips=(), name="v",
             source=V2_SOURCE):
    return make_vault(tmp_path, name,
                      {"version": 3, "source": source,
                       "episodes": list(episodes), "streams": list(streams),
                       "clips": list(clips)})


def simple_v3(tmp_path, eid="e1", name="v"):
    """A one-entry native vault, the baseline for non-migration behavior."""
    return v3_vault(tmp_path, episodes=[v3_entry(eid)], name=name)


# --------------------------------------------------------------------------
# request helpers
# --------------------------------------------------------------------------

def detail(name, category, eid):
    return "/catalog/%s/%s/%s" % (name, category, eid)


def client(viewer, tmp_path):
    return viewer(cwd=tmp_path).browser()


def call(br, method, name, category, eid, payload=None, raw=None):
    return br.json(method, detail(name, category, eid), payload=payload,
                   raw=raw)


def create(br, name, category, eid, payload):
    return call(br, "POST", name, category, eid, payload)


def update(br, name, category, eid, payload):
    return call(br, "PATCH", name, category, eid, payload)


def remove(br, name, category, eid, payload):
    return call(br, "DELETE", name, category, eid, payload)


def stored(vault, category, eid):
    """The stored `annotations` list of one entry."""
    return find(read_catalog(vault), category, eid).get("annotations")


def only(vault, category, eid):
    items = stored(vault, category, eid)
    assert len(items) == 1, items
    return items[0]


def unescape(text):
    return (text.replace("&quot;", '"').replace("&#39;", "'")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&amp;", "&"))


def path_of(location):
    """The request path of a Location header, absolute or server-relative."""
    assert location, "redirect without a Location header"
    if location.startswith("http://"):
        rest = location.split("/", 3)
        return "/" + rest[3] if len(rest) > 3 else "/"
    return location


def redirect_target(page):
    return path_of(page.location)


def made(br, vault, name, category, eid, title="Intro", timecode="90",
         **extra):
    """Create one annotation and return (response, stored annotation)."""
    payload = {"title": title, "timecode": timecode}
    payload.update(extra)
    page = create(br, name, category, eid, payload)
    assert page.status in REDIRECTS, (page.status, page.body[:300])
    return page


# --------------------------------------------------------------------------
# "Entry detail pages support user-managed annotations."
# --------------------------------------------------------------------------

def test_post_creates_an_annotation_on_a_v3_entry(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1")
    item = only(vault, "episodes", "e1")
    assert item["title"] == "Intro"
    assert item["timecode"] == 90


# Phrase: "Annotations require version 3 catalog format."
def test_annotation_leaves_a_v3_catalog_at_version_3(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1")
    assert read_catalog(vault)["version"] == 3


# Phrase: "Writing an annotation to a v1 or v2 vault triggers automatic
#          migration to v3 before the annotation is persisted."
def test_annotation_on_v1_vault_migrates_to_v3(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("e1")])
    br = client(viewer, tmp_path)
    made(br, vault, "v", "entries", "e1")
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert only(vault, "episodes", "e1")["title"] == "Intro"


def test_annotation_on_v2_vault_migrates_to_v3(viewer, tmp_path):
    vault = v2_vault(tmp_path, episodes=[v2_entry("e1")])
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1")
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert only(vault, "episodes", "e1")["title"] == "Intro"


# --------------------------------------------------------------------------
# Annotation Methods table
# --------------------------------------------------------------------------

# Phrase: "| `POST` | Create annotation | JSON with `title`, `timecode`,
#          optional `body` | Redirect to entry detail page with
#          `?timecode=<seconds>` |"
def test_post_redirects_to_entry_detail_with_timecode_query(viewer, tmp_path):
    simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    page = create(br, "v", "episodes", "e1",
                  {"title": "Intro", "timecode": "1:30"})
    assert page.status in REDIRECTS
    assert redirect_target(page) == "/catalog/v/episodes/e1?timecode=90"


# Phrase: "| `PATCH` | Update annotation | JSON with `id` and at least one of
#          `title` or `body` | Redirect to entry detail page |"
def test_patch_redirects_to_entry_detail_page(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1")
    aid = only(vault, "episodes", "e1")["id"]
    page = update(br, "v", "episodes", "e1", {"id": aid, "title": "Later"})
    assert page.status in REDIRECTS
    assert redirect_target(page).split("?")[0] == "/catalog/v/episodes/e1"


# Phrase: "| `DELETE` | Delete annotation | JSON with `id` | Redirect to entry
#          detail page |"
def test_delete_redirects_to_entry_detail_page(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1")
    aid = only(vault, "episodes", "e1")["id"]
    page = remove(br, "v", "episodes", "e1", {"id": aid})
    assert page.status in REDIRECTS
    assert redirect_target(page).split("?")[0] == "/catalog/v/episodes/e1"
    assert stored(vault, "episodes", "e1") == []


# --------------------------------------------------------------------------
# `POST` Annotation Fields
# --------------------------------------------------------------------------

# Phrase: "| `title` | string | yes | none |"
def test_post_stores_the_supplied_title(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="Cold open")
    assert only(vault, "episodes", "e1")["title"] == "Cold open"


# Phrase: "| `timecode` | string | yes | none |"
def test_post_stores_the_parsed_timecode(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", timecode="1:01:30")
    assert only(vault, "episodes", "e1")["timecode"] == 3690


# Phrase: "| `body` | string | no | `null` |"
def test_post_stores_the_supplied_body(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", body="a note")
    assert only(vault, "episodes", "e1")["body"] == "a note"


# Phrase: "| `body` | string | no | `null` |" (the default when omitted)
def test_post_defaults_body_to_null(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1")
    item = only(vault, "episodes", "e1")
    assert "body" in item and item["body"] is None


# --------------------------------------------------------------------------
# `PATCH` Annotation Fields
# --------------------------------------------------------------------------

# Phrase: "| `id` | string | yes | Annotation identifier inside current entry |"
def test_patch_targets_the_named_annotation_only(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="One", timecode="10")
    made(br, vault, "v", "episodes", "e1", title="Two", timecode="20")
    second = stored(vault, "episodes", "e1")[1]["id"]
    page = update(br, "v", "episodes", "e1", {"id": second, "title": "Edited"})
    assert page.status in REDIRECTS
    items = stored(vault, "episodes", "e1")
    assert [item["title"] for item in items] == ["One", "Edited"]


# Phrase: "| `title` | string | no | Replace existing title when present |"
def test_patch_replaces_the_title(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="Old", body="keep")
    aid = only(vault, "episodes", "e1")["id"]
    update(br, "v", "episodes", "e1", {"id": aid, "title": "New"})
    item = only(vault, "episodes", "e1")
    assert item["title"] == "New"
    assert item["body"] == "keep"


# Phrase: "| `body` | string | no | Replace existing body when present |"
def test_patch_replaces_the_body(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="Keep", body="old")
    aid = only(vault, "episodes", "e1")["id"]
    update(br, "v", "episodes", "e1", {"id": aid, "body": "new"})
    item = only(vault, "episodes", "e1")
    assert item["body"] == "new"
    assert item["title"] == "Keep"


# Phrase: "| omitted fields | n/a | allowed | Leave stored value unchanged |"
def test_patch_leaves_omitted_fields_unchanged(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="T", body="B",
         timecode="2:00")
    aid = only(vault, "episodes", "e1")["id"]
    update(br, "v", "episodes", "e1", {"id": aid, "title": "T2"})
    item = only(vault, "episodes", "e1")
    assert item == {"id": aid, "title": "T2", "body": "B", "timecode": 120}


# Phrase: "| omitted fields | n/a | allowed | Leave stored value unchanged |"
# Context: a `PATCH` never carries `timecode`, so the stored one survives.
def test_patch_does_not_disturb_the_stored_timecode(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", timecode="45")
    aid = only(vault, "episodes", "e1")["id"]
    update(br, "v", "episodes", "e1", {"id": aid, "body": "note"})
    assert only(vault, "episodes", "e1")["timecode"] == 45


# --------------------------------------------------------------------------
# `DELETE` Annotation Fields
# --------------------------------------------------------------------------

# Phrase: "| `id` | string | yes |"
def test_delete_removes_only_the_named_annotation(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="One", timecode="10")
    made(br, vault, "v", "episodes", "e1", title="Two", timecode="20")
    made(br, vault, "v", "episodes", "e1", title="Three", timecode="30")
    ids = [item["id"] for item in stored(vault, "episodes", "e1")]
    remove(br, "v", "episodes", "e1", {"id": ids[1]})
    assert [item["title"] for item in stored(vault, "episodes", "e1")] == \
        ["One", "Three"]


# --------------------------------------------------------------------------
# `timecode` Grammar
# --------------------------------------------------------------------------

# Phrase: "| `SS` | `\"90\"` | `90` |", "| `MM:SS` | `\"1:30\"` | `90` |",
#         "| `HH:MM:SS` | `\"1:01:30\"` | `3690` |"
@pytest.mark.parametrize("text,seconds", [
    ("90", 90),
    ("1:30", 90),
    ("1:01:30", 3690),
])
def test_timecode_grammar_parses_to_whole_seconds(viewer, tmp_path, text,
                                                  seconds):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", timecode=text)
    assert only(vault, "episodes", "e1")["timecode"] == seconds


# --------------------------------------------------------------------------
# `timecode` Parsing Rules
# --------------------------------------------------------------------------

# Phrase: "| Component type | Non-negative integer |"
@pytest.mark.parametrize("text,seconds", [
    ("0", 0),
    ("0:00", 0),
    ("0:00:00", 0),
    ("59", 59),
    ("10:00", 600),
    ("2:00:00", 7200),
])
def test_non_negative_integer_components_parse(viewer, tmp_path, text,
                                               seconds):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", timecode=text)
    assert only(vault, "episodes", "e1")["timecode"] == seconds


# Phrase: "| Leading zeros | Allowed |"
@pytest.mark.parametrize("text,seconds", [
    ("007", 7),
    ("01:30", 90),
    ("00:01:30", 90),
    ("0001:0002:0003", 3723),
])
def test_leading_zeros_are_allowed(viewer, tmp_path, text, seconds):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", timecode=text)
    assert only(vault, "episodes", "e1")["timecode"] == seconds


# Phrase: "| Conventional clock bounds | Not required; `\"90:00\"` is valid in
#          `MM:SS` form |"
def test_out_of_clock_range_minutes_are_valid(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", timecode="90:00")
    assert only(vault, "episodes", "e1")["timecode"] == 5400


# Phrase: "| Conventional clock bounds | Not required ... |"
@pytest.mark.parametrize("text,seconds", [
    ("99", 99),
    ("120", 120),
    ("1:99", 159),
    ("0:75:00", 4500),
    ("100:00:00", 360000),
])
def test_no_upper_bound_on_any_component(viewer, tmp_path, text, seconds):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", timecode=text)
    assert only(vault, "episodes", "e1")["timecode"] == seconds


# Phrase: "| Invalid pattern | Return error |"
@pytest.mark.parametrize("text", [
    "",
    "abc",
    "1:2:3:4",
    "-5",
    "1:-2",
    "1.5",
    "1:30.5",
    ":30",
    "1:",
    "1::30",
    "90 ",
    " 90",
    "1 : 30",
    "+90",
    "1e3",
    "0x10",
])
def test_invalid_timecode_patterns_are_rejected(viewer, tmp_path, text):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    page = create(br, "v", "episodes", "e1",
                  {"title": "T", "timecode": text})
    assert page.status == 400, (text, page.status)
    assert stored(vault, "episodes", "e1") == []


# Phrase: "| Create-success redirect value | Integer whole seconds |"
@pytest.mark.parametrize("text,seconds", [
    ("90", "90"),
    ("1:30", "90"),
    ("1:01:30", "3690"),
    ("90:00", "5400"),
    ("0", "0"),
    ("007", "7"),
])
def test_create_redirect_carries_integer_whole_seconds(viewer, tmp_path, text,
                                                       seconds):
    simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    page = create(br, "v", "episodes", "e1",
                  {"title": "T", "timecode": text})
    assert page.status in REDIRECTS
    assert redirect_target(page) == "/catalog/v/episodes/e1?timecode=" + seconds


# Phrase: "| Entry detail page effect | Seek playback to `timecode` query
#          value |"
def test_detail_page_seeks_playback_to_the_timecode_query_value(viewer,
                                                                tmp_path):
    simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    page = br.get("/catalog/v/episodes/e1?timecode=90")
    assert page.status == 200
    assert 'data-timecode="90"' in page.body


# Phrase: "| Entry detail page effect | Seek playback to `timecode` query
#          value |"
# Context: the create redirect is followed, so the seek reaches the page.
def test_following_the_create_redirect_reaches_a_seeking_page(viewer,
                                                              tmp_path):
    simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    page = create(br, "v", "episodes", "e1",
                  {"title": "T", "timecode": "1:01:30"})
    landed, followed = br.follow(redirect_target(page))
    assert followed.status == 200
    assert 'data-timecode="3690"' in followed.body


# --------------------------------------------------------------------------
# `annotations` Storage
# --------------------------------------------------------------------------

# Phrase: "| `id` | string | Unique within entry |"
def test_annotation_ids_are_strings_unique_within_the_entry(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    for index in range(4):
        made(br, vault, "v", "episodes", "e1", title="T%d" % index,
             timecode=str(index))
    ids = [item["id"] for item in stored(vault, "episodes", "e1")]
    assert all(isinstance(value, str) and value for value in ids)
    assert len(set(ids)) == len(ids)


# Phrase: "| `timecode` | integer | Whole seconds |"
def test_stored_timecode_is_a_json_integer(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", timecode="1:30")
    value = only(vault, "episodes", "e1")["timecode"]
    assert isinstance(value, int) and not isinstance(value, bool)
    raw = open(os.path.join(str(vault), "catalog.json"), encoding="utf-8").read()
    assert '"timecode": 90' in raw


# Phrase: "| `title` | string | Stored as provided |"
def test_title_is_stored_verbatim(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="  Odd <title> & co.  ")
    assert only(vault, "episodes", "e1")["title"] == "  Odd <title> & co.  "


# Phrase: "| `body` | string or `null` | Stored as provided or defaulted to
#          `null` |"
def test_body_is_stored_as_provided_or_null(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="one", timecode="1",
         body="text")
    made(br, vault, "v", "episodes", "e1", title="two", timecode="2")
    items = stored(vault, "episodes", "e1")
    assert [item["body"] for item in items] == ["text", None]


# --------------------------------------------------------------------------
# `annotations` Storage Location
# --------------------------------------------------------------------------

# Phrase: "| Catalog location | Entry object key `annotations` |"
def test_annotation_lives_under_the_entry_annotations_key(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1")
    entry = find(read_catalog(vault), "episodes", "e1")
    assert "annotations" in entry
    assert entry["annotations"][0]["title"] == "Intro"


# Phrase: "| Container type | Ordered list |"
def test_annotations_container_is_a_json_list(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1")
    assert isinstance(stored(vault, "episodes", "e1"), list)


# Phrase: "| List order | Creation order |"
def test_annotations_keep_creation_order(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    for title, code in (("third", "3:00"), ("first", "0:01"),
                        ("second", "0:30")):
        made(br, vault, "v", "episodes", "e1", title=title, timecode=code)
    items = stored(vault, "episodes", "e1")
    assert [item["title"] for item in items] == ["third", "first", "second"]
    assert [item["timecode"] for item in items] == [180, 1, 30]


# Phrase: "| List order | Creation order |"
# Context: a delete does not reorder what is left, and a later create appends.
def test_creation_order_survives_delete_and_recreate(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    for title in ("a", "b", "c"):
        made(br, vault, "v", "episodes", "e1", title=title)
    ids = [item["id"] for item in stored(vault, "episodes", "e1")]
    remove(br, "v", "episodes", "e1", {"id": ids[0]})
    made(br, vault, "v", "episodes", "e1", title="d")
    assert [item["title"] for item in stored(vault, "episodes", "e1")] == \
        ["b", "c", "d"]


# Phrase: "| Save behavior | `catalog.bak` written before persisting
#          annotation changes |"
def test_create_writes_a_backup_of_the_pre_annotation_catalog(viewer,
                                                              tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    before = read_catalog(vault)
    assert not has_backup(vault)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1")
    assert has_backup(vault)
    assert read_backup(vault) == before


# Phrase: "| Save behavior | `catalog.bak` written before persisting
#          annotation changes |"
def test_update_and_delete_also_back_up_first(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="one")
    aid = only(vault, "episodes", "e1")["id"]
    after_create = read_catalog(vault)
    update(br, "v", "episodes", "e1", {"id": aid, "title": "two"})
    assert read_backup(vault) == after_create
    after_update = read_catalog(vault)
    remove(br, "v", "episodes", "e1", {"id": aid})
    assert read_backup(vault) == after_update


# Phrase: "| Read-after-write behavior | Later `GET` to same entry detail page
#          reflects create, update, or delete result by visibly rendering
#          stored annotations, each `timecode` as raw seconds |"
def test_get_after_create_renders_the_annotation(viewer, tmp_path):
    simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    create(br, "v", "episodes", "e1",
           {"title": "Chorus", "timecode": "1:01:30", "body": "sing"})
    page = br.get(detail("v", "episodes", "e1"))
    assert page.status == 200
    text = unescape(page.body)
    assert "Chorus" in text and "sing" in text
    assert "3690" in text


# Phrase: "... each `timecode` as raw seconds"
# Context: raw seconds means the integer, not a re-formatted clock string.
def test_rendered_timecode_is_raw_seconds_not_a_clock_string(viewer,
                                                             tmp_path):
    simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    create(br, "v", "episodes", "e1", {"title": "T", "timecode": "1:01:30"})
    text = unescape(br.get(detail("v", "episodes", "e1")).body)
    assert "3690" in text
    assert "1:01:30" not in text


# Phrase: "| Read-after-write behavior | Later `GET` ... reflects ... update
#          ... |"
def test_get_after_update_shows_the_new_values(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="Before", body="old body")
    aid = only(vault, "episodes", "e1")["id"]
    update(br, "v", "episodes", "e1",
           {"id": aid, "title": "After", "body": "new body"})
    text = unescape(br.get(detail("v", "episodes", "e1")).body)
    assert "After" in text and "new body" in text
    assert "Before" not in text and "old body" not in text


# Phrase: "| Read-after-write behavior | Later `GET` ... reflects ... delete
#          result ... |"
def test_get_after_delete_no_longer_shows_the_annotation(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="Gone soon")
    aid = only(vault, "episodes", "e1")["id"]
    remove(br, "v", "episodes", "e1", {"id": aid})
    text = unescape(br.get(detail("v", "episodes", "e1")).body)
    assert "Gone soon" not in text


# Phrase: "| Read-after-write behavior | Later `GET` ... |"
# Context: a fresh client sees it too; the state is on disk, not in a session.
def test_annotations_are_visible_to_a_new_client(viewer, tmp_path):
    simple_v3(tmp_path)
    server = viewer(cwd=tmp_path)
    create(server.browser(), "v", "episodes", "e1",
           {"title": "Persisted", "timecode": "12"})
    text = unescape(server.browser().get(detail("v", "episodes", "e1")).body)
    assert "Persisted" in text and "12" in text


# --------------------------------------------------------------------------
# Annotation Auto-Migration
# --------------------------------------------------------------------------

# Phrase: "| v1 | Migrate entire catalog to v3 first, then apply annotation,
#          then persist |"
def test_v1_auto_migration_migrates_the_entire_catalog(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("e1"), v1_entry("e2")])
    br = client(viewer, tmp_path)
    made(br, vault, "v", "entries", "e1")
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert set(catalog) == {"version", "source", "episodes", "streams",
                            "clips"}
    assert "entries" not in catalog and "source_id" not in catalog
    assert [item["id"] for item in catalog["episodes"]] == ["e1", "e2"]
    # Every entry gets the v3 shape, not just the annotated one.
    for item in catalog["episodes"]:
        assert item["removed"] == {max(item["removed"]): False}
        assert isinstance(item["annotations"], list)


# Phrase: "| v2 | Migrate entire catalog to v3 first, then apply annotation,
#          then persist |"
def test_v2_auto_migration_migrates_every_category(viewer, tmp_path):
    vault = v2_vault(tmp_path, episodes=[v2_entry("e1")],
                     streams=[v2_entry("s1")], clips=[v2_entry("c1")])
    br = client(viewer, tmp_path)
    made(br, vault, "v", "streams", "s1")
    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert catalog["source"] == V2_SOURCE
    for category, eid in (("episodes", "e1"), ("streams", "s1"),
                          ("clips", "c1")):
        item = find(catalog, category, eid)
        assert item["removed"] == {max(item["removed"]): False}
        assert isinstance(item["annotations"], list)
    assert only(vault, "streams", "s1")["title"] == "Intro"
    assert stored(vault, "episodes", "e1") == []


# Phrase: "| v3 | Apply annotation directly |"
def test_v3_vault_is_not_rewritten_beyond_the_annotation(viewer, tmp_path):
    entry = v3_entry("e1")
    vault = v3_vault(tmp_path, episodes=[entry])
    before = read_catalog(vault)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1")
    after = read_catalog(vault)
    stamped = find(after, "episodes", "e1")
    annotations = stamped.pop("annotations")
    assert len(annotations) == 1
    before_entry = find(before, "episodes", "e1")
    before_entry.pop("annotations")
    assert stamped == before_entry
    assert after["version"] == 3 and after["source"] == before["source"]


# --------------------------------------------------------------------------
# Auto-Migration Rules
# --------------------------------------------------------------------------

# Phrase: "| Migration scope | Full catalog migration (same rules as `migrate`
#          command) |"
def test_auto_migration_matches_the_migrate_command(viewer, tmp_path, run):
    catalog = {"version": 1, "source_id": "chan42",
               "entries": [v1_entry("e1"), v1_entry("e2", epoch=999999999)]}
    auto = make_vault(tmp_path, "auto", catalog)
    manual = make_vault(tmp_path, "manual", catalog)
    assert run("migrate", "manual", cwd=tmp_path).returncode == 0
    br = client(viewer, tmp_path)
    made(br, auto, "auto", "entries", "e1")
    produced = read_catalog(auto)
    expected = read_catalog(manual)
    # The two runs stamp `removed` at their own moment; compare the rest.
    for item in produced["episodes"]:
        item.pop("annotations")
        item["removed"] = sorted(item["removed"].values())
    for item in expected["episodes"]:
        item.pop("annotations")
        item["removed"] = sorted(item["removed"].values())
    assert produced == expected


# Phrase: "| Backup before migration | `catalog.bak` contains the original
#          pre-migration catalog |"
def test_backup_holds_the_original_v1_catalog(viewer, tmp_path):
    original = {"version": 1, "source_id": "chan42",
                "entries": [v1_entry("e1")]}
    vault = make_vault(tmp_path, "v", original)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "entries", "e1")
    assert read_backup(vault) == original


# Phrase: "| Backup before migration | ... |" (v2 form)
def test_backup_holds_the_original_v2_catalog(viewer, tmp_path):
    original = {"version": 2, "source": V2_SOURCE,
                "episodes": [v2_entry("e1")], "streams": [], "clips": []}
    vault = make_vault(tmp_path, "v", original)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1")
    assert read_backup(vault) == original


# Phrase: "| Backup before annotation | If catalog was already v3,
#          `catalog.bak` contains pre-annotation catalog |"
def test_v3_backup_holds_the_pre_annotation_catalog(viewer, tmp_path):
    original = {"version": 3, "source": V2_SOURCE,
                "episodes": [v3_entry("e1")], "streams": [], "clips": []}
    vault = make_vault(tmp_path, "v", original)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1")
    assert read_backup(vault) == original
    assert stored(vault, "episodes", "e1")[0]["title"] == "Intro"


# Phrase: "| Single write for migration + annotation | Migration and
#          annotation may be persisted in one write; backup must reflect state
#          before **both** changes |"
def test_backup_is_pre_migration_and_pre_annotation(viewer, tmp_path):
    original = {"version": 1, "source_id": "chan42",
                "entries": [v1_entry("e1")]}
    vault = make_vault(tmp_path, "v", original)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "entries", "e1")
    backup = read_backup(vault)
    assert backup["version"] == 1
    assert "annotations" not in backup["entries"][0]
    assert read_catalog(vault)["version"] == 3


# Phrase: "| v1 UNIX-epoch key conversion | Same rules as `migrate` command |"
def test_v1_epoch_keys_become_iso_timestamps(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("e1", epoch=EPOCH)])
    br = client(viewer, tmp_path)
    made(br, vault, "v", "entries", "e1")
    item = find(read_catalog(vault), "episodes", "e1")
    for field in ("title", "description", "views", "likes", "preview"):
        assert list(item[field]) == [EPOCH_ISO]


# Phrase: "| v1 `source_id` conversion | Same rules as `migrate` command |"
def test_v1_source_id_becomes_the_derived_source_url(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("e1")], source_id="chan42")
    br = client(viewer, tmp_path)
    made(br, vault, "v", "entries", "e1")
    catalog = read_catalog(vault)
    assert catalog["source"] == V1_SOURCE_PREFIX + "chan42"
    assert "source_id" not in catalog


# Phrase: "| Post auto-migration viewer routing | Vault now serves as v3;
#          valid categories become `episodes`, `streams`, `clips` ... |"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v3_categories_serve_after_auto_migration(viewer, tmp_path, category):
    vault = v1_vault(tmp_path, [v1_entry("e1")])
    br = client(viewer, tmp_path)
    made(br, vault, "v", "entries", "e1")
    page = br.get("/catalog/v/%s" % category)
    assert page.status == 200


# Phrase: "... v1 `entries` category is no longer valid"
def test_entries_category_is_retired_after_auto_migration(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("e1")])
    br = client(viewer, tmp_path)
    made(br, vault, "v", "entries", "e1")
    page = br.get("/catalog/v/entries")
    assert page.status in REDIRECTS + (404,)
    if page.status in REDIRECTS:
        assert redirect_target(page) == "/catalog/v/episodes"


# Phrase: "| Retired GET behavior | Later `GET` requests to the retired v1
#          `entries` route may redirect to canonical v3 viewer routes or
#          return `404` |"
def test_retired_entry_detail_route_redirects_or_404s(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("e1")])
    br = client(viewer, tmp_path)
    made(br, vault, "v", "entries", "e1")
    page = br.get(detail("v", "entries", "e1"))
    assert page.status in REDIRECTS + (404,)
    if page.status in REDIRECTS:
        landed, followed = br.follow(detail("v", "entries", "e1"))
        assert followed.status == 200
        assert landed.startswith("/catalog/v/episodes")


# --------------------------------------------------------------------------
# Auto-Migration — Category Transition
# --------------------------------------------------------------------------

# Phrase: "| Request URL category | `entries` (v1 category name) |" and
#         "| Entry lookup | Find entry by `id` in the v1 `entries` array |"
def test_v1_annotation_targets_the_pre_migration_category(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("e1"), v1_entry("e2")])
    br = client(viewer, tmp_path)
    page = create(br, "v", "entries", "e2",
                  {"title": "Second", "timecode": "5"})
    assert page.status in REDIRECTS, page.body[:300]
    assert only(vault, "episodes", "e2")["title"] == "Second"
    assert stored(vault, "episodes", "e1") == []


# Phrase: "| Post-migration location | Entry is in `episodes` after migration |"
def test_annotated_v1_entry_lands_in_episodes(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("e1")])
    br = client(viewer, tmp_path)
    made(br, vault, "v", "entries", "e1")
    catalog = read_catalog(vault)
    assert [item["id"] for item in catalog["episodes"]] == ["e1"]
    assert catalog["streams"] == [] and catalog["clips"] == []


# Phrase: "| Redirect after success | Redirect uses post-migration category
#          (`episodes`) |"
def test_v1_create_redirect_uses_episodes(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1")])
    br = client(viewer, tmp_path)
    page = create(br, "v", "entries", "e1",
                  {"title": "T", "timecode": "1:30"})
    assert redirect_target(page) == "/catalog/v/episodes/e1?timecode=90"


# Phrase: "| Subsequent requests | Must use `episodes` (v1 `entries` route is
#          retired after migration) |"
def test_subsequent_annotation_requests_use_episodes(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("e1")])
    br = client(viewer, tmp_path)
    made(br, vault, "v", "entries", "e1", title="first")
    aid = only(vault, "episodes", "e1")["id"]
    page = update(br, "v", "episodes", "e1", {"id": aid, "title": "edited"})
    assert page.status in REDIRECTS
    assert only(vault, "episodes", "e1")["title"] == "edited"
    page = create(br, "v", "episodes", "e1", {"title": "second",
                                              "timecode": "2:00"})
    assert page.status in REDIRECTS
    assert [item["title"] for item in stored(vault, "episodes", "e1")] == \
        ["edited", "second"]


# Phrase: "| Subsequent requests | Must use `episodes` ... |"
# Context: the retired `entries` route no longer reaches the entry.
def test_entries_route_no_longer_accepts_annotations(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("e1")])
    br = client(viewer, tmp_path)
    made(br, vault, "v", "entries", "e1", title="first")
    page = create(br, "v", "entries", "e1", {"title": "second",
                                             "timecode": "3"})
    assert page.status == 404
    assert len(stored(vault, "episodes", "e1")) == 1


# Phrase: "Pristine v1 and v2 catalogs do not define `annotations`. As a
#          result, `PATCH`/`DELETE` on legacy vaults are only meaningful after
#          auto-migration has produced an entry that already contains
#          annotations ..."
@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_patch_or_delete_on_a_pristine_v1_vault_is_not_found(viewer, tmp_path,
                                                             method):
    vault = v1_vault(tmp_path, [v1_entry("e1")])
    br = client(viewer, tmp_path)
    page = call(br, method, "v", "entries", "e1",
                {"id": "anything", "title": "x"})
    assert page.status == 404
    assert read_catalog(vault)["version"] == 1
    assert not has_backup(vault)


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_patch_or_delete_on_a_pristine_v2_vault_is_not_found(viewer, tmp_path,
                                                             method):
    vault = v2_vault(tmp_path, episodes=[v2_entry("e1")])
    br = client(viewer, tmp_path)
    page = call(br, method, "v", "episodes", "e1",
                {"id": "anything", "title": "x"})
    assert page.status == 404
    assert read_catalog(vault)["version"] == 2
    assert not has_backup(vault)


# Phrase: "... such as after a prior successful `POST` in the same migrated
#          vault."
def test_patch_and_delete_work_after_a_migrating_post(viewer, tmp_path):
    vault = v2_vault(tmp_path, episodes=[v2_entry("e1")])
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="first", body="b")
    aid = only(vault, "episodes", "e1")["id"]
    assert update(br, "v", "episodes", "e1",
                  {"id": aid, "body": "edited"}).status in REDIRECTS
    assert only(vault, "episodes", "e1")["body"] == "edited"
    assert remove(br, "v", "episodes", "e1", {"id": aid}).status in REDIRECTS
    assert stored(vault, "episodes", "e1") == []


# --------------------------------------------------------------------------
# Annotation Error Handling
# --------------------------------------------------------------------------

def assert_clean_error(page, status):
    assert page.status == status, (page.status, page.body[:300])
    assert page.body, "error responses carry a body"
    assert "Traceback" not in page.body
    assert "File \"" not in page.body


# Phrase: "| Missing `title` on create | HTTP `400` with message naming
#          missing field |"
def test_create_without_title_is_400_naming_title(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    page = create(br, "v", "episodes", "e1", {"timecode": "90"})
    assert_clean_error(page, 400)
    assert "title" in unescape(page.body).lower()
    assert stored(vault, "episodes", "e1") == []


# Phrase: "| Missing `timecode` on create | HTTP `400` with message naming
#          missing field |"
def test_create_without_timecode_is_400_naming_timecode(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    page = create(br, "v", "episodes", "e1", {"title": "T"})
    assert_clean_error(page, 400)
    assert "timecode" in unescape(page.body).lower()
    assert stored(vault, "episodes", "e1") == []


# Phrase: "| Invalid `timecode` format | HTTP `400` with format error
#          message |"
def test_invalid_timecode_is_400_with_a_format_message(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    page = create(br, "v", "episodes", "e1",
                  {"title": "T", "timecode": "12:ab"})
    assert_clean_error(page, 400)
    assert "timecode" in unescape(page.body).lower()
    assert stored(vault, "episodes", "e1") == []


# Phrase: "| Missing `id` on update | HTTP `400` with message naming missing
#          field |"
def test_update_without_id_is_400_naming_id(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="keep")
    page = update(br, "v", "episodes", "e1", {"title": "x"})
    assert_clean_error(page, 400)
    assert "id" in unescape(page.body).lower()
    assert only(vault, "episodes", "e1")["title"] == "keep"


# Phrase: "| Missing `id` on delete | HTTP `400` with message naming missing
#          field |"
def test_delete_without_id_is_400_naming_id(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="keep")
    page = remove(br, "v", "episodes", "e1", {})
    assert_clean_error(page, 400)
    assert "id" in unescape(page.body).lower()
    assert len(stored(vault, "episodes", "e1")) == 1


# Phrase: "| Non-existent annotation `id` on update | HTTP `404` |"
def test_update_of_unknown_annotation_is_404(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="keep")
    page = update(br, "v", "episodes", "e1",
                  {"id": "no-such-id", "title": "x"})
    assert_clean_error(page, 404)
    assert only(vault, "episodes", "e1")["title"] == "keep"


# Phrase: "| Non-existent annotation `id` on delete | HTTP `404` |"
def test_delete_of_unknown_annotation_is_404(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="keep")
    page = remove(br, "v", "episodes", "e1", {"id": "no-such-id"})
    assert_clean_error(page, 404)
    assert len(stored(vault, "episodes", "e1")) == 1


# Phrase: "| Non-existent annotation `id` on update | HTTP `404` |"
# Context: an id belonging to a different entry is not "inside current entry".
def test_annotation_id_from_another_entry_is_404(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1"), v3_entry("e2")])
    br = client(viewer, tmp_path)
    made(br, vault, "v", "episodes", "e1", title="mine")
    aid = only(vault, "episodes", "e1")["id"]
    page = update(br, "v", "episodes", "e2", {"id": aid, "title": "x"})
    assert_clean_error(page, 404)
    assert only(vault, "episodes", "e1")["title"] == "mine"


# Phrase: "| Malformed JSON body | HTTP `400` |"
@pytest.mark.parametrize("raw", [
    "{",
    "not json at all",
    '{"title": "T", "timecode": "90",}',
    "",
    "[]",
    '"just a string"',
    "null",
])
def test_malformed_json_body_is_400(viewer, tmp_path, raw):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    page = call(br, "POST", "v", "episodes", "e1", raw=raw)
    assert_clean_error(page, 400)
    assert stored(vault, "episodes", "e1") == []


# Phrase: "| Malformed JSON body | HTTP `400` |" (all three methods)
@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_malformed_json_is_400_for_every_method(viewer, tmp_path, method):
    simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    page = call(br, method, "v", "episodes", "e1", raw="{oops}")
    assert_clean_error(page, 400)


# Phrase: "| Migration failure during auto-migration | HTTP `500` with error
#          message; original catalog unchanged |"
def test_migration_failure_is_500_and_leaves_the_catalog_alone(viewer,
                                                               tmp_path):
    # A v1 entry whose history key is not epoch seconds fails `migrate`.
    broken = {"version": 1, "source_id": "chan42",
              "entries": [{"id": "e1", "published": "2024-01-01T00:00:00",
                           "width": 1920, "height": 1080,
                           "title": {"not-an-epoch": "T"},
                           "description": {"1718444400": "D"},
                           "views": {"1718444400": 1},
                           "likes": {"1718444400": 1},
                           "preview": {"1718444400": "p"}}]}
    vault = make_vault(tmp_path, "v", broken)
    br = client(viewer, tmp_path)
    page = create(br, "v", "entries", "e1", {"title": "T", "timecode": "1"})
    assert_clean_error(page, 500)
    assert read_catalog(vault) == broken
    assert not has_backup(vault)


# Phrase: "| Migration failure during auto-migration | HTTP `500` ... |"
# Context: a v1 catalog with no `source_id` cannot be migrated either.
def test_migration_failure_without_source_id_is_500(viewer, tmp_path):
    broken = {"version": 1, "entries": [v1_entry("e1")]}
    vault = make_vault(tmp_path, "v", broken)
    br = client(viewer, tmp_path)
    page = create(br, "v", "entries", "e1", {"title": "T", "timecode": "1"})
    assert_clean_error(page, 500)
    assert read_catalog(vault) == broken


# Phrase: "| Any error response | Well-formed HTTP response; no raw traceback
#          or stack trace |"
@pytest.mark.parametrize("method,payload", [
    ("POST", {"timecode": "90"}),
    ("POST", {"title": "T", "timecode": "nope"}),
    ("PATCH", {"title": "T"}),
    ("PATCH", {"id": "zz", "title": "T"}),
    ("DELETE", {}),
    ("DELETE", {"id": "zz"}),
])
def test_error_responses_are_well_formed(viewer, tmp_path, method, payload):
    simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    page = call(br, method, "v", "episodes", "e1", payload)
    assert page.status in (400, 404)
    assert page.header("Content-Type")
    assert "Traceback" not in page.body
    assert "<html" in page.body.lower()


# Phrase: "| Any error response | Well-formed HTTP response ... |"
# Context: an unknown entry id in a valid category.
def test_annotation_on_unknown_entry_is_404(viewer, tmp_path):
    simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    page = create(br, "v", "episodes", "nope",
                  {"title": "T", "timecode": "1"})
    assert_clean_error(page, 404)


# Phrase: "| Any error response | Well-formed HTTP response ... |"
# Context: a vault that does not exist at all.
def test_annotation_on_missing_vault_does_not_crash(viewer, tmp_path):
    br = client(viewer, tmp_path)
    page = create(br, "ghost", "episodes", "e1",
                  {"title": "T", "timecode": "1"})
    assert page.status in (404,) + REDIRECTS
    assert "Traceback" not in page.body


# Phrase: "| Any error response | ... |"
# Context: a category the stored version does not expose.
def test_annotation_on_a_foreign_category_is_404(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("e1")])
    br = client(viewer, tmp_path)
    page = create(br, "v", "episodes", "e1", {"title": "T", "timecode": "1"})
    assert page.status == 404
    assert read_catalog(vault)["version"] == 1


# Phrase: "Annotation mutations (create, update, delete) require version 3
#          format ..." — a rejected request never migrates the vault.
def test_a_rejected_create_does_not_migrate_the_vault(viewer, tmp_path):
    original = {"version": 1, "source_id": "chan42",
                "entries": [v1_entry("e1")]}
    vault = make_vault(tmp_path, "v", original)
    br = client(viewer, tmp_path)
    page = create(br, "v", "entries", "e1", {"title": "T"})
    assert page.status == 400
    assert read_catalog(vault) == original
    assert not has_backup(vault)


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------

# Phrase: "| Timecode parsing | `\"90\"` = `90`, `\"1:30\"` = `90`,
#          `\"1:01:30\"` = `3690`, `\"90:00\"` = `5400` |"
def test_determinism_timecode_table(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    for text in ("90", "1:30", "1:01:30", "90:00"):
        made(br, vault, "v", "episodes", "e1", title=text, timecode=text)
    assert [item["timecode"] for item in stored(vault, "episodes", "e1")] == \
        [90, 90, 3690, 5400]


# Phrase: "| Create-success query parameter | Integer seconds only |"
def test_determinism_query_parameter_is_integer_seconds_only(viewer,
                                                             tmp_path):
    simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    page = create(br, "v", "episodes", "e1",
                  {"title": "T", "timecode": "0090"})
    target = redirect_target(page)
    assert target.endswith("?timecode=90")
    assert "0090" not in target


# Phrase: "| Annotation list order | Same order as stored in `catalog.json` |"
def test_determinism_rendered_order_matches_stored_order(viewer, tmp_path):
    vault = simple_v3(tmp_path)
    br = client(viewer, tmp_path)
    for title, code in (("zeta", "10:00"), ("alpha", "0:05"),
                        ("centre", "1:00")):
        made(br, vault, "v", "episodes", "e1", title=title, timecode=code)
    text = unescape(br.get(detail("v", "episodes", "e1")).body)
    positions = [text.index(title) for title in ("zeta", "alpha", "centre")]
    assert positions == sorted(positions)
    assert [item["title"] for item in stored(vault, "episodes", "e1")] == \
        ["zeta", "alpha", "centre"]


# Phrase: "| Auto-migration timestamp | Same timestamp used for all
#          migration-added `removed` fields |"
def test_determinism_one_timestamp_for_every_removed_field(viewer, tmp_path):
    entries = [v1_entry("e%d" % index) for index in range(5)]
    vault = v1_vault(tmp_path, entries)
    br = client(viewer, tmp_path)
    made(br, vault, "v", "entries", "e0")
    stamps = set()
    for item in read_catalog(vault)["episodes"]:
        assert list(item["removed"].values()) == [False]
        stamps.update(item["removed"])
    assert len(stamps) == 1


# Phrase: "| Post auto-migration category | v1 entries always migrate to
#          `episodes` |"
def test_determinism_v1_entries_always_land_in_episodes(viewer, tmp_path):
    vault = v1_vault(tmp_path, [v1_entry("a"), v1_entry("b")])
    br = client(viewer, tmp_path)
    made(br, vault, "v", "entries", "b")
    catalog = read_catalog(vault)
    assert sorted(item["id"] for item in catalog["episodes"]) == ["a", "b"]
    assert catalog["streams"] == [] and catalog["clips"] == []


# Phrase: "| Redirect after v1 annotation | Uses `episodes`, not `entries` |"
def test_determinism_v1_redirect_never_mentions_entries(viewer, tmp_path):
    v1_vault(tmp_path, [v1_entry("e1")])
    br = client(viewer, tmp_path)
    page = create(br, "v", "entries", "e1", {"title": "T", "timecode": "7"})
    target = redirect_target(page)
    assert "/episodes/" in target and "/entries/" not in target
