"""Spec section: Annotation Error Handling and Determinism."""

from __future__ import annotations

import pytest

REDIRECTS = (301, 302, 303, 307, 308)


def one_episode(catalogs, make_vault, entry_id="e1"):
    return make_vault(catalogs.catalog(episodes=[catalogs.entry(entry_id)]))


def existing_annotation(client, annotate, workdir, **fields):
    annotate.make(client, "vault", "episodes", "e1", **fields)
    return annotate.only(workdir, "vault", "e1")["id"]


def assert_clean_error(response, status):
    """| Any error response | Well-formed HTTP response; no raw traceback or
    stack trace |
    """
    assert response.status == status, f"{response.status}: {response.body[:400]}"
    assert response.body.strip(), "error response has an empty body"
    assert "Traceback (most recent call last)" not in response.body
    assert "File \"" not in response.body
    assert "mvault.py" not in response.body
    return response


# ---------------------------------------------------------------------------
# | Missing `title` on create | HTTP `400` with message naming missing field |
# ---------------------------------------------------------------------------

# Spec: | Missing `title` on create | HTTP `400` with message naming missing
#   field |
def test_missing_title_is_400(serve, make_vault, catalogs, annotate):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1",
                               {"timecode": "90"})
    assert_clean_error(response, 400)


# Spec: | Missing `title` on create | ... with message naming missing field |
def test_missing_title_message_names_the_field(serve, make_vault, catalogs,
                                               annotate):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1",
                               {"timecode": "90"})
    assert "title" in annotate.text(response.body).lower(), response.body


# Spec: | Missing `title` on create | ... |
# Context: a rejected create adds nothing.
def test_missing_title_stores_nothing(serve, make_vault, catalogs, annotate,
                                      workdir):
    one_episode(catalogs, make_vault)
    annotate.create(serve().client, "vault", "episodes", "e1",
                    {"timecode": "90"})
    assert annotate.stored(workdir, "vault", "e1") == []


# Spec: | Missing `timecode` on create | HTTP `400` with message naming
#   missing field |
def test_missing_timecode_is_400(serve, make_vault, catalogs, annotate):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1",
                               {"title": "Note"})
    assert_clean_error(response, 400)


# Spec: | Missing `timecode` on create | ... naming missing field |
def test_missing_timecode_message_names_the_field(serve, make_vault, catalogs,
                                                  annotate):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1",
                               {"title": "Note"})
    assert "timecode" in annotate.text(response.body).lower(), response.body


# Spec: | Missing `title` ... | | Missing `timecode` ... |
# Context: an empty create body is missing both required fields.
def test_empty_object_body_on_create(serve, make_vault, catalogs, annotate):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1", {})
    assert_clean_error(response, 400)


# Spec: | `title` | string | yes | none |
# Context: T74 - a present-but-non-string title is not the string the table
# requires.
@pytest.mark.parametrize("value", [None, 5, ["Note"], {"t": "Note"}])
def test_non_string_title_is_400(serve, make_vault, catalogs, annotate, value):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1",
                               {"title": value, "timecode": "90"})
    assert_clean_error(response, 400)


# Spec: | `body` | string | no | `null` |
# Context: a present-but-non-string body is not storable as "string or null".
def test_non_string_body_is_400(serve, make_vault, catalogs, annotate):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1",
                               {"title": "Note", "timecode": "90", "body": 7})
    assert_clean_error(response, 400)


# ---------------------------------------------------------------------------
# | Invalid `timecode` format | HTTP `400` with format error message |
# ---------------------------------------------------------------------------

# Spec: | Invalid `timecode` format | HTTP `400` with format error message |
def test_invalid_timecode_is_400(serve, make_vault, catalogs, annotate):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1",
                               {"title": "Note", "timecode": "1:2:3:4"})
    assert_clean_error(response, 400)


# Spec: | Invalid `timecode` format | HTTP `400` with format error message |
def test_invalid_timecode_message_mentions_the_format(serve, make_vault,
                                                      catalogs, annotate):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1",
                               {"title": "Note", "timecode": "later"})
    text = annotate.text(response.body).lower()
    assert "timecode" in text, response.body


# ---------------------------------------------------------------------------
# | Missing `id` on update | HTTP `400` with message naming missing field |
# | Missing `id` on delete | HTTP `400` with message naming missing field |
# ---------------------------------------------------------------------------

# Spec: | Missing `id` on update | HTTP `400` with message naming missing field |
def test_missing_id_on_update_is_400(serve, make_vault, catalogs, annotate,
                                     workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    existing_annotation(client, annotate, workdir)
    response = annotate.update(client, "vault", "episodes", "e1",
                               {"title": "New"})
    assert_clean_error(response, 400)
    assert "id" in annotate.text(response.body).lower()


# Spec: | Missing `id` on delete | HTTP `400` with message naming missing field |
def test_missing_id_on_delete_is_400(serve, make_vault, catalogs, annotate,
                                     workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    existing_annotation(client, annotate, workdir)
    response = annotate.remove(client, "vault", "episodes", "e1", {})
    assert_clean_error(response, 400)
    assert "id" in annotate.text(response.body).lower()


# Spec: | Missing `id` on update | ... |
# Context: the rejected update leaves the stored annotation alone.
def test_missing_id_on_update_changes_nothing(serve, make_vault, catalogs,
                                              annotate, workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    existing_annotation(client, annotate, workdir, title="Kept")
    annotate.update(client, "vault", "episodes", "e1", {"title": "New"})
    assert annotate.only(workdir, "vault", "e1")["title"] == "Kept"


# Spec: | `id` | string | yes | Annotation identifier inside current entry |
# Context: a non-string `id` is not the identifier the table requires.
@pytest.mark.parametrize("value", [None, 1, ["a1"]])
def test_non_string_id_on_update(serve, make_vault, catalogs, annotate,
                                 workdir, value):
    one_episode(catalogs, make_vault)
    client = serve().client
    existing_annotation(client, annotate, workdir)
    response = annotate.update(client, "vault", "episodes", "e1",
                               {"id": value, "title": "New"})
    assert response.status in (400, 404), response.status
    assert_clean_error(response, response.status)


# ---------------------------------------------------------------------------
# | Non-existent annotation `id` on update | HTTP `404` |
# | Non-existent annotation `id` on delete | HTTP `404` |
# ---------------------------------------------------------------------------

# Spec: | Non-existent annotation `id` on update | HTTP `404` |
def test_unknown_id_on_update_is_404(serve, make_vault, catalogs, annotate,
                                     workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    existing_annotation(client, annotate, workdir)
    response = annotate.update(client, "vault", "episodes", "e1",
                               {"id": "no-such-annotation", "title": "New"})
    assert_clean_error(response, 404)


# Spec: | Non-existent annotation `id` on delete | HTTP `404` |
def test_unknown_id_on_delete_is_404(serve, make_vault, catalogs, annotate,
                                     workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    existing_annotation(client, annotate, workdir)
    response = annotate.remove(client, "vault", "episodes", "e1",
                               {"id": "no-such-annotation"})
    assert_clean_error(response, 404)


# Spec: | Non-existent annotation `id` on delete | HTTP `404` |
# Context: an entry with no annotations at all has no id to match.
def test_delete_on_an_entry_without_annotations_is_404(serve, make_vault,
                                                       catalogs, annotate):
    one_episode(catalogs, make_vault)
    response = annotate.remove(serve().client, "vault", "episodes", "e1",
                               {"id": "a1"})
    assert_clean_error(response, 404)


# Spec: | Non-existent annotation `id` on update | HTTP `404` |
# Context: the rejected update changes nothing on disk.
def test_unknown_id_changes_nothing(serve, make_vault, catalogs, annotate,
                                    workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    existing_annotation(client, annotate, workdir, title="Kept")
    before = annotate.catalog_text(workdir)
    annotate.update(client, "vault", "episodes", "e1",
                    {"id": "nope", "title": "New"})
    assert annotate.catalog_text(workdir) == before


# ---------------------------------------------------------------------------
# | Malformed JSON body | HTTP `400` |
# ---------------------------------------------------------------------------

# Spec: | Malformed JSON body | HTTP `400` |
@pytest.mark.parametrize("raw", [
    "{",
    "not json at all",
    '{"title": "Note", "timecode": "90"',
    "{'title': 'Note'}",
    "",
])
def test_malformed_json_is_400(serve, make_vault, catalogs, annotate, raw):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1",
                               raw=raw)
    assert_clean_error(response, 400)


# Spec: | Malformed JSON body | HTTP `400` |
# Context: valid JSON that is not an object cannot carry the named fields.
@pytest.mark.parametrize("raw", ["[]", '"title"', "42", "null", "true"])
def test_non_object_json_is_400(serve, make_vault, catalogs, annotate, raw):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1",
                               raw=raw)
    assert_clean_error(response, 400)


# Spec: | Malformed JSON body | HTTP `400` |
# Context: a request with no body at all carries no JSON.
def test_no_body_is_400(serve, make_vault, catalogs, annotate):
    one_episode(catalogs, make_vault)
    response = annotate.send(serve().client, "POST", "vault", "episodes", "e1")
    assert_clean_error(response, 400)


# Spec: | Malformed JSON body | HTTP `400` | (update and delete legs)
@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_malformed_json_on_update_and_delete(serve, make_vault, catalogs,
                                             annotate, method):
    one_episode(catalogs, make_vault)
    response = annotate.send(serve().client, method, "vault", "episodes", "e1",
                             raw="{oops")
    assert_clean_error(response, 400)


# Spec: | Malformed JSON body | HTTP `400` |
# Context: T81 - a form-encoded body is not JSON, whatever its content type.
def test_form_encoded_body_is_400(serve, make_vault, catalogs, annotate):
    one_episode(catalogs, make_vault)
    response = annotate.send(
        serve().client, "POST", "vault", "episodes", "e1",
        raw="title=Note&timecode=90",
        content_type="application/x-www-form-urlencoded")
    assert_clean_error(response, 400)


# Spec: | `POST` | Create annotation | JSON with ... |
# Context: T81 - a JSON body is accepted whatever content type it declares.
def test_json_body_without_json_content_type(serve, make_vault, catalogs,
                                             annotate, workdir):
    one_episode(catalogs, make_vault)
    response = annotate.send(serve().client, "POST", "vault", "episodes", "e1",
                             raw='{"title": "Note", "timecode": "90"}',
                             content_type="text/plain")
    assert response.status in REDIRECTS, response.body[:400]
    assert annotate.only(workdir, "vault", "e1")["title"] == "Note"


# ---------------------------------------------------------------------------
# | Any error response | Well-formed HTTP response; no raw traceback or stack
#   trace |
# ---------------------------------------------------------------------------

# Spec: | Any error response | Well-formed HTTP response ... |
# Context: T68 - the error body is the viewer's HTML error page, so it is a
# complete document with a declared content type.
def test_error_response_is_well_formed(serve, make_vault, catalogs, annotate):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1",
                               {"timecode": "90"})
    assert response.headers.get("Content-Type"), "no Content-Type"
    assert response.headers.get("Content-Length") is not None


# Spec: | Any error response | ... no raw traceback or stack trace |
# Context: the connection stays usable for the next request.
def test_server_survives_a_bad_request(serve, make_vault, catalogs, annotate,
                                       detail):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.create(client, "vault", "episodes", "e1", raw="{")
    assert client.get(detail.path("vault", "episodes", "e1")).status == 200


# Spec: | Non-existent annotation `id` on update | HTTP `404` |
# Context: T71 - an entry that is not in the named category is a `404` too.
def test_unknown_entry_is_404(serve, make_vault, catalogs, annotate):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "ghost",
                               {"title": "Note", "timecode": "90"})
    assert_clean_error(response, 404)


# Spec: | Category scope | Lookup occurs only inside named category |
# Context: T71 - the entry exists, but not in the category the URL named.
def test_wrong_category_is_404(serve, make_vault, catalogs, annotate, workdir):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "clips", "e1",
                               {"title": "Note", "timecode": "90"})
    assert_clean_error(response, 404)
    assert annotate.stored(workdir, "vault", "e1") == []


# Spec: | Entry lookup | Find entry by `id` ... |
# Context: T71 - a category name that is not valid for the vault's version.
def test_unknown_category_is_404(serve, make_vault, catalogs, annotate):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "nonsense", "e1",
                               {"title": "Note", "timecode": "90"})
    assert_clean_error(response, 404)


# Spec: | Entry lookup | Find entry by `id` ... |
# Context: T71 - an annotation aimed at a vault that is not there is a `404`,
# not the landing-page redirect a browser `GET` would get.
def test_unknown_vault_is_404(serve, make_vault, catalogs, annotate):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "ghost", "episodes", "e1",
                               {"title": "Note", "timecode": "90"})
    assert_clean_error(response, 404)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

# Spec: | Annotation list order | Same order as stored in `catalog.json` |
# Context: repeating the same fixture twice produces the same stored list.
def test_repeated_runs_store_the_same_list(serve, make_vault, catalogs,
                                           annotate, workdir, helpers):
    one_episode(catalogs, make_vault)
    client = serve().client
    for title in ("a", "b", "c"):
        annotate.make(client, "vault", "episodes", "e1", title=title,
                      timecode="30")
    first = annotate.stored(workdir, "vault", "e1")

    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]), name="other")
    for title in ("a", "b", "c"):
        annotate.make(client, "other", "episodes", "e1", title=title,
                      timecode="30")
    second = annotate.stored(workdir, "other", "e1")
    assert first == second


# Spec: | Post auto-migration category | v1 entries always migrate to
#   `episodes` |
def test_v1_entries_always_migrate_to_episodes(serve, make_vault, legacy,
                                               annotate, workdir, helpers):
    make_vault(legacy.v1_catalog([legacy.v1_entry("e1"),
                                  legacy.v1_entry("e2")]))
    annotate.create(serve().client, "vault", "entries", "e1",
                    {"title": "Note", "timecode": "90"})
    catalog = helpers.read_catalog(workdir)
    assert [entry["id"] for entry in catalog["episodes"]] == ["e1", "e2"]
    assert catalog["streams"] == [] and catalog["clips"] == []
