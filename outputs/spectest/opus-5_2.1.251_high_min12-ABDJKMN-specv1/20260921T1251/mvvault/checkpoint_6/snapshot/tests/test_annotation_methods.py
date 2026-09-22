"""Spec section: `/catalog/<name>/<category>/<id>` Annotation Methods."""

from __future__ import annotations

import urllib.parse


def one_episode(catalogs, make_vault, entry_id="e1"):
    make_vault(catalogs.catalog(episodes=[catalogs.entry(entry_id)]))


# ---------------------------------------------------------------------------
# Spec: Entry detail pages support user-managed annotations.
# ---------------------------------------------------------------------------

# Spec: "Entry detail pages support user-managed annotations."
# Context: the annotation methods live on the entry detail route, so the route
# must answer them at all rather than treating them as unknown pages.
def test_entry_detail_route_accepts_annotation_methods(serve, make_vault,
                                                       catalogs, annotate):
    one_episode(catalogs, make_vault)
    client = serve().client
    response = annotate.create(client, "vault", "episodes", "e1",
                               {"title": "Intro", "timecode": "90"})
    assert response.status != 404, response.body[:400]
    assert response.status in annotate.REDIRECTS, response.status


# Spec: "Annotations require version 3 catalog format."
# Context: a v3 vault needs no migration, so its version stays 3.
def test_annotation_on_v3_leaves_version_3(serve, make_vault, catalogs,
                                           annotate, workdir, helpers):
    one_episode(catalogs, make_vault)
    annotate.make(serve().client, "vault", "episodes", "e1")
    assert helpers.read_catalog(workdir)["version"] == 3


# ---------------------------------------------------------------------------
# | `POST` | Create annotation | JSON with `title`, `timecode`, optional `body`
#   | Redirect to entry detail page with `?timecode=<seconds>` |
# ---------------------------------------------------------------------------

# Spec: | `POST` | Create annotation | JSON with `title`, `timecode` ... |
def test_post_creates_an_annotation(serve, make_vault, catalogs, annotate,
                                    workdir):
    one_episode(catalogs, make_vault)
    annotate.create(serve().client, "vault", "episodes", "e1",
                    {"title": "Intro", "timecode": "90"})
    stored = annotate.only(workdir, "vault", "e1")
    assert stored["title"] == "Intro"


# Spec: | `POST` | ... | Success Result | Redirect to entry detail page ... |
def test_post_success_redirects(serve, make_vault, catalogs, annotate):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1",
                               {"title": "Intro", "timecode": "90"})
    assert response.status in annotate.REDIRECTS, response.status


# Spec: | `POST` | ... | Redirect to entry detail page with `?timecode=...` |
# Context: "entry detail page" is the route the request was made against.
def test_post_redirect_points_at_the_entry_detail_page(serve, make_vault,
                                                       catalogs, annotate):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1",
                               {"title": "Intro", "timecode": "90"})
    assert annotate.target(response) == "/catalog/vault/episodes/e1"


# Spec: | `POST` | ... | Redirect ... with `?timecode=<seconds>` |
def test_post_redirect_carries_the_timecode_query(serve, make_vault, catalogs,
                                                  annotate):
    one_episode(catalogs, make_vault)
    response = annotate.create(serve().client, "vault", "episodes", "e1",
                               {"title": "Intro", "timecode": "1:30"})
    assert annotate.timecode(response) == "90"


# Spec: | `POST` | ... | Redirect to entry detail page ... |
# Context: following the redirect must land on a usable detail page.
def test_post_redirect_is_followable(serve, make_vault, catalogs, annotate):
    one_episode(catalogs, make_vault)
    client = serve().client
    response = annotate.create(client, "vault", "episodes", "e1",
                               {"title": "Intro", "timecode": "90"},
                               follow=True)
    assert response.status == 200, response.status
    assert "Intro" in annotate.text(response.body)


# Spec: | `POST` | Create annotation | ... optional `body` |
def test_post_accepts_an_optional_body(serve, make_vault, catalogs, annotate,
                                       workdir):
    one_episode(catalogs, make_vault)
    annotate.create(serve().client, "vault", "episodes", "e1",
                    {"title": "Intro", "timecode": "90", "body": "Long note"})
    assert annotate.only(workdir, "vault", "e1")["body"] == "Long note"


# ---------------------------------------------------------------------------
# | `PATCH` | Update annotation | JSON with `id` and at least one of `title` or
#   `body` | Redirect to entry detail page |
# ---------------------------------------------------------------------------

# Spec: | `PATCH` | Update annotation | JSON with `id` and ... `title` ... |
def test_patch_updates_the_title(serve, make_vault, catalogs, annotate,
                                 workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", title="Old")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    annotate.update(client, "vault", "episodes", "e1",
                    {"id": annotation_id, "title": "New"})
    assert annotate.only(workdir, "vault", "e1")["title"] == "New"


# Spec: | `PATCH` | Update annotation | JSON with `id` and ... `body` |
def test_patch_updates_the_body(serve, make_vault, catalogs, annotate,
                                workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", body="old text")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    annotate.update(client, "vault", "episodes", "e1",
                    {"id": annotation_id, "body": "new text"})
    assert annotate.only(workdir, "vault", "e1")["body"] == "new text"


# Spec: | `PATCH` | ... | Success Result | Redirect to entry detail page |
def test_patch_success_redirects_to_the_detail_page(serve, make_vault,
                                                    catalogs, annotate,
                                                    workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    response = annotate.update(client, "vault", "episodes", "e1",
                               {"id": annotation_id, "title": "New"})
    assert response.status in annotate.REDIRECTS, response.status
    assert annotate.target(response) == "/catalog/vault/episodes/e1"


# Spec: | `PATCH` | Update annotation | ... |
# Context: an update rewrites an existing annotation rather than appending.
def test_patch_does_not_add_an_annotation(serve, make_vault, catalogs,
                                          annotate, workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    annotate.update(client, "vault", "episodes", "e1",
                    {"id": annotation_id, "title": "New"})
    assert len(annotate.stored(workdir, "vault", "e1")) == 1


# ---------------------------------------------------------------------------
# | `DELETE` | Delete annotation | JSON with `id` | Redirect to entry detail
#   page |
# ---------------------------------------------------------------------------

# Spec: | `DELETE` | Delete annotation | JSON with `id` | ... |
def test_delete_removes_the_annotation(serve, make_vault, catalogs, annotate,
                                       workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    annotate.remove(client, "vault", "episodes", "e1", {"id": annotation_id})
    assert annotate.stored(workdir, "vault", "e1") == []


# Spec: | `DELETE` | ... | Success Result | Redirect to entry detail page |
def test_delete_success_redirects_to_the_detail_page(serve, make_vault,
                                                     catalogs, annotate,
                                                     workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    response = annotate.remove(client, "vault", "episodes", "e1",
                               {"id": annotation_id})
    assert response.status in annotate.REDIRECTS, response.status
    assert annotate.target(response) == "/catalog/vault/episodes/e1"


# Spec: | `DELETE` | Delete annotation | ... |
# Context: only the named annotation goes away.
def test_delete_keeps_the_other_annotations(serve, make_vault, catalogs,
                                            annotate, workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", title="first")
    annotate.make(client, "vault", "episodes", "e1", title="second")
    stored = annotate.stored(workdir, "vault", "e1")
    annotate.remove(client, "vault", "episodes", "e1", {"id": stored[0]["id"]})
    remaining = annotate.stored(workdir, "vault", "e1")
    assert [item["title"] for item in remaining] == ["second"]


# ---------------------------------------------------------------------------
# | `PATCH` Annotation Fields |
# ---------------------------------------------------------------------------

# Spec: | `id` | string | yes | Annotation identifier inside current entry |
# Context: the same id in a *different* entry is not this entry's annotation.
def test_patch_id_is_scoped_to_the_current_entry(serve, make_vault, catalogs,
                                                 annotate, workdir):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1"),
                                          catalogs.entry("e2")]))
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", title="on e1")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    response = annotate.update(client, "vault", "episodes", "e2",
                               {"id": annotation_id, "title": "moved"})
    assert response.status == 404, response.status
    assert annotate.only(workdir, "vault", "e1")["title"] == "on e1"


# Spec: | `title` | string | no | Replace existing title when present |
# Context: replacing the title leaves the rest of the annotation alone.
def test_patch_title_leaves_body_and_timecode(serve, make_vault, catalogs,
                                              annotate, workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", title="Old",
                  timecode="1:30", body="keep me")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    annotate.update(client, "vault", "episodes", "e1",
                    {"id": annotation_id, "title": "New"})
    stored = annotate.only(workdir, "vault", "e1")
    assert stored["body"] == "keep me"
    assert stored["timecode"] == 90


# Spec: | omitted fields | n/a | allowed | Leave stored value unchanged |
def test_patch_omitting_body_leaves_it_unchanged(serve, make_vault, catalogs,
                                                 annotate, workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", body="original")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    annotate.update(client, "vault", "episodes", "e1",
                    {"id": annotation_id, "title": "New"})
    assert annotate.only(workdir, "vault", "e1")["body"] == "original"


# Spec: | omitted fields | n/a | allowed | Leave stored value unchanged |
def test_patch_omitting_title_leaves_it_unchanged(serve, make_vault, catalogs,
                                                  annotate, workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", title="Original")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    annotate.update(client, "vault", "episodes", "e1",
                    {"id": annotation_id, "body": "added"})
    stored = annotate.only(workdir, "vault", "e1")
    assert stored["title"] == "Original"
    assert stored["body"] == "added"


# Spec: | `PATCH` | Update annotation | JSON with `id` and at least one of
#   `title` or `body` | ... |
# Context: T70 - both fields are marked Required `no` and the error table
# lists no "nothing to update" case, so a body carrying only `id` is a
# successful no-op.
def test_patch_with_only_id_is_a_no_op_success(serve, make_vault, catalogs,
                                               annotate, workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", title="Only",
                  body="unchanged")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    response = annotate.update(client, "vault", "episodes", "e1",
                               {"id": annotation_id})
    assert response.status in annotate.REDIRECTS, response.status
    stored = annotate.only(workdir, "vault", "e1")
    assert (stored["title"], stored["body"]) == ("Only", "unchanged")


# Spec: | `body` | string | no | Replace existing body when present |
# Context: T76 - `body` is allowed to hold `null` in storage, so an explicit
# `null` clears it.
def test_patch_body_null_clears_the_body(serve, make_vault, catalogs,
                                         annotate, workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", body="text")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    annotate.update(client, "vault", "episodes", "e1",
                    {"id": annotation_id, "body": None})
    assert annotate.only(workdir, "vault", "e1")["body"] is None


# Spec: | omitted fields | n/a | allowed | Leave stored value unchanged |
# Context: T77 - `timecode` is not a field of `PATCH`, so a stray one is
# ignored and the stored timecode is unchanged.
def test_patch_ignores_a_timecode_field(serve, make_vault, catalogs, annotate,
                                        workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", timecode="90")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    response = annotate.update(client, "vault", "episodes", "e1",
                               {"id": annotation_id, "title": "New",
                                "timecode": "5:00"})
    assert response.status in annotate.REDIRECTS, response.status
    assert annotate.only(workdir, "vault", "e1")["timecode"] == 90


# ---------------------------------------------------------------------------
# | `DELETE` Annotation Fields | | `id` | string | yes |
# ---------------------------------------------------------------------------

# Spec: | `id` | string | yes | (DELETE)
def test_delete_targets_the_named_annotation(serve, make_vault, catalogs,
                                             annotate, workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    for title in ("a", "b", "c"):
        annotate.make(client, "vault", "episodes", "e1", title=title)
    stored = annotate.stored(workdir, "vault", "e1")
    annotate.remove(client, "vault", "episodes", "e1", {"id": stored[1]["id"]})
    remaining = annotate.stored(workdir, "vault", "e1")
    assert [item["title"] for item in remaining] == ["a", "c"]


# ---------------------------------------------------------------------------
# T82: the annotation verbs belong to the entry detail path only.
# ---------------------------------------------------------------------------

# Spec: ## `/catalog/<name>/<category>/<id>` Annotation Methods
# Context: T82 - `PATCH` to a category listing is not an annotation route.
def test_patch_on_the_category_listing_is_not_found(serve, make_vault,
                                                    catalogs):
    one_episode(catalogs, make_vault)
    response = serve().client.send_json("PATCH", "/catalog/vault/episodes",
                                        payload={"id": "a1", "title": "x"})
    assert response.status == 404, response.status


# Spec: ## `/catalog/<name>/<category>/<id>` Annotation Methods
# Context: T82 - and `DELETE` at the site root is not one either.
def test_delete_on_the_root_is_not_found(serve, make_vault, catalogs):
    one_episode(catalogs, make_vault)
    response = serve().client.send_json("DELETE", "/", payload={"id": "a1"})
    assert response.status == 404, response.status


# Spec: | `POST` | `/` | Accept form-encoded body; redirect to
#   `/catalog/<value>` ... | (earlier viewer section)
# Context: adding annotation methods must not disturb the landing form post.
def test_landing_form_post_still_works(serve, make_vault, catalogs):
    one_episode(catalogs, make_vault)
    response = serve().client.post("/", {"catalog": "vault"})
    assert response.status in (301, 302, 303, 307, 308), response.status
    assert urllib.parse.urlsplit(response.location).path == "/catalog/vault"
