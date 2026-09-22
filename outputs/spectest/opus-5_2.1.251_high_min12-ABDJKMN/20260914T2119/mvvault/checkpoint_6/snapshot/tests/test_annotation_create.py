"""Spec: the `POST` annotation method, its field table and the stored shape."""
import pytest

from annotation_helpers import (assert_clean, create, mutate, only_annotation,
                                redirect_path, redirect_timecode,
                                stored_annotations)
from digest_helpers import v3, v3_entry


@pytest.fixture
def vault3(make_vault):
    """A v3 vault holding one episode `e1` with no annotations yet."""
    def _make(entries=None, **kwargs):
        return make_vault(v3(episodes=entries or [v3_entry(id="e1")]),
                          **kwargs)
    return _make


# --------------------------------------------------------------------------
# Method table
# --------------------------------------------------------------------------
# Spec: "Entry detail pages support user-managed annotations." -- the detail
# route itself accepts the annotation methods.
def test_detail_route_accepts_post(serve, vault3):
    vault3()
    response = create(serve(), title="Note", timecode="90")
    assert response.status not in (404, 405, 501), response
    assert_clean(response)


# Spec: "| `POST` | Create annotation | JSON with `title`, `timecode`,
# optional `body` | Redirect to entry detail page with `?timecode=<seconds>` |"
def test_post_redirects_to_the_entry_detail_page(serve, vault3):
    vault3()
    response = create(serve(), title="Note", timecode="90")
    assert response.is_redirect, response
    assert redirect_path(response) == "/catalog/vault/episodes/e1"


# Spec: "| `POST` | ... | Redirect to entry detail page with
# `?timecode=<seconds>` |"
def test_post_redirect_carries_the_timecode_query(serve, vault3):
    vault3()
    response = create(serve(), title="Note", timecode="1:30")
    assert redirect_timecode(response) == "90"


# Spec: "| `POST` | Create annotation | ... |" -- the annotation exists after
# the request.
def test_post_creates_an_annotation(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="90")
    assert len(stored_annotations(tmp_path)) == 1


# Spec: "| Redirect status | HTTP `302` or `303` |" (viewer redirect rule)
def test_post_redirect_status(serve, vault3):
    vault3()
    assert create(serve(), title="Note", timecode="90").status in (302, 303)


# Spec: "| `POST` | ... | Redirect to entry detail page ... |" -- the redirect
# leads to a real page rather than an error.
def test_post_redirect_is_followable(serve, vault3):
    vault3([v3_entry(id="e1", title="Ep One")])
    server = serve()
    response = create(server, title="Note", timecode="90")
    followed = server.request("GET", response.location)
    assert followed.status == 200, followed


# Spec: "| `POST` | ... | Redirect to entry detail page ... |" -- the page the
# redirect names shows the new annotation.
def test_post_redirect_target_renders(serve, vault3):
    vault3([v3_entry(id="e1", title="Ep One")])
    server = serve()
    create(server, title="Marker", timecode="90")
    page = server.get("/catalog/vault/episodes/e1?timecode=90")
    assert page.status == 200, page
    assert "Marker" in page.body


# --------------------------------------------------------------------------
# `POST` Annotation Fields
# --------------------------------------------------------------------------
# Spec: "| `title` | string | yes | none |"
def test_title_is_stored(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Chapter one", timecode="90")
    assert only_annotation(tmp_path)["title"] == "Chapter one"


# Spec: "| `timecode` | string | yes | none |"
def test_timecode_is_stored(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="1:30")
    assert only_annotation(tmp_path)["timecode"] == 90


# Spec: "| `body` | string | no | `null` |" -- provided body is stored.
def test_body_is_stored_when_provided(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="90", body="Long form text")
    assert only_annotation(tmp_path)["body"] == "Long form text"


# Spec: "| `body` | string | no | `null` |" -- an omitted body defaults to null.
def test_body_defaults_to_null(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="90")
    assert only_annotation(tmp_path)["body"] is None


# Spec: "| `body` | string | no | `null` |" -- the key exists even when the
# body was omitted (stored "as provided or defaulted to `null`").
def test_body_key_is_present_when_defaulted(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="90")
    assert "body" in only_annotation(tmp_path)


# --------------------------------------------------------------------------
# `annotations` Storage
# --------------------------------------------------------------------------
# Spec: "| `id` | string | Unique within entry |"
def test_stored_annotation_has_a_string_id(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="90")
    assert isinstance(only_annotation(tmp_path)["id"], str)
    assert only_annotation(tmp_path)["id"] != ""


# Spec: "| `id` | string | Unique within entry |"
def test_ids_are_unique_within_an_entry(serve, tmp_path, vault3):
    vault3()
    server = serve()
    for index in range(4):
        create(server, title="Note %d" % index, timecode="90")
    ids = [item["id"] for item in stored_annotations(tmp_path)]
    assert len(set(ids)) == len(ids) == 4


# Spec: "| `timecode` | integer | Whole seconds |"
def test_stored_timecode_is_an_integer(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="1:01:30")
    stored = only_annotation(tmp_path)["timecode"]
    assert isinstance(stored, int) and not isinstance(stored, bool)
    assert stored == 3690


# Spec: "| `title` | string | Stored as provided |" -- no trimming, casing or
# other rewriting of the submitted text.
def test_title_is_stored_verbatim(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="  Spaced & <odd>  ", timecode="90")
    assert only_annotation(tmp_path)["title"] == "  Spaced & <odd>  "


# Spec: "| `body` | string or `null` | Stored as provided or defaulted to
# `null` |" -- verbatim as well.
def test_body_is_stored_verbatim(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="90", body="  raw\ntext  ")
    assert only_annotation(tmp_path)["body"] == "  raw\ntext  "


# Spec: "| Container type | Ordered list |"
def test_annotations_is_a_list(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="90")
    assert isinstance(stored_annotations(tmp_path), list)


# Spec: "| List order | Creation order |"
def test_annotations_are_kept_in_creation_order(serve, tmp_path, vault3):
    vault3()
    server = serve()
    for title in ("first", "second", "third"):
        create(server, title=title, timecode="5")
    assert [item["title"] for item in stored_annotations(tmp_path)] == [
        "first", "second", "third"]


# Spec: "| Catalog location | Entry object key `annotations` |" -- the
# annotation lands on the entry that was addressed, not on a sibling.
def test_annotation_lands_on_the_addressed_entry(serve, tmp_path, vault3):
    vault3([v3_entry(id="e1"), v3_entry(id="e2")])
    create(serve(), title="Note", timecode="90", entry_id="e2")
    assert stored_annotations(tmp_path, entry_id="e1") == []
    assert len(stored_annotations(tmp_path, entry_id="e2")) == 1


# Spec: "| Catalog location | Entry object key `annotations` |" -- and not on
# a same-id entry in another category.
def test_annotation_is_scoped_to_the_addressed_category(serve, tmp_path,
                                                        make_vault):
    make_vault(v3(episodes=[v3_entry(id="dup")], clips=[v3_entry(id="dup")]))
    create(serve(), title="Note", timecode="90", category="clips",
           entry_id="dup")
    assert stored_annotations(tmp_path, category="episodes",
                              entry_id="dup") == []
    assert len(stored_annotations(tmp_path, category="clips",
                                  entry_id="dup")) == 1


# Spec: "| Catalog location | Entry object key `annotations` |" -- an entry
# that has no `annotations` key yet gains one.
def test_entry_without_annotations_key_gains_one(serve, tmp_path, make_vault):
    entry = v3_entry(id="e1")
    entry.pop("annotations")
    make_vault(v3(episodes=[entry]))
    response = create(serve(), title="Note", timecode="90")
    assert response.is_redirect, response
    assert len(stored_annotations(tmp_path)) == 1


# Spec: "| `POST` | Create annotation | JSON with ... |" -- creating twice
# appends rather than replacing.
def test_second_create_appends(serve, tmp_path, vault3):
    vault3()
    server = serve()
    create(server, title="one", timecode="1")
    create(server, title="two", timecode="2")
    assert len(stored_annotations(tmp_path)) == 2


# Spec: "Entry detail pages support user-managed annotations." -- other
# entries' catalog data survives the write untouched.
def test_create_leaves_the_rest_of_the_catalog_intact(serve, tmp_path,
                                                      make_vault):
    original = v3(episodes=[v3_entry(id="e1")], clips=[v3_entry(id="c1")])
    make_vault(original)
    create(serve(), title="Note", timecode="90")
    from annotation_helpers import stored_catalog
    after = stored_catalog(tmp_path)
    assert after["version"] == 3
    assert after["source"] == original["source"]
    assert after["clips"] == original["clips"]


# Spec: "| `POST` | ... JSON with `title`, `timecode`, optional `body` |" --
# the request body is read as JSON, not as a form encoding.
def test_body_is_read_as_json(serve, tmp_path, vault3):
    vault3()
    response = mutate(serve(), "POST",
                      raw='{"title": "json note", "timecode": "42"}')
    assert response.is_redirect, response
    assert only_annotation(tmp_path)["title"] == "json note"


# Spec: "| `title` | string | yes | none |" -- "required" is about the field
# being present; an empty string is a provided value (see AMBIGUITIES T65).
def test_empty_title_is_a_provided_value(serve, tmp_path, vault3):
    vault3()
    response = create(serve(), title="", timecode="90")
    assert response.is_redirect, response
    assert only_annotation(tmp_path)["title"] == ""


# Spec: "| `body` | string | no | `null` |" -- an empty body string is stored
# as an empty string rather than defaulted away.
def test_empty_body_is_stored_as_empty_string(serve, tmp_path, vault3):
    vault3()
    create(serve(), title="Note", timecode="90", body="")
    assert only_annotation(tmp_path)["body"] == ""


# Spec: "| `id` | string | Unique within entry |" -- the create request does
# not get to choose the id (see AMBIGUITIES T73).
def test_client_supplied_id_is_not_trusted(serve, tmp_path, vault3):
    vault3()
    server = serve()
    mutate(server, "POST", {"title": "one", "timecode": "1", "id": "fixed"})
    mutate(server, "POST", {"title": "two", "timecode": "2", "id": "fixed"})
    ids = [item["id"] for item in stored_annotations(tmp_path)]
    assert len(set(ids)) == 2
