"""Spec sections: `/catalog/<name>/<category>/<id>` Annotation Methods;
`POST`/`PATCH`/`DELETE` Annotation Fields; `timecode` Grammar and Parsing
Rules; `annotations` Storage and Storage Location; Annotation Auto-Migration
and its rules; Auto-Migration -- Category Transition; Annotation Error
Handling; Determinism."""
import json
import os

import pytest

from annohelp import (
    REDIRECTS,
    annotation_ids,
    backup_json,
    by_id,
    catalog_bytes,
    create,
    entry_path,
    has_traceback,
    location_path,
    location_query,
    stored_annotations,
    stored_entry,
    timecode_param,
    visible_text,
)
from conftest import (
    EPOCH_TO_ISO,
    LEGACY_SOURCE_PREFIX,
    read_catalog,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
)
from detailhelp import build_vault, detail

STAMP = "2024-06-15T09:40:00"


@pytest.fixture
def v3_vault(tmp_path):
    """A v3 vault with entries in every category and one archived video."""
    build_vault(tmp_path, v3_catalog(
        source="https://example.test/source.json",
        episodes=[v3_entry("e1"), v3_entry("e2")],
        streams=[v3_entry("s1")],
        clips=[v3_entry("c1")],
    ), media=["e1.mp4"])
    return "vault"


@pytest.fixture
def v2_vault(tmp_path):
    build_vault(tmp_path, v2_catalog(
        source="https://example.test/source.json",
        episodes=[v2_entry("e1"), v2_entry("e2")],
        streams=[v2_entry("s1")],
    ))
    return "vault"


@pytest.fixture
def v1_vault(tmp_path):
    build_vault(tmp_path, v1_catalog(
        source_id="chan-1",
        entries=[v1_entry("e1"), v1_entry("e2")],
    ))
    return "vault"


def post(client, name="vault", category="episodes", eid="e1", **fields):
    return client.create(entry_path(name, category, eid), fields)


def patch(client, name="vault", category="episodes", eid="e1", **fields):
    return client.patch(entry_path(name, category, eid), fields)


def remove(client, name="vault", category="episodes", eid="e1", **fields):
    return client.delete(entry_path(name, category, eid), fields)


# ---------------------------------------------------------------------------
# `/catalog/<name>/<category>/<id>` Annotation Methods
# ---------------------------------------------------------------------------

# --- Phrase: "| `POST` | Create annotation | JSON with `title`, `timecode`,
#     optional `body` | Redirect to entry detail page with
#     `?timecode=<seconds>` |"
def test_post_creates_an_annotation_and_redirects(viewer, tmp_path, v3_vault):
    response = post(viewer(), title="Intro", timecode="90")
    assert response.status in REDIRECTS, response
    assert location_path(response) == "/catalog/vault/episodes/e1", response
    assert timecode_param(response) == "90", response
    assert len(stored_annotations(tmp_path, "e1")) == 1


# --- Phrase: "| `POST` | Create annotation | JSON with `title`, `timecode`,
#     optional `body` |" (context: `body` may be supplied)
def test_post_accepts_an_optional_body(viewer, tmp_path, v3_vault):
    response, stored = create(viewer(), tmp_path, "vault", "episodes", "e1",
                              title="Intro", timecode="90", body="Notes here")
    assert response.status in REDIRECTS, response
    assert stored["body"] == "Notes here", stored


# --- Phrase: "| `PATCH` | Update annotation | JSON with `id` and at least one
#     of `title` or `body` | Redirect to entry detail page |"
def test_patch_updates_an_annotation_and_redirects(viewer, tmp_path, v3_vault):
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", "episodes", "e1",
                               title="Intro", timecode="90")
    response = patch(client, id=stored["id"], title="Opening")
    assert response.status in REDIRECTS, response
    assert location_path(response) == "/catalog/vault/episodes/e1", response
    assert by_id(tmp_path, "e1", stored["id"])["title"] == "Opening"


# --- Phrase: "| `DELETE` | Delete annotation | JSON with `id` | Redirect to
#     entry detail page |"
def test_delete_removes_an_annotation_and_redirects(viewer, tmp_path,
                                                    v3_vault):
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", "episodes", "e1",
                               title="Intro", timecode="90")
    response = remove(client, id=stored["id"])
    assert response.status in REDIRECTS, response
    assert location_path(response) == "/catalog/vault/episodes/e1", response
    assert stored_annotations(tmp_path, "e1") == []


# --- Phrase: "Redirect to entry detail page" (context: PATCH/DELETE carry no
#     `timecode` query parameter, unlike create)
@pytest.mark.parametrize("verb", ["patch", "delete"])
def test_update_and_delete_redirects_carry_no_timecode(viewer, tmp_path,
                                                       v3_vault, verb):
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", "episodes", "e1",
                               title="Intro", timecode="90")
    if verb == "patch":
        response = patch(client, id=stored["id"], title="Opening")
    else:
        response = remove(client, id=stored["id"])
    assert "timecode" not in location_query(response), response


# --- Phrase: "Entry detail pages support user-managed annotations."
#     (context: the methods live on the entry detail route, per category)
@pytest.mark.parametrize("category,eid", [("streams", "s1"), ("clips", "c1")])
def test_annotation_methods_work_in_every_category(viewer, tmp_path, v3_vault,
                                                   category, eid):
    response, stored = create(viewer(), tmp_path, "vault", category, eid,
                              title="Note", timecode="5")
    assert response.status in REDIRECTS, response
    assert location_path(response) == "/catalog/vault/%s/%s" % (category, eid)
    assert stored["title"] == "Note"


# --- Phrase: "Entry detail pages support user-managed annotations."
#     (context: only the entry detail route; a listing route is not one)
@pytest.mark.parametrize("path", ["/catalog/vault", "/catalog/vault/episodes"])
def test_annotation_methods_are_not_offered_on_other_routes(viewer, v3_vault,
                                                            path):
    client = viewer()
    created = client.create(path, {"title": "x", "timecode": "1"})
    assert created.status not in REDIRECTS or location_path(created) != path
    assert client.patch(path, {"id": "a"}).status == 404
    assert client.delete(path, {"id": "a"}).status == 404


# ---------------------------------------------------------------------------
# `POST` Annotation Fields
# ---------------------------------------------------------------------------

# --- Phrase: "| `title` | string | yes | none |"
def test_post_stores_the_title_it_was_given(viewer, tmp_path, v3_vault):
    _response, stored = create(viewer(), tmp_path, "vault", "episodes", "e1",
                               title="Chapter one", timecode="0")
    assert stored["title"] == "Chapter one", stored


# --- Phrase: "| `timecode` | string | yes | none |"
def test_post_stores_the_parsed_timecode(viewer, tmp_path, v3_vault):
    _response, stored = create(viewer(), tmp_path, "vault", "episodes", "e1",
                               title="Chapter one", timecode="1:30")
    assert stored["timecode"] == 90, stored


# --- Phrase: "| `body` | string | no | `null` |"
def test_post_defaults_a_missing_body_to_null(viewer, tmp_path, v3_vault):
    _response, stored = create(viewer(), tmp_path, "vault", "episodes", "e1",
                               title="Chapter one", timecode="0")
    assert "body" in stored, stored
    assert stored["body"] is None, stored


# --- Phrase: "| `body` | string | no | `null` |" (context: an explicit null
#     is the same as omitting it)
def test_post_accepts_an_explicit_null_body(viewer, tmp_path, v3_vault):
    client = viewer()
    response = client.create(entry_path("vault", "episodes", "e1"),
                             {"title": "T", "timecode": "0", "body": None})
    assert response.status in REDIRECTS, response
    assert stored_annotations(tmp_path, "e1")[0]["body"] is None


# ---------------------------------------------------------------------------
# `PATCH` Annotation Fields
# ---------------------------------------------------------------------------

# --- Phrase: "| `id` | string | yes | Annotation identifier inside current
#     entry |"
def test_patch_only_matches_ids_inside_the_named_entry(viewer, tmp_path,
                                                       v3_vault):
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", "episodes", "e1",
                               title="Intro", timecode="90")
    response = patch(client, eid="e2", id=stored["id"], title="Opening")
    assert response.status == 404, response
    assert by_id(tmp_path, "e1", stored["id"])["title"] == "Intro"


# --- Phrase: "| `title` | string | no | Replace existing title when present |"
def test_patch_replaces_the_title_when_present(viewer, tmp_path, v3_vault):
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", "episodes", "e1",
                               title="Intro", timecode="90", body="Body")
    patch(client, id=stored["id"], title="Opening")
    item = by_id(tmp_path, "e1", stored["id"])
    assert item["title"] == "Opening", item


# --- Phrase: "| `body` | string | no | Replace existing body when present |"
def test_patch_replaces_the_body_when_present(viewer, tmp_path, v3_vault):
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", "episodes", "e1",
                               title="Intro", timecode="90", body="Body")
    patch(client, id=stored["id"], body="Rewritten")
    item = by_id(tmp_path, "e1", stored["id"])
    assert item["body"] == "Rewritten", item


# --- Phrase: "| omitted fields | n/a | allowed | Leave stored value
#     unchanged |" (context: an omitted `body` keeps the stored body)
def test_patch_without_body_leaves_the_stored_body_unchanged(viewer, tmp_path,
                                                             v3_vault):
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", "episodes", "e1",
                               title="Intro", timecode="90", body="Body")
    patch(client, id=stored["id"], title="Opening")
    item = by_id(tmp_path, "e1", stored["id"])
    assert item["body"] == "Body", item


# --- Phrase: "| omitted fields | n/a | allowed | Leave stored value
#     unchanged |" (context: an omitted `title` keeps the stored title)
def test_patch_without_title_leaves_the_stored_title_unchanged(viewer,
                                                               tmp_path,
                                                               v3_vault):
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", "episodes", "e1",
                               title="Intro", timecode="90", body="Body")
    patch(client, id=stored["id"], body="Rewritten")
    item = by_id(tmp_path, "e1", stored["id"])
    assert item["title"] == "Intro", item


# --- Phrase: "| omitted fields | n/a | allowed | Leave stored value
#     unchanged |" (context: `timecode` is never patchable, so it survives)
def test_patch_leaves_the_stored_timecode_unchanged(viewer, tmp_path,
                                                    v3_vault):
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", "episodes", "e1",
                               title="Intro", timecode="1:30")
    patch(client, id=stored["id"], title="Opening", timecode="2:00")
    item = by_id(tmp_path, "e1", stored["id"])
    assert item["timecode"] == 90, item


# --- Phrase: "Annotation identifier inside current entry" (context: the
#     identifier itself is not rewritten by an update)
def test_patch_keeps_the_annotation_id(viewer, tmp_path, v3_vault):
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", "episodes", "e1",
                               title="Intro", timecode="90")
    patch(client, id=stored["id"], title="Opening")
    assert annotation_ids(tmp_path, "e1") == [stored["id"]]


# ---------------------------------------------------------------------------
# `DELETE` Annotation Fields
# ---------------------------------------------------------------------------

# --- Phrase: "| `id` | string | yes |" (context: delete removes exactly the
#     named annotation)
def test_delete_removes_only_the_named_annotation(viewer, tmp_path, v3_vault):
    client = viewer()
    _r1, first = create(client, tmp_path, "vault", "episodes", "e1",
                        title="One", timecode="10")
    _r2, second = create(client, tmp_path, "vault", "episodes", "e1",
                         title="Two", timecode="20")
    remove(client, id=first["id"])
    assert annotation_ids(tmp_path, "e1") == [second["id"]]


# --- Phrase: "| `id` | string | yes |" (context: the id is scoped to the
#     entry in the URL)
def test_delete_only_matches_ids_inside_the_named_entry(viewer, tmp_path,
                                                        v3_vault):
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", "episodes", "e1",
                               title="Intro", timecode="90")
    response = remove(client, eid="e2", id=stored["id"])
    assert response.status == 404, response
    assert annotation_ids(tmp_path, "e1") == [stored["id"]]


# ---------------------------------------------------------------------------
# `timecode` Grammar
# ---------------------------------------------------------------------------

# --- Phrase: "| `SS` | `\"90\"` | `90` |", "| `MM:SS` | `\"1:30\"` | `90` |",
#     "| `HH:MM:SS` | `\"1:01:30\"` | `3690` |"
@pytest.mark.parametrize("text,seconds", [
    ("90", 90),
    ("1:30", 90),
    ("1:01:30", 3690),
])
def test_timecode_grammar_parses_to_whole_seconds(viewer, tmp_path, v3_vault,
                                                  text, seconds):
    _response, stored = create(viewer(), tmp_path, "vault", "episodes", "e1",
                               title="T", timecode=text)
    assert stored["timecode"] == seconds, stored


# --- Phrase: "| `SS` | `\"90\"` | `90` |" (context: the redirect reports the
#     same parsed value)
@pytest.mark.parametrize("text,seconds", [
    ("90", "90"),
    ("1:30", "90"),
    ("1:01:30", "3690"),
])
def test_timecode_grammar_reaches_the_redirect(viewer, v3_vault, text,
                                               seconds):
    response = post(viewer(), title="T", timecode=text)
    assert timecode_param(response) == seconds, response


# ---------------------------------------------------------------------------
# `timecode` Parsing Rules
# ---------------------------------------------------------------------------

# --- Phrase: "| Component type | Non-negative integer |"
@pytest.mark.parametrize("text", ["-1", "-1:30", "1:-30", "1.5", "9e2",
                                  "abc", "1:ab"])
def test_non_integer_or_negative_components_are_rejected(viewer, tmp_path,
                                                         v3_vault, text):
    response = post(viewer(), title="T", timecode=text)
    assert response.status == 400, response
    assert stored_annotations(tmp_path, "e1") == []


# --- Phrase: "| Leading zeros | Allowed |"
@pytest.mark.parametrize("text,seconds", [
    ("090", 90),
    ("01:30", 90),
    ("00:01:30", 90),
    ("0", 0),
    ("00:00", 0),
])
def test_leading_zeros_are_allowed(viewer, tmp_path, v3_vault, text, seconds):
    _response, stored = create(viewer(), tmp_path, "vault", "episodes", "e1",
                               title="T", timecode=text)
    assert stored is not None and stored["timecode"] == seconds, stored


# --- Phrase: "| Conventional clock bounds | Not required; `\"90:00\"` is
#     valid in `MM:SS` form |"
def test_clock_bounds_are_not_enforced(viewer, tmp_path, v3_vault):
    _response, stored = create(viewer(), tmp_path, "vault", "episodes", "e1",
                               title="T", timecode="90:00")
    assert stored["timecode"] == 5400, stored


# --- Phrase: "| Conventional clock bounds | Not required |" (context: the
#     seconds and minutes components may also exceed 59)
@pytest.mark.parametrize("text,seconds", [
    ("1:90", 150),
    ("0:99:99", 6039),
    ("3600", 3600),
])
def test_out_of_range_components_still_parse(viewer, tmp_path, v3_vault, text,
                                             seconds):
    _response, stored = create(viewer(), tmp_path, "vault", "episodes", "e1",
                               title="T", timecode=text)
    assert stored is not None and stored["timecode"] == seconds, stored


# --- Phrase: "| Invalid pattern | Return error |"
@pytest.mark.parametrize("text", ["", ":", "1:", ":30", "1:2:3:4", "1::2",
                                  " 90", "90 ", "1:30:", "12:34:56:78"])
def test_invalid_patterns_return_an_error(viewer, tmp_path, v3_vault, text):
    response = post(viewer(), title="T", timecode=text)
    assert response.status == 400, response
    assert stored_annotations(tmp_path, "e1") == []


# --- Phrase: "| Create-success redirect value | Integer whole seconds |"
@pytest.mark.parametrize("text", ["1:30", "01:30", "0:01:30"])
def test_create_redirect_value_is_integer_whole_seconds(viewer, v3_vault,
                                                        text):
    value = timecode_param(post(viewer(), title="T", timecode=text))
    assert value == "90", value
    assert str(int(value)) == value, value


# --- Phrase: "| Entry detail page effect | Seek playback to `timecode` query
#     value |"
def test_detail_page_seeks_playback_to_the_timecode_query_value(viewer,
                                                                v3_vault):
    client = viewer()
    plain = detail(client, "vault", "episodes", "e1").text
    seeking = client.get("/catalog/vault/episodes/e1?timecode=90").text
    assert seeking != plain, seeking
    assert "90" in seeking, seeking
    assert "#t=90" in seeking, seeking


# --- Phrase: "| Entry detail page effect | Seek playback to `timecode` query
#     value |" (context: following the create redirect lands on a seeking page)
def test_following_the_create_redirect_lands_on_a_seeking_page(viewer,
                                                               v3_vault):
    client = viewer()
    post(client, title="T", timecode="1:30")
    followed = client.get("/catalog/vault/episodes/e1?timecode=90",
                          follow=True)
    assert followed.status == 200, followed
    assert "#t=90" in followed.text, followed


# --- Phrase: "| Entry detail page effect | Seek playback to `timecode` query
#     value |" (context: the player is actually moved to that position)
def test_seeking_page_drives_the_player_to_the_position(viewer, v3_vault):
    text = viewer().get("/catalog/vault/episodes/e1?timecode=1:30").text
    assert "currentTime" in text, text
    assert "90" in text, text


# --- Phrase: "| Entry detail page effect | Seek playback to `timecode` query
#     value |" (context: the query accepts the same grammar a create used)
def test_seek_query_accepts_the_timecode_grammar(viewer, v3_vault):
    client = viewer()
    by_seconds = client.get("/catalog/vault/episodes/e1?timecode=90").text
    by_clock = client.get("/catalog/vault/episodes/e1?timecode=1:30").text
    assert by_seconds == by_clock, (by_seconds, by_clock)


# --- Phrase: "| Entry detail page effect | Seek playback to `timecode` query
#     value |" (context: an unusable query value leaves a well-formed page)
@pytest.mark.parametrize("value", ["abc", "-5", ""])
def test_unparseable_timecode_query_still_renders_the_page(viewer, v3_vault,
                                                           value):
    response = viewer().get("/catalog/vault/episodes/e1?timecode=%s" % value)
    assert response.status == 200, response
    assert not has_traceback(response.text), response


# ---------------------------------------------------------------------------
# `annotations` Storage
# ---------------------------------------------------------------------------

# --- Phrase: "| `id` | string | Unique within entry |"
def test_stored_annotation_ids_are_strings(viewer, tmp_path, v3_vault):
    _response, stored = create(viewer(), tmp_path, "vault", "episodes", "e1",
                               title="T", timecode="0")
    assert isinstance(stored["id"], str) and stored["id"], stored


# --- Phrase: "| `id` | string | Unique within entry |"
def test_stored_annotation_ids_are_unique_within_the_entry(viewer, tmp_path,
                                                           v3_vault):
    client = viewer()
    for index in range(5):
        post(client, title="T%d" % index, timecode=str(index))
    ids = annotation_ids(tmp_path, "e1")
    assert len(ids) == 5 and len(set(ids)) == 5, ids


# --- Phrase: "| `timecode` | integer | Whole seconds |"
def test_stored_timecode_is_an_integer(viewer, tmp_path, v3_vault):
    _response, stored = create(viewer(), tmp_path, "vault", "episodes", "e1",
                               title="T", timecode="1:01:30")
    assert isinstance(stored["timecode"], int), stored
    assert not isinstance(stored["timecode"], bool), stored
    assert stored["timecode"] == 3690, stored


# --- Phrase: "| `title` | string | Stored as provided |"
@pytest.mark.parametrize("title", ["Plain", "", "  spaced  ",
                                   "<b>markup</b> & \"quotes\"", "unicode ✓"])
def test_title_is_stored_exactly_as_provided(viewer, tmp_path, v3_vault,
                                             title):
    _response, stored = create(viewer(), tmp_path, "vault", "episodes", "e1",
                               title=title, timecode="0")
    assert stored is not None and stored["title"] == title, stored


# --- Phrase: "| `body` | string or `null` | Stored as provided or defaulted
#     to `null` |"
@pytest.mark.parametrize("body", ["Some text", "", "multi\nline"])
def test_body_is_stored_exactly_as_provided(viewer, tmp_path, v3_vault, body):
    _response, stored = create(viewer(), tmp_path, "vault", "episodes", "e1",
                               title="T", timecode="0", body=body)
    assert stored is not None and stored["body"] == body, stored


# ---------------------------------------------------------------------------
# `annotations` Storage Location
# ---------------------------------------------------------------------------

# --- Phrase: "| Catalog location | Entry object key `annotations` |"
def test_annotations_live_under_the_entry_annotations_key(viewer, tmp_path,
                                                          v3_vault):
    post(viewer(), title="T", timecode="0")
    item = stored_entry(tmp_path, "e1")
    assert "annotations" in item, item
    assert item["annotations"][0]["title"] == "T", item


# --- Phrase: "| Catalog location | Entry object key `annotations` |"
#     (context: only the addressed entry gains the annotation)
def test_other_entries_are_untouched(viewer, tmp_path, v3_vault):
    post(viewer(), title="T", timecode="0")
    assert stored_annotations(tmp_path, "e2") == []
    assert stored_annotations(tmp_path, "s1", "streams") == []


# --- Phrase: "| Container type | Ordered list |"
def test_annotations_container_is_a_list(viewer, tmp_path, v3_vault):
    post(viewer(), title="T", timecode="0")
    assert isinstance(stored_annotations(tmp_path, "e1"), list)


# --- Phrase: "| List order | Creation order |"
def test_annotations_are_kept_in_creation_order(viewer, tmp_path, v3_vault):
    client = viewer()
    for text in ["third", "first", "second"]:
        post(client, title=text, timecode="0")
    titles = [item["title"] for item in stored_annotations(tmp_path, "e1")]
    assert titles == ["third", "first", "second"], titles


# --- Phrase: "| List order | Creation order |" (context: order does not
#     follow the timecode values)
def test_creation_order_is_not_timecode_order(viewer, tmp_path, v3_vault):
    client = viewer()
    for value in ["300", "10", "200"]:
        post(client, title="at %s" % value, timecode=value)
    codes = [item["timecode"] for item in stored_annotations(tmp_path, "e1")]
    assert codes == [300, 10, 200], codes


# --- Phrase: "| List order | Creation order |" (context: a delete does not
#     reorder the survivors)
def test_delete_preserves_the_order_of_the_survivors(viewer, tmp_path,
                                                     v3_vault):
    client = viewer()
    made = []
    for text in ["a", "b", "c"]:
        made.append(create(client, tmp_path, "vault", "episodes", "e1",
                           title=text, timecode="0")[1])
    remove(client, id=made[1]["id"])
    titles = [item["title"] for item in stored_annotations(tmp_path, "e1")]
    assert titles == ["a", "c"], titles


# --- Phrase: "| List order | Creation order |" (context: an update keeps the
#     annotation in place)
def test_update_preserves_list_position(viewer, tmp_path, v3_vault):
    client = viewer()
    made = []
    for text in ["a", "b", "c"]:
        made.append(create(client, tmp_path, "vault", "episodes", "e1",
                           title=text, timecode="0")[1])
    patch(client, id=made[0]["id"], title="renamed")
    titles = [item["title"] for item in stored_annotations(tmp_path, "e1")]
    assert titles == ["renamed", "b", "c"], titles


# --- Phrase: "| Save behavior | `catalog.bak` written before persisting
#     annotation changes |"
def test_create_writes_a_backup(viewer, tmp_path, v3_vault):
    before = json.loads(catalog_bytes(tmp_path).decode("utf-8"))
    post(viewer(), title="T", timecode="0")
    assert os.path.isfile(os.path.join(str(tmp_path), "vault", "catalog.bak"))
    assert backup_json(tmp_path) == before


# --- Phrase: "| Save behavior | `catalog.bak` written before persisting
#     annotation changes |" (context: update and delete save too)
@pytest.mark.parametrize("verb", ["patch", "delete"])
def test_update_and_delete_write_a_backup(viewer, tmp_path, v3_vault, verb):
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", "episodes", "e1",
                               title="Intro", timecode="0")
    before = json.loads(catalog_bytes(tmp_path).decode("utf-8"))
    if verb == "patch":
        patch(client, id=stored["id"], title="Opening")
    else:
        remove(client, id=stored["id"])
    assert backup_json(tmp_path) == before


# --- Phrase: "| Read-after-write behavior | Later `GET` to same entry detail
#     page reflects create ... by visibly rendering stored annotations |"
def test_detail_page_renders_a_created_annotation(viewer, v3_vault):
    client = viewer()
    post(client, title="Opening titles", timecode="1:30",
         body="The theme plays")
    text = visible_text(detail(client, "vault", "episodes", "e1").text)
    assert "Opening titles" in text, text
    assert "The theme plays" in text, text


# --- Phrase: "| Read-after-write behavior | Later `GET` ... reflects ...
#     update ... |"
def test_detail_page_renders_an_updated_annotation(viewer, tmp_path,
                                                   v3_vault):
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", "episodes", "e1",
                               title="Opening titles", timecode="90")
    patch(client, id=stored["id"], title="Cold open")
    text = visible_text(detail(client, "vault", "episodes", "e1").text)
    assert "Cold open" in text, text
    assert "Opening titles" not in text, text


# --- Phrase: "| Read-after-write behavior | Later `GET` ... reflects ...
#     delete result |"
def test_detail_page_drops_a_deleted_annotation(viewer, tmp_path, v3_vault):
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", "episodes", "e1",
                               title="Opening titles", timecode="90")
    remove(client, id=stored["id"])
    text = visible_text(detail(client, "vault", "episodes", "e1").text)
    assert "Opening titles" not in text, text


# --- Phrase: "visibly rendering stored annotations" (context: in stored
#     order, and only on the entry that owns them)
def test_detail_page_renders_annotations_in_stored_order(viewer, v3_vault):
    client = viewer()
    for text in ["gamma", "alpha", "beta"]:
        post(client, title=text, timecode="0")
    rendered = visible_text(detail(client, "vault", "episodes", "e1").text)
    assert [rendered.index(t) for t in ["gamma", "alpha", "beta"]] == sorted(
        rendered.index(t) for t in ["gamma", "alpha", "beta"]), rendered
    other = visible_text(detail(client, "vault", "episodes", "e2").text)
    assert "gamma" not in other, other


# --- Phrase: "| Read-after-write behavior | Later `GET` to same entry detail
#     page |" (context: a brand new browser sees the same stored state)
def test_stored_annotations_survive_a_server_restart(viewer, tmp_path,
                                                     v3_vault):
    post(viewer(), title="Persisted", timecode="7")
    fresh = viewer()
    text = visible_text(detail(fresh, "vault", "episodes", "e1").text)
    assert "Persisted" in text, text


# ---------------------------------------------------------------------------
# Annotation Auto-Migration
# ---------------------------------------------------------------------------

# --- Phrase: "| v3 | Apply annotation directly |"
def test_v3_vault_is_not_rewritten_beyond_the_annotation(viewer, tmp_path,
                                                         v3_vault):
    before = read_catalog(tmp_path)
    post(viewer(), title="T", timecode="0")
    after = read_catalog(tmp_path)
    assert after["version"] == 3, after
    for item in after["episodes"]:
        if item["id"] != "e1":
            assert item == next(b for b in before["episodes"]
                                if b["id"] == item["id"])


# --- Phrase: "| v2 | Migrate entire catalog to v3 first, then apply
#     annotation, then persist |"
def test_v2_vault_is_migrated_by_an_annotation(viewer, tmp_path, v2_vault):
    response, stored = create(viewer(), tmp_path, "vault", "episodes", "e1",
                              title="T", timecode="90")
    assert response.status in REDIRECTS, response
    catalog = read_catalog(tmp_path)
    assert catalog["version"] == 3, catalog
    assert stored["timecode"] == 90, stored


# --- Phrase: "| v1 | Migrate entire catalog to v3 first, then apply
#     annotation, then persist |"
def test_v1_vault_is_migrated_by_an_annotation(viewer, tmp_path, v1_vault):
    response = post(viewer(), category="entries", title="T", timecode="90")
    assert response.status in REDIRECTS, response
    catalog = read_catalog(tmp_path)
    assert catalog["version"] == 3, catalog
    assert stored_annotations(tmp_path, "e1")[0]["title"] == "T"


# --- Phrase: "Annotation mutations (create, update, delete) require version 3
#     format because the `annotations` field does not exist in v1 or v2
#     entries."
@pytest.mark.parametrize("fixture", ["v1_vault", "v2_vault"])
def test_migration_adds_annotations_to_every_entry(viewer, tmp_path, request,
                                                   fixture):
    request.getfixturevalue(fixture)
    category = "entries" if fixture == "v1_vault" else "episodes"
    post(viewer(), category=category, title="T", timecode="0")
    catalog = read_catalog(tmp_path)
    for group in ("episodes", "streams", "clips"):
        for item in catalog[group]:
            assert isinstance(item.get("annotations"), list), item


# --- Phrase: "| Migration scope | Full catalog migration (same rules as
#     `migrate` command) |"
def test_auto_migration_matches_the_migrate_command(viewer, run, tmp_path):
    build_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")],
                                     streams=[v2_entry("s1")]), name="auto")
    build_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")],
                                     streams=[v2_entry("s1")]), name="cli")
    assert run("migrate", "cli").returncode == 0
    post(viewer(), name="auto", title="T", timecode="0")
    auto = read_catalog(tmp_path, "auto")
    cli = read_catalog(tmp_path, "cli")
    for item in auto["episodes"]:
        if item["id"] == "e1":
            item["annotations"] = []
    for group in ("episodes", "streams", "clips"):
        assert [dict(i, removed={}) for i in auto[group]] == \
               [dict(i, removed={}) for i in cli[group]], group
    assert auto["version"] == cli["version"] == 3
    assert auto["source"] == cli["source"]


# --- Phrase: "| Backup before migration | `catalog.bak` contains the original
#     pre-migration catalog |"
@pytest.mark.parametrize("fixture", ["v1_vault", "v2_vault"])
def test_backup_holds_the_pre_migration_catalog(viewer, tmp_path, request,
                                                fixture):
    request.getfixturevalue(fixture)
    original = json.loads(catalog_bytes(tmp_path).decode("utf-8"))
    category = "entries" if fixture == "v1_vault" else "episodes"
    post(viewer(), category=category, title="T", timecode="0")
    assert backup_json(tmp_path) == original


# --- Phrase: "| Backup before annotation | If catalog was already v3,
#     `catalog.bak` contains pre-annotation catalog |"
def test_backup_of_a_v3_vault_is_the_pre_annotation_catalog(viewer, tmp_path,
                                                            v3_vault):
    original = json.loads(catalog_bytes(tmp_path).decode("utf-8"))
    post(viewer(), title="T", timecode="0")
    backup = backup_json(tmp_path)
    assert backup == original, backup
    assert backup["episodes"][0]["annotations"] == []


# --- Phrase: "| Single write for migration + annotation | ... backup must
#     reflect state before **both** changes |"
def test_backup_shows_neither_migration_nor_annotation(viewer, tmp_path,
                                                       v1_vault):
    post(viewer(), category="entries", title="T", timecode="0")
    backup = backup_json(tmp_path)
    assert backup["version"] == 1, backup
    assert "entries" in backup and "episodes" not in backup, backup
    assert "annotations" not in backup["entries"][0], backup


# --- Phrase: "| v1 UNIX-epoch key conversion | Same rules as `migrate`
#     command |"
def test_auto_migration_converts_epoch_history_keys(viewer, tmp_path):
    build_vault(tmp_path, v1_catalog(entries=[
        v1_entry("e1", stamp="1718444400"),
    ]))
    post(viewer(), category="entries", title="T", timecode="0")
    item = stored_entry(tmp_path, "e1")
    assert list(item["title"]) == [EPOCH_TO_ISO["1718444400"]], item


# --- Phrase: "| v1 `source_id` conversion | Same rules as `migrate` command |"
def test_auto_migration_converts_source_id(viewer, tmp_path, v1_vault):
    post(viewer(), category="entries", title="T", timecode="0")
    catalog = read_catalog(tmp_path)
    assert catalog["source"] == LEGACY_SOURCE_PREFIX + "chan-1", catalog
    assert "source_id" not in catalog, catalog


# --- Phrase: "| Post auto-migration viewer routing | Vault now serves as v3;
#     valid categories become `episodes`, `streams`, `clips` |"
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_v3_categories_are_routable_after_auto_migration(viewer, tmp_path,
                                                         v1_vault, category):
    client = viewer()
    post(client, category="entries", title="T", timecode="0")
    response = client.get("/catalog/vault/%s" % category)
    assert response.status == 200, response


# --- Phrase: "| Post auto-migration viewer routing | ... v1 `entries`
#     category is no longer valid |"
def test_v1_entries_category_is_retired_after_auto_migration(viewer, tmp_path,
                                                             v1_vault):
    client = viewer()
    post(client, category="entries", title="T", timecode="0")
    response = client.get("/catalog/vault/entries")
    assert response.status in REDIRECTS + (404,), response
    if response.status in REDIRECTS:
        assert location_path(response) == "/catalog/vault/episodes", response


# ---------------------------------------------------------------------------
# Auto-Migration -- Category Transition
# ---------------------------------------------------------------------------

# --- Phrase: "| Request URL category | `entries` (v1 category name) |" and
#     "| Entry lookup | Find entry by `id` in the v1 `entries` array |"
def test_v1_annotation_targets_the_pre_migration_category(viewer, tmp_path,
                                                          v1_vault):
    response = post(viewer(), category="entries", eid="e2", title="T",
                    timecode="0")
    assert response.status in REDIRECTS, response
    assert stored_annotations(tmp_path, "e2")[0]["title"] == "T"


# --- Phrase: "| Entry lookup | Find entry by `id` in the v1 `entries`
#     array |" (context: an id that is not there is not found)
def test_v1_annotation_for_an_unknown_id_is_not_found(viewer, tmp_path,
                                                      v1_vault):
    response = post(viewer(), category="entries", eid="nope", title="T",
                    timecode="0")
    assert response.status == 404, response
    assert read_catalog(tmp_path)["version"] == 1


# --- Phrase: "| Request URL category | `entries` (v1 category name) |"
#     (context: `episodes` is not yet a category of a v1 vault, T87)
def test_v1_annotation_through_the_post_migration_category_is_rejected(
        viewer, tmp_path, v1_vault):
    response = post(viewer(), category="episodes", title="T", timecode="0")
    assert response.status == 404, response
    assert read_catalog(tmp_path)["version"] == 1


# --- Phrase: "| Post-migration location | Entry is in `episodes` after
#     migration |"
def test_v1_entry_moves_to_episodes(viewer, tmp_path, v1_vault):
    post(viewer(), category="entries", title="T", timecode="0")
    catalog = read_catalog(tmp_path)
    assert [item["id"] for item in catalog["episodes"]] == ["e1", "e2"]
    assert "entries" not in catalog, catalog


# --- Phrase: "| Redirect after success | Redirect uses post-migration
#     category (`episodes`) |"
def test_v1_annotation_redirect_uses_episodes(viewer, tmp_path, v1_vault):
    response = post(viewer(), category="entries", title="T", timecode="1:30")
    assert location_path(response) == "/catalog/vault/episodes/e1", response
    assert timecode_param(response) == "90", response


# --- Phrase: "| Subsequent requests | Must use `episodes` (v1 `entries` route
#     is retired after migration) |"
def test_subsequent_annotation_requests_use_episodes(viewer, tmp_path,
                                                     v1_vault):
    client = viewer()
    post(client, category="entries", title="first", timecode="0")
    response = post(client, category="episodes", title="second", timecode="0")
    assert response.status in REDIRECTS, response
    titles = [item["title"] for item in stored_annotations(tmp_path, "e1")]
    assert titles == ["first", "second"], titles


# --- Phrase: "| Retired GET behavior | Later `GET` requests to the retired v1
#     `entries` route may redirect to canonical v3 viewer routes or return
#     `404` |"
def test_retired_entries_detail_get_is_handled(viewer, tmp_path, v1_vault):
    client = viewer()
    post(client, category="entries", title="T", timecode="0")
    response = detail(client, "vault", "entries", "e1")
    assert response.status in REDIRECTS + (404,), response
    assert not has_traceback(response.text), response


# --- Phrase: "Pristine v1 and v2 catalogs do not define `annotations`. As a
#     result, `PATCH`/`DELETE` on legacy vaults are only meaningful after
#     auto-migration ..."
@pytest.mark.parametrize("fixture,category", [("v1_vault", "entries"),
                                              ("v2_vault", "episodes")])
def test_patch_on_a_pristine_legacy_vault_is_not_found(viewer, tmp_path,
                                                       request, fixture,
                                                       category):
    request.getfixturevalue(fixture)
    response = patch(viewer(), category=category, id="anything", title="T")
    assert response.status == 404, response


# --- Phrase: "... such as after a prior successful `POST` in the same
#     migrated vault."
@pytest.mark.parametrize("fixture,category", [("v1_vault", "entries"),
                                              ("v2_vault", "episodes")])
def test_patch_after_a_migrating_post_succeeds(viewer, tmp_path, request,
                                               fixture, category):
    request.getfixturevalue(fixture)
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", category, "e1",
                               title="Intro", timecode="0")
    response = patch(client, category="episodes", id=stored["id"],
                     title="Opening")
    assert response.status in REDIRECTS, response
    assert by_id(tmp_path, "e1", stored["id"])["title"] == "Opening"


# --- Phrase: "... such as after a prior successful `POST` in the same
#     migrated vault." (context: delete works the same way)
def test_delete_after_a_migrating_post_succeeds(viewer, tmp_path, v1_vault):
    client = viewer()
    _response, stored = create(client, tmp_path, "vault", "entries", "e1",
                               title="Intro", timecode="0")
    response = remove(client, category="episodes", id=stored["id"])
    assert response.status in REDIRECTS, response
    assert stored_annotations(tmp_path, "e1") == []


# ---------------------------------------------------------------------------
# Annotation Error Handling
# ---------------------------------------------------------------------------

# --- Phrase: "| Missing `title` on create | HTTP `400` with message naming
#     missing field |"
def test_missing_title_on_create_is_a_400_naming_the_field(viewer, tmp_path,
                                                           v3_vault):
    response = viewer().create(entry_path("vault", "episodes", "e1"),
                               {"timecode": "90"})
    assert response.status == 400, response
    assert "title" in response.text, response
    assert stored_annotations(tmp_path, "e1") == []


# --- Phrase: "| Missing `timecode` on create | HTTP `400` with message naming
#     missing field |"
def test_missing_timecode_on_create_is_a_400_naming_the_field(viewer, tmp_path,
                                                              v3_vault):
    response = viewer().create(entry_path("vault", "episodes", "e1"),
                               {"title": "T"})
    assert response.status == 400, response
    assert "timecode" in response.text, response
    assert stored_annotations(tmp_path, "e1") == []


# --- Phrase: "| Missing `title` ... | ... naming missing field |" (context:
#     an empty create body names both required fields)
def test_empty_create_body_names_both_required_fields(viewer, v3_vault):
    response = viewer().create(entry_path("vault", "episodes", "e1"), {})
    assert response.status == 400, response
    assert "title" in response.text and "timecode" in response.text, response


# --- Phrase: "| Invalid `timecode` format | HTTP `400` with format error
#     message |"
def test_invalid_timecode_format_is_a_400_with_a_format_message(viewer,
                                                                v3_vault):
    response = post(viewer(), title="T", timecode="not-a-timecode")
    assert response.status == 400, response
    assert "timecode" in response.text, response


# --- Phrase: "| Missing `id` on update | HTTP `400` with message naming
#     missing field |"
def test_missing_id_on_update_is_a_400_naming_the_field(viewer, tmp_path,
                                                        v3_vault):
    client = viewer()
    create(client, tmp_path, "vault", "episodes", "e1", title="Intro",
           timecode="0")
    response = client.patch(entry_path("vault", "episodes", "e1"),
                            {"title": "Opening"})
    assert response.status == 400, response
    assert "id" in response.text, response
    assert stored_annotations(tmp_path, "e1")[0]["title"] == "Intro"


# --- Phrase: "| Missing `id` on delete | HTTP `400` with message naming
#     missing field |"
def test_missing_id_on_delete_is_a_400_naming_the_field(viewer, tmp_path,
                                                        v3_vault):
    client = viewer()
    create(client, tmp_path, "vault", "episodes", "e1", title="Intro",
           timecode="0")
    response = client.delete(entry_path("vault", "episodes", "e1"), {})
    assert response.status == 400, response
    assert "id" in response.text, response
    assert len(stored_annotations(tmp_path, "e1")) == 1


# --- Phrase: "| Non-existent annotation `id` on update | HTTP `404` |"
def test_unknown_annotation_id_on_update_is_404(viewer, tmp_path, v3_vault):
    client = viewer()
    create(client, tmp_path, "vault", "episodes", "e1", title="Intro",
           timecode="0")
    response = patch(client, id="no-such-annotation", title="Opening")
    assert response.status == 404, response
    assert stored_annotations(tmp_path, "e1")[0]["title"] == "Intro"


# --- Phrase: "| Non-existent annotation `id` on delete | HTTP `404` |"
def test_unknown_annotation_id_on_delete_is_404(viewer, tmp_path, v3_vault):
    client = viewer()
    create(client, tmp_path, "vault", "episodes", "e1", title="Intro",
           timecode="0")
    response = remove(client, id="no-such-annotation")
    assert response.status == 404, response
    assert len(stored_annotations(tmp_path, "e1")) == 1


# --- Phrase: "| Malformed JSON body | HTTP `400` |"
@pytest.mark.parametrize("raw", ["{", "not json", "", "[1, 2]", "\"text\"",
                                 "{'title': 'T'}"])
@pytest.mark.parametrize("verb", ["create", "patch", "delete"])
def test_malformed_json_body_is_400(viewer, tmp_path, v3_vault, verb, raw):
    client = viewer()
    response = getattr(client, verb)(entry_path("vault", "episodes", "e1"),
                                     raw=raw)
    assert response.status == 400, response
    assert stored_annotations(tmp_path, "e1") == []


# --- Phrase: "| Malformed JSON body | HTTP `400` |" (context: no body at all)
@pytest.mark.parametrize("verb", ["create", "patch", "delete"])
def test_absent_body_is_400(viewer, v3_vault, verb):
    response = getattr(viewer(), verb)(entry_path("vault", "episodes", "e1"))
    assert response.status == 400, response


# --- Phrase: "| Migration failure during auto-migration | HTTP `500` with
#     error message; original catalog unchanged |"
def test_migration_failure_is_500_and_leaves_the_catalog_unchanged(viewer,
                                                                   tmp_path):
    broken = v1_entry("e1")
    broken["title"] = {"not-an-epoch": "Title e1"}
    build_vault(tmp_path, v1_catalog(entries=[broken]))
    before = catalog_bytes(tmp_path)
    response = post(viewer(), category="entries", title="T", timecode="0")
    assert response.status == 500, response
    assert response.text.strip(), response
    assert catalog_bytes(tmp_path) == before
    assert not os.path.isfile(os.path.join(str(tmp_path), "vault",
                                           "catalog.bak"))


# --- Phrase: "| Migration failure during auto-migration | HTTP `500` ... |"
#     (context: a v2 catalog that cannot migrate either)
def test_v2_migration_failure_is_500(viewer, tmp_path):
    broken = v2_entry("e1")
    del broken["views"]
    build_vault(tmp_path, v2_catalog(episodes=[broken]))
    before = catalog_bytes(tmp_path)
    response = post(viewer(), title="T", timecode="0")
    assert response.status == 500, response
    assert catalog_bytes(tmp_path) == before


# --- Phrase: "| Any error response | Well-formed HTTP response; no raw
#     traceback or stack trace |"
@pytest.mark.parametrize("verb,fields,raw", [
    ("create", {"timecode": "90"}, None),
    ("create", {"title": "T", "timecode": "??"}, None),
    ("create", None, "{"),
    ("patch", {"title": "T"}, None),
    ("patch", {"id": "nope", "title": "T"}, None),
    ("delete", {}, None),
    ("delete", {"id": "nope"}, None),
])
def test_error_responses_are_well_formed(viewer, v3_vault, verb, fields, raw):
    client = viewer()
    response = getattr(client, verb)(entry_path("vault", "episodes", "e1"),
                                     fields, raw)
    assert 400 <= response.status < 600, response
    assert response.headers.get("Content-Type"), response
    assert not has_traceback(response.text), response
    assert response.body, response


# --- Phrase: "| Any error response | Well-formed HTTP response ... |"
#     (context: an unknown entry or vault is a clean error too)
@pytest.mark.parametrize("path", [
    "/catalog/vault/episodes/nope",
    "/catalog/missing/episodes/e1",
])
def test_annotation_on_an_unknown_target_is_a_clean_error(viewer, v3_vault,
                                                          path):
    response = viewer().create(path, {"title": "T", "timecode": "0"})
    assert response.status >= 300, response
    assert response.status != 200, response
    assert not has_traceback(response.text), response


# --- Phrase: "| Non-existent annotation `id` on update | HTTP `404` |"
#     (context: an unresolvable target outranks a bad body, T80)
def test_unknown_entry_outranks_a_malformed_body(viewer, v3_vault):
    response = viewer().patch("/catalog/vault/episodes/nope", raw="{")
    assert response.status == 404, response


# --- Phrase: "| Migration failure during auto-migration | ... original
#     catalog unchanged |" (context: a rejected mutation persists nothing,
#     so a legacy vault stays legacy, T79)
@pytest.mark.parametrize("verb,fields", [
    ("create", {"title": "T"}),
    ("patch", {"id": "nope", "title": "T"}),
    ("delete", {"id": "nope"}),
])
def test_a_rejected_mutation_leaves_a_v1_vault_unmigrated(viewer, tmp_path,
                                                          v1_vault, verb,
                                                          fields):
    before = catalog_bytes(tmp_path)
    response = getattr(viewer(), verb)(entry_path("vault", "entries", "e1"),
                                       fields)
    assert response.status in (400, 404), response
    assert catalog_bytes(tmp_path) == before
    assert not os.path.isfile(os.path.join(str(tmp_path), "vault",
                                           "catalog.bak"))


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

# --- Phrase: "| Timecode parsing | `\"90\"` = `90`, `\"1:30\"` = `90`,
#     `\"1:01:30\"` = `3690`, `\"90:00\"` = `5400` |"
@pytest.mark.parametrize("text,seconds", [
    ("90", 90),
    ("1:30", 90),
    ("1:01:30", 3690),
    ("90:00", 5400),
])
def test_determinism_of_timecode_parsing(viewer, tmp_path, v3_vault, text,
                                         seconds):
    _response, stored = create(viewer(), tmp_path, "vault", "episodes", "e1",
                               title="T", timecode=text)
    assert stored is not None and stored["timecode"] == seconds, stored
    assert timecode_param(_response) == str(seconds), _response


# --- Phrase: "| Create-success query parameter | Integer seconds only |"
def test_create_query_parameter_is_only_integer_seconds(viewer, v3_vault):
    response = post(viewer(), title="T", timecode="1:01:30")
    query = location_query(response)
    assert list(query) == ["timecode"], response
    assert query["timecode"] == ["3690"], response


# --- Phrase: "| Annotation list order | Same order as stored in
#     `catalog.json` |"
def test_rendered_order_matches_catalog_order(viewer, tmp_path, v3_vault):
    client = viewer()
    for text in ["zulu", "alpha", "mike"]:
        post(client, title=text, timecode="0")
    stored = [item["title"] for item in stored_annotations(tmp_path, "e1")]
    rendered = visible_text(detail(client, "vault", "episodes", "e1").text)
    positions = [rendered.index(title) for title in stored]
    assert positions == sorted(positions), (stored, rendered)


# --- Phrase: "| Auto-migration timestamp | Same timestamp used for all
#     migration-added `removed` fields |"
def test_auto_migration_uses_one_timestamp_for_every_removed_field(viewer,
                                                                   tmp_path):
    build_vault(tmp_path, v1_catalog(entries=[
        v1_entry("e%d" % index) for index in range(4)
    ]))
    post(viewer(), category="entries", title="T", timecode="0")
    catalog = read_catalog(tmp_path)
    stamps = {key for item in catalog["episodes"] for key in item["removed"]}
    assert len(stamps) == 1, stamps
    assert all(item["removed"] == {next(iter(stamps)): False}
               for item in catalog["episodes"]), catalog


# --- Phrase: "| Post auto-migration category | v1 entries always migrate to
#     `episodes` |"
def test_v1_entries_always_land_in_episodes(viewer, tmp_path):
    build_vault(tmp_path, v1_catalog(entries=[v1_entry("e1"), v1_entry("e2"),
                                              v1_entry("e3")]))
    post(viewer(), category="entries", eid="e3", title="T", timecode="0")
    catalog = read_catalog(tmp_path)
    assert [item["id"] for item in catalog["episodes"]] == ["e1", "e2", "e3"]
    assert catalog["streams"] == [] and catalog["clips"] == []


# --- Phrase: "| Redirect after v1 annotation | Uses `episodes`, not
#     `entries` |"
def test_v1_redirect_never_mentions_entries(viewer, tmp_path, v1_vault):
    response = post(viewer(), category="entries", title="T", timecode="0")
    assert "/entries/" not in (response.location or ""), response
    assert location_path(response) == "/catalog/vault/episodes/e1", response


# --- Phrase: "| Annotation list order | Same order as stored in
#     `catalog.json` |" (context: repeated reads are identical)
def test_detail_page_is_identical_across_requests(viewer, v3_vault):
    client = viewer()
    post(client, title="Stable", timecode="42")
    first = detail(client, "vault", "episodes", "e1").text
    second = detail(client, "vault", "episodes", "e1").text
    assert first == second, first
