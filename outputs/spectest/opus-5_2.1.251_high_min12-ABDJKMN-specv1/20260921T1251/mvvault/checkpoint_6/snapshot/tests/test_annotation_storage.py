"""Spec section: `annotations` Storage and `annotations` Storage Location."""

from __future__ import annotations

import json


def one_episode(catalogs, make_vault, entry_id="e1"):
    return make_vault(catalogs.catalog(episodes=[catalogs.entry(entry_id)]))


# ---------------------------------------------------------------------------
# | `annotations` Storage | field types |
# ---------------------------------------------------------------------------

# Spec: | `id` | string | Unique within entry |
def test_stored_id_is_a_string(serve, make_vault, catalogs, annotate, workdir):
    one_episode(catalogs, make_vault)
    annotate.make(serve().client, "vault", "episodes", "e1")
    stored = annotate.only(workdir, "vault", "e1")
    assert isinstance(stored["id"], str) and stored["id"]


# Spec: | `id` | string | Unique within entry |
def test_stored_ids_are_unique_within_the_entry(serve, make_vault, catalogs,
                                                annotate, workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    for index in range(5):
        annotate.make(client, "vault", "episodes", "e1", title=f"n{index}")
    ids = [item["id"] for item in annotate.stored(workdir, "vault", "e1")]
    assert len(set(ids)) == len(ids) == 5, ids


# Spec: | `id` | string | Unique within entry |
# Context: uniqueness is scoped to one entry, so a delete-then-create cycle
# must not hand out an id the entry still holds.
def test_ids_stay_unique_after_a_delete(serve, make_vault, catalogs, annotate,
                                        workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", title="a")
    annotate.make(client, "vault", "episodes", "e1", title="b")
    stored = annotate.stored(workdir, "vault", "e1")
    annotate.remove(client, "vault", "episodes", "e1", {"id": stored[0]["id"]})
    annotate.make(client, "vault", "episodes", "e1", title="c")
    ids = [item["id"] for item in annotate.stored(workdir, "vault", "e1")]
    assert len(set(ids)) == len(ids) == 2, ids


# Spec: | `timecode` | integer | Whole seconds |
def test_stored_timecode_is_an_integer(serve, make_vault, catalogs, annotate,
                                       workdir):
    one_episode(catalogs, make_vault)
    annotate.make(serve().client, "vault", "episodes", "e1", timecode="1:30")
    stored = annotate.only(workdir, "vault", "e1")
    assert stored["timecode"] == 90
    assert isinstance(stored["timecode"], int)
    assert not isinstance(stored["timecode"], bool)


# Spec: | `timecode` | integer | Whole seconds |
# Context: the catalog holds a JSON number, not the submitted text.
def test_stored_timecode_is_json_number(serve, make_vault, catalogs, annotate,
                                        workdir):
    one_episode(catalogs, make_vault)
    annotate.make(serve().client, "vault", "episodes", "e1", timecode="1:30")
    text = annotate.catalog_text(workdir)
    assert '"timecode": 90' in text or '"timecode":90' in text, text
    assert '"timecode": "90"' not in text and '"timecode":"90"' not in text


# Spec: | `title` | string | Stored as provided |
def test_title_is_stored_as_provided(serve, make_vault, catalogs, annotate,
                                     workdir):
    one_episode(catalogs, make_vault)
    annotate.make(serve().client, "vault", "episodes", "e1",
                  title="  Mixed Case & <marks>  ")
    stored = annotate.only(workdir, "vault", "e1")
    assert stored["title"] == "  Mixed Case & <marks>  "


# Spec: | `body` | string or `null` | Stored as provided or defaulted to `null` |
def test_body_is_stored_as_provided(serve, make_vault, catalogs, annotate,
                                    workdir):
    one_episode(catalogs, make_vault)
    annotate.make(serve().client, "vault", "episodes", "e1",
                  body="multi\nline body")
    assert annotate.only(workdir, "vault", "e1")["body"] == "multi\nline body"


# Spec: | `body` | string or `null` | ... or defaulted to `null` |
# Spec: | `body` | string | no | `null` | (POST Annotation Fields)
def test_body_defaults_to_null(serve, make_vault, catalogs, annotate, workdir):
    one_episode(catalogs, make_vault)
    annotate.make(serve().client, "vault", "episodes", "e1")
    stored = annotate.only(workdir, "vault", "e1")
    assert "body" in stored, stored
    assert stored["body"] is None


# Spec: | `body` | string or `null` | Stored as provided ... |
# Context: an explicit `null` on create is the same as leaving it out.
def test_explicit_null_body_on_create(serve, make_vault, catalogs, annotate,
                                      workdir):
    one_episode(catalogs, make_vault)
    annotate.create(serve().client, "vault", "episodes", "e1",
                    {"title": "n", "timecode": "5", "body": None})
    assert annotate.only(workdir, "vault", "e1")["body"] is None


# Spec: | `title` | string | yes | none | (POST Annotation Fields)
# Context: the stored annotation carries exactly the four storage fields.
def test_stored_annotation_fields(serve, make_vault, catalogs, annotate,
                                  workdir):
    one_episode(catalogs, make_vault)
    annotate.make(serve().client, "vault", "episodes", "e1", title="T",
                  timecode="7", body="B")
    stored = annotate.only(workdir, "vault", "e1")
    assert set(stored) >= {"id", "timecode", "title", "body"}
    assert (stored["title"], stored["timecode"], stored["body"]) == ("T", 7, "B")


# ---------------------------------------------------------------------------
# | `annotations` Storage Location |
# ---------------------------------------------------------------------------

# Spec: | Catalog location | Entry object key `annotations` |
def test_annotations_live_on_the_entry_object(serve, make_vault, catalogs,
                                              annotate, workdir, helpers):
    one_episode(catalogs, make_vault)
    annotate.make(serve().client, "vault", "episodes", "e1")
    catalog = helpers.read_catalog(workdir)
    assert "annotations" not in catalog
    assert "annotations" in catalog["episodes"][0]


# Spec: | Catalog location | Entry object key `annotations` |
# Context: only the targeted entry gains an annotation.
def test_other_entries_are_untouched(serve, make_vault, catalogs, annotate,
                                     workdir):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1"),
                                          catalogs.entry("e2")],
                                clips=[catalogs.entry("c1")]))
    annotate.make(serve().client, "vault", "episodes", "e1")
    assert annotate.stored(workdir, "vault", "e2") == []
    assert annotate.stored(workdir, "vault", "c1") == []


# Spec: | Container type | Ordered list |
def test_container_is_a_list(serve, make_vault, catalogs, annotate, workdir):
    one_episode(catalogs, make_vault)
    annotate.make(serve().client, "vault", "episodes", "e1")
    assert isinstance(annotate.stored(workdir, "vault", "e1"), list)


# Spec: | List order | Creation order |
def test_list_is_in_creation_order(serve, make_vault, catalogs, annotate,
                                   workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    for title, timecode in [("third-made-first", "300"),
                            ("second", "10"),
                            ("last", "120")]:
        annotate.make(client, "vault", "episodes", "e1", title=title,
                      timecode=timecode)
    titles = [item["title"] for item in annotate.stored(workdir, "vault", "e1")]
    assert titles == ["third-made-first", "second", "last"]


# Spec: | List order | Creation order |
# Context: an update does not move an annotation within the list.
def test_update_keeps_position(serve, make_vault, catalogs, annotate, workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    for title in ("a", "b", "c"):
        annotate.make(client, "vault", "episodes", "e1", title=title)
    stored = annotate.stored(workdir, "vault", "e1")
    annotate.update(client, "vault", "episodes", "e1",
                    {"id": stored[0]["id"], "title": "a-updated"})
    titles = [item["title"] for item in annotate.stored(workdir, "vault", "e1")]
    assert titles == ["a-updated", "b", "c"]


# Spec: | List order | Creation order |
# Context: a delete closes the gap without reordering the rest.
def test_delete_keeps_relative_order(serve, make_vault, catalogs, annotate,
                                     workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    for title in ("a", "b", "c", "d"):
        annotate.make(client, "vault", "episodes", "e1", title=title)
    stored = annotate.stored(workdir, "vault", "e1")
    annotate.remove(client, "vault", "episodes", "e1", {"id": stored[1]["id"]})
    titles = [item["title"] for item in annotate.stored(workdir, "vault", "e1")]
    assert titles == ["a", "c", "d"]


# ---------------------------------------------------------------------------
# | Save behavior | `catalog.bak` written before persisting annotation changes |
# ---------------------------------------------------------------------------

# Spec: | Save behavior | `catalog.bak` written before persisting annotation
#   changes |
def test_create_writes_a_backup(serve, make_vault, catalogs, annotate,
                                workdir):
    one_episode(catalogs, make_vault)
    annotate.make(serve().client, "vault", "episodes", "e1")
    assert annotate.has_backup(workdir)


# Spec: | Backup before annotation | If catalog was already v3, `catalog.bak`
#   contains pre-annotation catalog |
def test_backup_holds_the_pre_annotation_catalog(serve, make_vault, catalogs,
                                                 annotate, workdir):
    vault = one_episode(catalogs, make_vault)
    before = json.loads((vault / "catalog.json").read_text(encoding="utf-8"))
    annotate.make(serve().client, "vault", "episodes", "e1")
    assert annotate.backup(workdir) == before
    assert annotate.backup(workdir)["episodes"][0]["annotations"] == []


# Spec: | Save behavior | `catalog.bak` written before persisting annotation
#   changes |
# Context: each further mutation refreshes the backup with the state that
# preceded it.
def test_backup_tracks_the_previous_state(serve, make_vault, catalogs,
                                          annotate, workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", title="first")
    annotate.make(client, "vault", "episodes", "e1", title="second")
    backup = annotate.backup(workdir)
    titles = [item["title"] for item in backup["episodes"][0]["annotations"]]
    assert titles == ["first"]


# Spec: | Save behavior | `catalog.bak` written before persisting annotation
#   changes | (update)
def test_update_writes_a_backup(serve, make_vault, catalogs, annotate,
                                workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", title="before")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    annotate.update(client, "vault", "episodes", "e1",
                    {"id": annotation_id, "title": "after"})
    backup = annotate.backup(workdir)
    assert backup["episodes"][0]["annotations"][0]["title"] == "before"


# Spec: | Save behavior | `catalog.bak` written before persisting annotation
#   changes | (delete)
def test_delete_writes_a_backup(serve, make_vault, catalogs, annotate,
                                workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", title="doomed")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    annotate.remove(client, "vault", "episodes", "e1", {"id": annotation_id})
    backup = annotate.backup(workdir)
    assert len(backup["episodes"][0]["annotations"]) == 1
    assert annotate.stored(workdir, "vault", "e1") == []


# ---------------------------------------------------------------------------
# | Read-after-write behavior | Later `GET` to same entry detail page reflects
#   create, update, or delete result by visibly rendering stored annotations,
#   each `timecode` as raw seconds |
# ---------------------------------------------------------------------------

# Spec: | Read-after-write behavior | Later `GET` ... reflects create ... |
def test_get_shows_a_created_annotation(serve, make_vault, catalogs, annotate,
                                        detail):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", title="Chapter one",
                  body="the opening")
    text = annotate.text(client.get(detail.path("vault", "episodes", "e1")).body)
    assert "Chapter one" in text
    assert "the opening" in text


# Spec: | ... | ... each `timecode` as raw seconds |
def test_get_renders_timecode_as_raw_seconds(serve, make_vault, catalogs,
                                             annotate, detail):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", title="Chapter one",
                  timecode="1:01:30")
    text = annotate.text(client.get(detail.path("vault", "episodes", "e1")).body)
    assert "3690" in text, text
    assert "1:01:30" not in text, text


# Spec: | Read-after-write behavior | ... visibly rendering stored annotations |
# Context: "visibly" means page text, not just an embedded JSON payload or an
# HTML attribute.
def test_annotation_is_visible_text(serve, make_vault, catalogs, annotate,
                                    detail):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", title="Visible title",
                  timecode="42")
    page = client.get(detail.path("vault", "episodes", "e1")).body
    text = annotate.text(page)
    assert "Visible title" in text
    assert "42" in text


# Spec: | Read-after-write behavior | Later `GET` ... reflects ... update ... |
def test_get_shows_an_updated_annotation(serve, make_vault, catalogs,
                                         annotate, detail, workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", title="Before")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    annotate.update(client, "vault", "episodes", "e1",
                    {"id": annotation_id, "title": "After"})
    text = annotate.text(client.get(detail.path("vault", "episodes", "e1")).body)
    assert "After" in text
    assert "Before" not in text


# Spec: | Read-after-write behavior | Later `GET` ... reflects ... delete ... |
def test_get_drops_a_deleted_annotation(serve, make_vault, catalogs, annotate,
                                        detail, workdir):
    one_episode(catalogs, make_vault)
    client = serve().client
    annotate.make(client, "vault", "episodes", "e1", title="Doomed note")
    annotation_id = annotate.only(workdir, "vault", "e1")["id"]
    annotate.remove(client, "vault", "episodes", "e1", {"id": annotation_id})
    text = annotate.text(client.get(detail.path("vault", "episodes", "e1")).body)
    assert "Doomed note" not in text


# Spec: | Annotation list order | Same order as stored in `catalog.json` |
def test_page_lists_annotations_in_stored_order(serve, make_vault, catalogs,
                                                annotate, detail):
    one_episode(catalogs, make_vault)
    client = serve().client
    for title, timecode in [("zeta", "300"), ("alpha", "10"), ("mid", "120")]:
        annotate.make(client, "vault", "episodes", "e1", title=title,
                      timecode=timecode)
    text = annotate.text(client.get(detail.path("vault", "episodes", "e1")).body)
    positions = [text.index(title) for title in ("zeta", "alpha", "mid")]
    assert positions == sorted(positions), text


# Spec: | Read-after-write behavior | ... | Context: a second, independent
# browser session sees the same stored annotations.
def test_annotation_survives_a_new_session(serve, make_vault, catalogs,
                                           annotate, detail):
    one_episode(catalogs, make_vault)
    viewer = serve()
    annotate.make(viewer.client, "vault", "episodes", "e1", title="Durable")
    other = viewer.client.fresh()
    text = annotate.text(other.get(detail.path("vault", "episodes", "e1")).body)
    assert "Durable" in text


# Spec: | Read-after-write behavior | ... |
# Context: T78 - a v3 entry with no `annotations` key gets one on create.
def test_v3_entry_without_annotations_key(serve, make_vault, catalogs,
                                          annotate, workdir):
    entry = catalogs.entry("e1")
    del entry["annotations"]
    make_vault(catalogs.catalog(episodes=[entry]))
    annotate.make(serve().client, "vault", "episodes", "e1", title="fresh")
    stored = annotate.stored(workdir, "vault", "e1")
    assert [item["title"] for item in stored] == ["fresh"]


# Spec: | ... | Context: an annotation write leaves the entry's history and
# static fields exactly as they were.
def test_annotation_write_preserves_the_rest_of_the_entry(serve, make_vault,
                                                          catalogs, annotate,
                                                          workdir, helpers):
    vault = one_episode(catalogs, make_vault)
    before = json.loads((vault / "catalog.json").read_text(encoding="utf-8"))
    annotate.make(serve().client, "vault", "episodes", "e1")
    after = helpers.read_catalog(workdir)
    entry_before = before["episodes"][0]
    entry_after = dict(after["episodes"][0])
    entry_after["annotations"] = []
    assert entry_after == entry_before
    assert after["version"] == before["version"]
    assert after["source"] == before["source"]
