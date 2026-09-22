"""Annotation methods, fields, the `timecode` grammar and `annotations` storage."""

import json

import pytest

from conftest import SOURCE_URL, read_catalog, stored_annotations, v3_catalog, v3_entry

ENTRY = "/catalog/v/episodes/a"


def entry_vault(served, entry=None, **assets):
    """A served v3 vault holding one episode `a`, plus the client talking to it."""
    return served(v3_catalog(SOURCE_URL, episodes=[entry or v3_entry("a")]), **assets)


def location(response):
    """The `Location` of an unfollowed annotation redirect."""
    assert response.status_code in (302, 303), (response.status_code, response.text[:300])
    return response.headers["Location"]


def create(client, title="note", timecode="90", path=ENTRY, **fields):
    """`POST` one annotation, asserting the route answered with its redirect."""
    payload = {"title": title, "timecode": timecode, **fields}
    response = client.send_json("POST", path, payload)
    location(response)
    return response


def only_id(vault):
    """The id of the single annotation stored on episode `a`."""
    stored = stored_annotations(vault)
    assert len(stored) == 1, stored
    return stored[0]["id"]


# Spec: `POST` | Create annotation | JSON with `title`, `timecode`, optional `body`
def test_post_creates_an_annotation_on_the_entry(served, tmp_path):
    create(entry_vault(served), title="opening", timecode="90")
    assert [(one["title"], one["timecode"]) for one in stored_annotations(tmp_path / "v")] == [("opening", 90)]


# Spec: `POST` | Success Result | Redirect to entry detail page with
# `?timecode=<seconds>`
def test_post_redirects_to_the_entry_detail_page_with_the_timecode(served, tmp_path):
    response = create(entry_vault(served), timecode="1:30")
    assert location(response) == f"{ENTRY}?timecode=90"


# Spec: `PATCH` | Update annotation | JSON with `id` and at least one of `title`
# or `body`
def test_patch_updates_the_named_annotation(served, tmp_path):
    client = entry_vault(served)
    create(client)
    client.send_json("PATCH", ENTRY, {"id": only_id(tmp_path / "v"), "title": "renamed"})
    assert [one["title"] for one in stored_annotations(tmp_path / "v")] == ["renamed"]


# Spec: `PATCH` | Success Result | Redirect to entry detail page
def test_patch_redirects_to_the_entry_detail_page(served, tmp_path):
    client = entry_vault(served)
    create(client)
    response = client.send_json("PATCH", ENTRY, {"id": only_id(tmp_path / "v"), "title": "renamed"})
    assert location(response) == ENTRY


# Spec: `DELETE` | Delete annotation | JSON with `id`
def test_delete_removes_the_named_annotation(served, tmp_path):
    client = entry_vault(served)
    create(client)
    client.send_json("DELETE", ENTRY, {"id": only_id(tmp_path / "v")})
    assert stored_annotations(tmp_path / "v") == []


# Spec: `DELETE` | Success Result | Redirect to entry detail page
def test_delete_redirects_to_the_entry_detail_page(served, tmp_path):
    client = entry_vault(served)
    create(client)
    response = client.send_json("DELETE", ENTRY, {"id": only_id(tmp_path / "v")})
    assert location(response) == ENTRY


# Spec: `DELETE` | Delete annotation (the other annotations are left alone)
def test_delete_leaves_the_remaining_annotations(served, tmp_path):
    client = entry_vault(served)
    create(client, title="first")
    create(client, title="second")
    client.send_json("DELETE", ENTRY, {"id": stored_annotations(tmp_path / "v")[0]["id"]})
    assert [one["title"] for one in stored_annotations(tmp_path / "v")] == ["second"]


# Spec: Annotation Methods | the methods answer on
# `/catalog/<name>/<category>/<id>` (every category of the vault)
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_annotation_methods_answer_on_every_category_route(served, tmp_path, category):
    catalog = v3_catalog(SOURCE_URL, **{category: [v3_entry("a")]})
    client = served(catalog)
    create(client, path=f"/catalog/v/{category}/a")
    assert len(stored_annotations(tmp_path / "v", category)) == 1


# Spec: `POST` Annotation Fields | `title` | string | required
def test_post_stores_the_title_as_provided(served, tmp_path):
    create(entry_vault(served), title="  Spaced & <odd> tïtle  ")
    assert stored_annotations(tmp_path / "v")[0]["title"] == "  Spaced & <odd> tïtle  "


# Spec: `POST` Annotation Fields | `body` | string | no | Default `null`
def test_post_defaults_the_body_to_null(served, tmp_path):
    create(entry_vault(served))
    assert stored_annotations(tmp_path / "v")[0]["body"] is None


# Spec: `POST` Annotation Fields | `body` | string (stored as provided)
def test_post_stores_the_body_when_given(served, tmp_path):
    create(entry_vault(served), body="a longer remark")
    assert stored_annotations(tmp_path / "v")[0]["body"] == "a longer remark"


# Spec: `PATCH` Annotation Fields | `title` | Replace existing title when present
def test_patch_replaces_the_title_when_present(served, tmp_path):
    client = entry_vault(served)
    create(client, title="before", body="kept")
    client.send_json("PATCH", ENTRY, {"id": only_id(tmp_path / "v"), "title": "after"})
    assert stored_annotations(tmp_path / "v")[0] == {
        "id": only_id(tmp_path / "v"),
        "timecode": 90,
        "title": "after",
        "body": "kept",
    }


# Spec: `PATCH` Annotation Fields | `body` | Replace existing body when present
def test_patch_replaces_the_body_when_present(served, tmp_path):
    client = entry_vault(served)
    create(client, body="before")
    client.send_json("PATCH", ENTRY, {"id": only_id(tmp_path / "v"), "body": "after"})
    assert stored_annotations(tmp_path / "v")[0]["body"] == "after"


# Spec: `PATCH` Annotation Fields | omitted fields | Leave stored value unchanged
def test_patch_leaves_omitted_fields_unchanged(served, tmp_path):
    client = entry_vault(served)
    create(client, title="kept title", body="kept body")
    client.send_json("PATCH", ENTRY, {"id": only_id(tmp_path / "v"), "title": "new title"})
    stored = stored_annotations(tmp_path / "v")[0]
    assert (stored["body"], stored["timecode"]) == ("kept body", 90)


# Spec: `PATCH` Annotation Fields | both fields may be sent together
def test_patch_can_replace_title_and_body_at_once(served, tmp_path):
    client = entry_vault(served)
    create(client, title="before", body="before body")
    client.send_json("PATCH", ENTRY, {"id": only_id(tmp_path / "v"), "title": "t", "body": "b"})
    stored = stored_annotations(tmp_path / "v")[0]
    assert (stored["title"], stored["body"]) == ("t", "b")


# Spec: `PATCH` Annotation Fields | `id` | Annotation identifier inside current entry
def test_patch_only_reaches_annotations_of_the_addressed_entry(served, tmp_path):
    catalog = v3_catalog(SOURCE_URL, episodes=[v3_entry("a"), v3_entry("b")])
    client = served(catalog)
    create(client, title="on a")
    other = stored_annotations(tmp_path / "v")[0]["id"]
    assert client.send_json("PATCH", "/catalog/v/episodes/b", {"id": other, "title": "x"}).status_code == 404


# Spec: `timecode` Grammar | `SS` `"90"` = 90; `MM:SS` `"1:30"` = 90;
# `HH:MM:SS` `"1:01:30"` = 3690
@pytest.mark.parametrize(("text", "seconds"), [("90", 90), ("1:30", 90), ("1:01:30", 3690)])
def test_timecode_grammar_parses_each_documented_format(served, tmp_path, text, seconds):
    create(entry_vault(served), timecode=text)
    assert stored_annotations(tmp_path / "v")[0]["timecode"] == seconds


# Spec: `timecode` Parsing Rules | Leading zeros | Allowed
@pytest.mark.parametrize(("text", "seconds"), [("007", 7), ("01:05", 65), ("00:02:03", 123)])
def test_timecode_allows_leading_zeros(served, tmp_path, text, seconds):
    create(entry_vault(served), timecode=text)
    assert stored_annotations(tmp_path / "v")[0]["timecode"] == seconds


# Spec: `timecode` Parsing Rules | Conventional clock bounds | Not required;
# `"90:00"` is valid in `MM:SS` form
@pytest.mark.parametrize(("text", "seconds"), [("90:00", 5400), ("0:90", 90), ("1:99:99", 9639)])
def test_timecode_does_not_enforce_clock_bounds(served, tmp_path, text, seconds):
    create(entry_vault(served), timecode=text)
    assert stored_annotations(tmp_path / "v")[0]["timecode"] == seconds


# Spec: `timecode` Parsing Rules | Component type | Non-negative integer
def test_timecode_accepts_zero(served, tmp_path):
    create(entry_vault(served), timecode="0")
    assert stored_annotations(tmp_path / "v")[0]["timecode"] == 0


# Spec: `timecode` Parsing Rules | Create-success redirect value | Integer whole seconds
def test_create_redirect_carries_integer_whole_seconds(served):
    assert location(create(entry_vault(served), timecode="1:01:30")) == f"{ENTRY}?timecode=3690"


# Spec: `timecode` Parsing Rules | Entry detail page effect | Seek playback to
# `timecode` query value
def test_detail_page_seeks_playback_to_the_timecode_query_value(served):
    client = entry_vault(served, media=["a-episode.mp4"])
    body = client.get(f"{ENTRY}?timecode=90").text
    assert 'data-timecode="90"' in body
    assert "#t=90" in body


# Spec: Entry detail page effect | Seek playback to `timecode` query value
# (no query value: nothing is sought)
def test_detail_page_without_a_timecode_query_seeks_nothing(served):
    body = entry_vault(served, media=["a-episode.mp4"]).get(ENTRY).text
    assert "data-timecode" not in body
    assert "#t=" not in body


# Spec: `annotations` Storage | `id` | string | Unique within entry
def test_stored_ids_are_unique_strings_within_the_entry(served, tmp_path):
    client = entry_vault(served)
    for index in range(3):
        create(client, title=f"note-{index}")
    ids = [one["id"] for one in stored_annotations(tmp_path / "v")]
    assert len(set(ids)) == 3
    assert all(isinstance(one, str) for one in ids)


# Spec: `annotations` Storage | `timecode` | integer | Whole seconds
def test_stored_timecode_is_a_json_integer(served, tmp_path):
    create(entry_vault(served), timecode="1:30")
    stored = stored_annotations(tmp_path / "v")[0]["timecode"]
    assert isinstance(stored, int) and not isinstance(stored, bool)


# Spec: `annotations` Storage | `body` | string or `null`
def test_stored_body_is_written_as_json_null_when_defaulted(served, tmp_path):
    create(entry_vault(served))
    assert '"body": null' in (tmp_path / "v" / "catalog.json").read_text()


# Spec: `annotations` Storage Location | Catalog location | Entry object key
# `annotations`
def test_annotations_live_under_the_entry_object_key(served, tmp_path):
    create(entry_vault(served))
    entry = read_catalog(tmp_path / "v")["episodes"][0]
    assert sorted(entry["annotations"][0]) == ["body", "id", "timecode", "title"]


# Spec: `annotations` Storage Location | Container type | Ordered list
def test_the_annotations_container_is_a_json_list(served, tmp_path):
    create(entry_vault(served))
    assert isinstance(read_catalog(tmp_path / "v")["episodes"][0]["annotations"], list)


# Spec: `annotations` Storage Location | List order | Creation order
def test_annotations_are_stored_in_creation_order(served, tmp_path):
    client = entry_vault(served)
    for title, timecode in [("third", "3"), ("first", "1"), ("second", "2")]:
        create(client, title=title, timecode=timecode)
    assert [one["title"] for one in stored_annotations(tmp_path / "v")] == ["third", "first", "second"]


# Spec: List order | Creation order (an update keeps the annotation in place)
def test_an_update_keeps_the_annotation_in_its_created_position(served, tmp_path):
    client = entry_vault(served)
    create(client, title="first")
    create(client, title="second")
    first = stored_annotations(tmp_path / "v")[0]["id"]
    client.send_json("PATCH", ENTRY, {"id": first, "title": "renamed"})
    assert [one["title"] for one in stored_annotations(tmp_path / "v")] == ["renamed", "second"]


# Spec: Save behavior | `catalog.bak` written before persisting annotation changes
def test_creating_an_annotation_writes_the_backup_first(served, tmp_path):
    client = entry_vault(served)
    before = (tmp_path / "v" / "catalog.json").read_text()
    create(client)
    assert (tmp_path / "v" / "catalog.bak").read_text() == before


# Spec: Save behavior | `catalog.bak` written before persisting annotation changes
# (update and delete persist through the same backed-up write)
@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_update_and_delete_write_the_backup_first(served, tmp_path, method):
    client = entry_vault(served)
    create(client)
    before = (tmp_path / "v" / "catalog.json").read_text()
    client.send_json(method, ENTRY, {"id": only_id(tmp_path / "v"), "title": "renamed"})
    assert (tmp_path / "v" / "catalog.bak").read_text() == before
    assert json.loads(before)["episodes"][0]["annotations"][0]["title"] == "note"


# Spec: Read-after-write behavior | Later `GET` ... reflects create ... by
# visibly rendering stored annotations
def test_a_later_get_renders_a_created_annotation(served):
    client = entry_vault(served)
    create(client, title="opening credits")
    assert "opening credits" in client.get(ENTRY).text


# Spec: Read-after-write behavior | Later `GET` ... reflects update
def test_a_later_get_renders_an_updated_annotation(served, tmp_path):
    client = entry_vault(served)
    create(client, title="before", body="old body")
    client.send_json("PATCH", ENTRY, {"id": only_id(tmp_path / "v"), "title": "after", "body": "new body"})
    body = client.get(ENTRY).text
    assert "after" in body and "new body" in body
    assert "old body" not in body


# Spec: Read-after-write behavior | Later `GET` ... reflects delete
def test_a_later_get_no_longer_renders_a_deleted_annotation(served, tmp_path):
    client = entry_vault(served)
    create(client, title="temporary")
    client.send_json("DELETE", ENTRY, {"id": only_id(tmp_path / "v")})
    assert "temporary" not in client.get(ENTRY).text


# Spec: Read-after-write behavior | ... by visibly rendering stored annotations
# (the stored body is rendered too)
def test_the_detail_page_renders_the_annotation_body(served):
    client = entry_vault(served)
    create(client, title="note", body="the remark")
    assert "the remark" in client.get(ENTRY).text


# Spec: Determinism | Timecode parsing | `"90"` = 90, `"1:30"` = 90,
# `"1:01:30"` = 3690, `"90:00"` = 5400
@pytest.mark.parametrize(("text", "seconds"), [("90", 90), ("1:30", 90), ("1:01:30", 3690), ("90:00", 5400)])
def test_determinism_of_timecode_parsing(served, text, seconds):
    assert location(create(entry_vault(served), timecode=text)) == f"{ENTRY}?timecode={seconds}"


# Spec: Determinism | Create-success query parameter | Integer seconds only
def test_create_query_parameter_is_bare_integer_seconds(served):
    assert location(create(entry_vault(served), timecode="02:00")).endswith("?timecode=120")


# Spec: Determinism | Annotation list order | Same order as stored in `catalog.json`
def test_the_page_lists_annotations_in_stored_order(served, tmp_path):
    client = entry_vault(served)
    for title in ["alpha", "bravo", "charlie"]:
        create(client, title=title)
    body = client.get(ENTRY).text
    stored = [one["title"] for one in stored_annotations(tmp_path / "v")]
    assert sorted(stored, key=body.index) == stored
