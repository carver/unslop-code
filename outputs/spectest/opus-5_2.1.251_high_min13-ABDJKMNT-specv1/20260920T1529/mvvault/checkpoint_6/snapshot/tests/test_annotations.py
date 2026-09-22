"""Spec sections: the annotation methods of `/catalog/<name>/<category>/<id>`,
the `POST`/`PATCH`/`DELETE` field tables, the `timecode` grammar and its parsing
rules, `annotations` storage and its location, and the annotation error table."""

import pytest
from conftest import (
    V2_KEY,
    entry_by_id,
    place_media,
    read_backup,
    read_catalog,
    v3_catalog,
    v3_entry,
    write_vault,
)

SOURCE = "https://example.test/a"
ENTRY = "/catalog/demo/episodes/e1"
REDIRECTS = (302, 303)


def v3_vault(tmp_path, name="demo", **categories):
    return write_vault(tmp_path, v3_catalog(SOURCE, **categories), name=name)


def create(viewer, path=ENTRY, **fields):
    """`POST` one annotation, sending exactly the fields named."""
    return viewer.send_json("POST", path, fields)


def update(viewer, path=ENTRY, **fields):
    return viewer.send_json("PATCH", path, fields)


def remove(viewer, path=ENTRY, **fields):
    return viewer.send_json("DELETE", path, fields)


def stored(vault, category="episodes", entry_id="e1"):
    """The annotations the catalog on disk holds for one entry."""
    return entry_by_id(read_catalog(vault), category, entry_id)["annotations"]


def only(vault, **lookup):
    """The single stored annotation of an entry."""
    annotations = stored(vault, **lookup)
    assert len(annotations) == 1, annotations
    return annotations[0]


# Annotation Methods: "`POST` | Create annotation | JSON with `title`,
# `timecode`, optional `body`", and "Entry detail pages support user-managed
# annotations."
def test_post_creates_an_annotation_on_the_entry(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = create(viewer, title="a note", timecode="90")

    assert response.status in REDIRECTS
    assert only(vault)["title"] == "a note"


# Annotation Methods: "`POST` | ... | Redirect to entry detail page with
# `?timecode=<seconds>`".
def test_post_redirects_to_the_entry_detail_page_with_the_timecode(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = create(viewer, title="a note", timecode="1:30")

    assert response.location == f"{ENTRY}?timecode=90"


# Annotation Methods: "`PATCH` | Update annotation | JSON with `id` and at least
# one of `title` or `body` | Redirect to entry detail page".
def test_patch_updates_the_annotation_and_redirects_to_the_entry(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    create(viewer, title="first", timecode="10")

    response = update(viewer, id=only(vault)["id"], title="second")

    assert response.status in REDIRECTS
    assert response.location == ENTRY
    assert only(vault)["title"] == "second"


# Annotation Methods: "`DELETE` | Delete annotation | JSON with `id` | Redirect
# to entry detail page".
def test_delete_removes_the_annotation_and_redirects_to_the_entry(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    create(viewer, title="a note", timecode="10")

    response = remove(viewer, id=only(vault)["id"])

    assert response.status in REDIRECTS
    assert response.location == ENTRY
    assert stored(vault) == []


# `POST` Annotation Fields: "`body` | string | no | `null`".
def test_post_defaults_a_missing_body_to_null(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    create(viewer, title="a note", timecode="10")

    assert only(vault)["body"] is None


# `POST` Annotation Fields: "`body` | string | no" — a supplied body is kept.
def test_post_stores_a_supplied_body(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    create(viewer, title="a note", timecode="10", body="the long text")

    assert only(vault)["body"] == "the long text"


# `PATCH` Annotation Fields: "`title` | string | no | Replace existing title
# when present".
def test_patch_replaces_the_title_when_present(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    create(viewer, title="before", timecode="10", body="kept")

    update(viewer, id=only(vault)["id"], title="after")

    assert only(vault)["title"] == "after"


# `PATCH` Annotation Fields: "`body` | string | no | Replace existing body when
# present".
def test_patch_replaces_the_body_when_present(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    create(viewer, title="a note", timecode="10", body="before")

    update(viewer, id=only(vault)["id"], body="after")

    assert only(vault)["body"] == "after"


# `PATCH` Annotation Fields: "omitted fields | n/a | allowed | Leave stored
# value unchanged".
def test_patch_leaves_omitted_fields_unchanged(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    create(viewer, title="a note", timecode="1:30", body="the body")
    annotation_id = only(vault)["id"]

    update(viewer, id=annotation_id, title="renamed")

    assert only(vault) == {
        "id": annotation_id,
        "timecode": 90,
        "title": "renamed",
        "body": "the body",
    }


# `PATCH` Annotation Fields: "`id` | string | yes | Annotation identifier inside
# current entry" — another entry's annotation of the same id is not reached.
def test_patch_only_reaches_the_current_entry(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1"), v3_entry("e2")])
    create(viewer, title="on e1", timecode="10")
    create(viewer, path="/catalog/demo/episodes/e2", title="on e2", timecode="10")
    shared_id = only(vault)["id"]
    assert only(vault, entry_id="e2")["id"] == shared_id

    update(viewer, id=shared_id, title="renamed")

    assert only(vault)["title"] == "renamed"
    assert only(vault, entry_id="e2")["title"] == "on e2"


# `DELETE` Annotation Fields: "`id` | string | yes" — the named annotation is
# the only one removed.
def test_delete_removes_only_the_named_annotation(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    create(viewer, title="first", timecode="10")
    create(viewer, title="second", timecode="20")

    remove(viewer, id=stored(vault)[0]["id"])

    assert [note["title"] for note in stored(vault)] == ["second"]


# `timecode` Grammar: "`SS` | `"90"` | `90`", "`MM:SS` | `"1:30"` | `90`",
# "`HH:MM:SS` | `"1:01:30"` | `3690`"; Determinism: "`"90:00"` = `5400`".
@pytest.mark.parametrize(
    "timecode,seconds",
    [("90", 90), ("1:30", 90), ("1:01:30", 3690), ("90:00", 5400)],
)
def test_timecode_grammar_parses_to_whole_seconds(viewer, tmp_path, timecode, seconds):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    create(viewer, title="a note", timecode=timecode)

    assert only(vault)["timecode"] == seconds


# `timecode` Parsing Rules: "Leading zeros | Allowed".
@pytest.mark.parametrize("timecode,seconds", [("007", 7), ("0:07", 7), ("01:02:03", 3723)])
def test_leading_zeros_are_accepted(viewer, tmp_path, timecode, seconds):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    create(viewer, title="a note", timecode=timecode)

    assert only(vault)["timecode"] == seconds


# `timecode` Parsing Rules: "Conventional clock bounds | Not required; `"90:00"`
# is valid in `MM:SS` form".
def test_out_of_clock_components_are_valid(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = create(viewer, title="a note", timecode="90:00")

    assert response.status in REDIRECTS
    assert only(vault)["timecode"] == 5400


# `timecode` Parsing Rules: "Component type | Non-negative integer" and
# "Invalid pattern | Return error"; Error Handling: "Invalid `timecode` format |
# HTTP `400` with format error message".
@pytest.mark.parametrize(
    "timecode",
    ["", "abc", "-5", "1.5", "90s", " 90", "1:", ":30", "1:2:3:4", "1: 30", "1:-3", "90::00"],
)
def test_invalid_timecode_patterns_are_refused(viewer, tmp_path, timecode):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = create(viewer, title="a note", timecode=timecode)

    assert response.status == 400
    assert "timecode" in response.body
    assert "format" in response.body
    assert stored(vault) == []


# `timecode` Parsing Rules: "Create-success redirect value | Integer whole
# seconds".
def test_create_redirect_carries_integer_seconds(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = create(viewer, title="a note", timecode="01:02:03")

    assert response.location == f"{ENTRY}?timecode=3723"


# `timecode` Parsing Rules: "Entry detail page effect | Seek playback to
# `timecode` query value".
def test_detail_page_seeks_playback_to_the_timecode_query(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_media(vault, "e1.mp4")

    response = viewer.get(f"{ENTRY}?timecode=90")

    assert response.status == 200
    assert "/vault/demo/media/e1.mp4#t=90" in response.body
    assert "90" in response.body


# `timecode` Parsing Rules: "Entry detail page effect" — a page asked for no
# timecode starts its media at the beginning.
def test_detail_page_without_a_timecode_query_does_not_seek(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    place_media(vault, "e1.mp4")

    response = viewer.get(ENTRY)

    assert "#t=" not in response.body


# `annotations` Storage: "`id` | string | Unique within entry".
def test_annotation_ids_are_unique_strings_within_the_entry(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    create(viewer, title="first", timecode="10")
    create(viewer, title="second", timecode="20")
    create(viewer, title="third", timecode="30")

    ids = [note["id"] for note in stored(vault)]
    assert all(isinstance(value, str) for value in ids)
    assert len(set(ids)) == 3


# `annotations` Storage: "`timecode` | integer | Whole seconds".
def test_stored_timecode_is_an_integer(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    create(viewer, title="a note", timecode="1:30")

    assert only(vault)["timecode"] == 90
    assert isinstance(only(vault)["timecode"], int)


# `annotations` Storage: "`title` | string | Stored as provided".
def test_title_is_stored_as_provided(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    title = '  <b>Act & "one"</b>  '

    create(viewer, title=title, timecode="10")

    assert only(vault)["title"] == title


# `annotations` Storage: "`body` | string or `null` | Stored as provided or
# defaulted to `null`".
def test_body_is_stored_as_provided_or_null(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    create(viewer, title="with", timecode="10", body="text")
    create(viewer, title="without", timecode="20")

    assert [note["body"] for note in stored(vault)] == ["text", None]


# `annotations` Storage Location: "Catalog location | Entry object key
# `annotations`" and "Container type | Ordered list".
def test_annotations_live_in_a_list_under_the_entry_key(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    create(viewer, title="a note", timecode="10")

    entry = entry_by_id(read_catalog(vault), "episodes", "e1")
    assert isinstance(entry["annotations"], list)
    assert set(entry["annotations"][0]) == {"id", "timecode", "title", "body"}


# `annotations` Storage Location: "List order | Creation order"; Determinism:
# "Annotation list order | Same order as stored in `catalog.json`".
def test_annotations_are_stored_in_creation_order(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    create(viewer, title="third", timecode="3:00")
    create(viewer, title="first", timecode="1:00")
    create(viewer, title="second", timecode="2:00")

    assert [note["title"] for note in stored(vault)] == ["third", "first", "second"]


# `annotations` Storage Location: "Save behavior | `catalog.bak` written before
# persisting annotation changes".
def test_a_backup_holds_the_catalog_from_before_the_annotation(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    create(viewer, title="a note", timecode="10")

    backup = entry_by_id(read_backup(vault), "episodes", "e1")
    assert backup["annotations"] == []


# `annotations` Storage Location: "Save behavior" — each later mutation backs up
# the catalog it is about to replace.
def test_each_mutation_backs_up_the_catalog_it_replaces(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    create(viewer, title="a note", timecode="10")
    annotation_id = only(vault)["id"]

    update(viewer, id=annotation_id, title="renamed")

    assert entry_by_id(read_backup(vault), "episodes", "e1")["annotations"][0]["title"] == "a note"

    remove(viewer, id=annotation_id)

    assert len(entry_by_id(read_backup(vault), "episodes", "e1")["annotations"]) == 1


# `annotations` Storage Location: "Read-after-write behavior | Later `GET` to
# same entry detail page reflects create ... by visibly rendering stored
# annotations, each `timecode` as raw seconds".
def test_a_later_get_renders_the_created_annotation_in_raw_seconds(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])

    create(viewer, title="the chorus", timecode="1:30", body="from here")

    page = viewer.get(ENTRY).body
    assert "the chorus" in page
    assert "from here" in page
    assert ">90<" in page
    assert "1:30" not in page


# `annotations` Storage Location: "Read-after-write behavior | ... reflects
# ... update ...".
def test_a_later_get_reflects_an_update(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    create(viewer, title="before", timecode="10")

    update(viewer, id=only(vault)["id"], title="after")

    page = viewer.get(ENTRY).body
    assert "after" in page
    assert "before" not in page


# `annotations` Storage Location: "Read-after-write behavior | ... reflects
# ... delete result".
def test_a_later_get_reflects_a_delete(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    create(viewer, title="doomed", timecode="10")

    remove(viewer, id=only(vault)["id"])

    assert "doomed" not in viewer.get(ENTRY).body


# Determinism: "Annotation list order | Same order as stored in `catalog.json`"
# — the rendered page keeps the stored order.
def test_the_detail_page_renders_annotations_in_stored_order(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])
    for title, timecode in [("gamma", "3:00"), ("alpha", "1:00"), ("beta", "2:00")]:
        create(viewer, title=title, timecode=timecode)

    page = viewer.get(ENTRY).body
    assert page.index("gamma") < page.index("alpha") < page.index("beta")


# Error Handling: "Missing `title` on create | HTTP `400` with message naming
# missing field".
def test_create_without_a_title_is_refused(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = create(viewer, timecode="90")

    assert response.status == 400
    assert "title" in response.body
    assert stored(vault) == []


# Error Handling: "Missing `timecode` on create | HTTP `400` with message naming
# missing field".
def test_create_without_a_timecode_is_refused(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = create(viewer, title="a note")

    assert response.status == 400
    assert "timecode" in response.body
    assert stored(vault) == []


# Error Handling: "Missing `id` on update | HTTP `400` with message naming
# missing field".
def test_update_without_an_id_is_refused(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    create(viewer, title="a note", timecode="10")

    response = update(viewer, title="renamed")

    assert response.status == 400
    assert "id" in response.body
    assert only(vault)["title"] == "a note"


# Error Handling: "Missing `id` on delete | HTTP `400` with message naming
# missing field".
def test_delete_without_an_id_is_refused(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    create(viewer, title="a note", timecode="10")

    response = remove(viewer)

    assert response.status == 400
    assert "id" in response.body
    assert len(stored(vault)) == 1


# Error Handling: "Non-existent annotation `id` on update | HTTP `404`".
def test_update_of_an_unknown_annotation_is_not_found(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    create(viewer, title="a note", timecode="10")

    response = update(viewer, id="no-such-annotation", title="renamed")

    assert response.status == 404
    assert only(vault)["title"] == "a note"


# Error Handling: "Non-existent annotation `id` on delete | HTTP `404`".
def test_delete_of_an_unknown_annotation_is_not_found(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])
    create(viewer, title="a note", timecode="10")

    response = remove(viewer, id="no-such-annotation")

    assert response.status == 404
    assert len(stored(vault)) == 1


# Error Handling: "Malformed JSON body | HTTP `400`".
@pytest.mark.parametrize("body", ["", "{", "not json", '{"title": "a note",}', "[]"])
def test_a_malformed_json_body_is_refused(viewer, tmp_path, body):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = viewer.send_json("POST", ENTRY, body=body)

    assert response.status == 400
    assert stored(vault) == []


# Error Handling: "Any error response | Well-formed HTTP response; no raw
# traceback or stack trace".
@pytest.mark.parametrize(
    "method,fields",
    [
        ("POST", {"timecode": "10"}),
        ("POST", {"title": "a note", "timecode": "nope"}),
        ("PATCH", {"title": "renamed"}),
        ("PATCH", {"id": "missing", "title": "renamed"}),
        ("DELETE", {}),
        ("DELETE", {"id": "missing"}),
    ],
)
def test_error_responses_are_well_formed_and_carry_no_traceback(viewer, tmp_path, method, fields):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = viewer.send_json(method, ENTRY, fields)

    assert response.status in (400, 404)
    assert "text/html" in response.headers["Content-Type"]
    assert response.headers["Content-Length"] == str(len(response.body.encode("utf-8")))
    assert "Traceback" not in response.body
    assert "mvaultlib" not in response.body


# Annotation Methods: the methods address one entry, so a mutation aimed at an
# id the category does not hold reaches no entry.
def test_a_mutation_on_an_unknown_entry_is_not_found(viewer, tmp_path):
    v3_vault(tmp_path, episodes=[v3_entry("e1")])

    response = create(viewer, path="/catalog/demo/episodes/nope", title="a note", timecode="10")

    assert response.status == 404
    assert not (tmp_path / "demo" / "catalog.bak").exists()


# Annotations require version 3 catalog format: a v3 entry written without the
# field gains it rather than being rejected.
def test_a_v3_entry_without_the_field_gains_annotations(viewer, tmp_path):
    entry = v3_entry("e1")
    del entry["annotations"]
    vault = v3_vault(tmp_path, episodes=[entry])

    create(viewer, title="a note", timecode="10")

    assert only(vault)["title"] == "a note"


# Annotation Auto-Migration: "v3 | Apply annotation directly" — a v3 annotation
# leaves every other part of the catalog as it was.
def test_a_v3_annotation_changes_nothing_but_the_annotations(viewer, tmp_path):
    vault = v3_vault(tmp_path, episodes=[v3_entry("e1")], clips=[v3_entry("c1")])
    before = read_catalog(vault)

    create(viewer, title="a note", timecode="10")

    after = read_catalog(vault)
    assert after["version"] == 3
    assert after["clips"] == before["clips"]
    assert entry_by_id(after, "episodes", "e1")["title"] == {V2_KEY: "title-e1"}
