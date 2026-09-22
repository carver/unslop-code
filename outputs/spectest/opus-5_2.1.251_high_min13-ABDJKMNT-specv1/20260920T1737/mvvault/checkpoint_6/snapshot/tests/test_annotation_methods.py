"""Spec sections: annotation overview and `/catalog/<name>/<category>/<id>`
Annotation Methods."""

import pytest
from annotation_fixtures import V1_ENTRY, V3_ENTRY, created, delete, mark, patch, post, stored
from conftest import REDIRECT_STATUSES, read_catalog
from detail_fixtures import v1_vault, v2_vault, v3_vault


# Phrase: "Entry detail pages support user-managed annotations."
def test_a_created_annotation_appears_on_the_entry_detail_page(viewer, tmp_path):
    v3_vault(tmp_path)

    post(viewer, mark(title="chorus starts"))

    assert "chorus starts" in viewer.client.get(V3_ENTRY).body


# Phrase: "Annotations require version 3 catalog format."
def test_an_annotated_vault_is_a_version_3_catalog(viewer, tmp_path):
    vault = v3_vault(tmp_path)

    post(viewer)

    assert read_catalog(vault)["version"] == 3


# Phrase: "Writing an annotation to a v1 or v2 vault triggers automatic
# migration to v3 before the annotation is persisted."
@pytest.mark.parametrize("build, path", [(v1_vault, V1_ENTRY), (v2_vault, V3_ENTRY)])
def test_writing_to_a_legacy_vault_migrates_it_to_v3_first(viewer, tmp_path, build, path):
    vault = build(tmp_path)

    assert post(viewer, path=path).status in REDIRECT_STATUSES

    catalog = read_catalog(vault)
    assert catalog["version"] == 3
    assert catalog["episodes"][0]["annotations"][0]["title"] == "chorus"


# Phrase: "| `POST` | Create annotation | JSON with `title`, `timecode`, optional
# `body` | Redirect to entry detail page with `?timecode=<seconds>` |"
def test_post_redirects_to_the_detail_page_carrying_the_timecode(viewer, tmp_path):
    v3_vault(tmp_path)

    response = post(viewer, mark(timecode="1:30"))

    assert response.status in REDIRECT_STATUSES
    assert response.location.endswith(f"{V3_ENTRY}?timecode=90")


# Phrase: "| `PATCH` | Update annotation | JSON with `id` and at least one of
# `title` or `body` | Redirect to entry detail page |"
def test_patch_redirects_to_the_detail_page(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    annotation = created(viewer, vault)

    response = patch(viewer, {"id": annotation["id"], "title": "bridge"})

    assert response.status in REDIRECT_STATUSES
    assert response.location.endswith(V3_ENTRY)
    assert stored(vault)[0]["title"] == "bridge"


# Phrase: "| `DELETE` | Delete annotation | JSON with `id` | Redirect to entry
# detail page |"
def test_delete_redirects_to_the_detail_page(viewer, tmp_path):
    vault = v3_vault(tmp_path)
    annotation = created(viewer, vault)

    response = delete(viewer, {"id": annotation["id"]})

    assert response.status in REDIRECT_STATUSES
    assert response.location.endswith(V3_ENTRY)
    assert stored(vault) == []


# Phrase: "Redirect to entry detail page" -- the location a mutation names is a
# page the viewer actually serves.
def test_the_redirect_target_is_the_entry_detail_page(viewer, tmp_path):
    v3_vault(tmp_path)

    followed = viewer.client.follow(post(viewer).location)

    assert followed.status == 200
    assert "new-title-e1" in followed.body
