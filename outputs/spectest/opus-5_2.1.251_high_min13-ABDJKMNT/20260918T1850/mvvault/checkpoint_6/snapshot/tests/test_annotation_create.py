"""Spec sections: `/catalog/<name>/<category>/<id>` Annotation Methods (`POST`),
`POST` Annotation Fields, and `annotations` Storage."""

from conftest import (
    create,
    entry_route,
    location,
    stored_annotations,
    v3_catalog,
    v3_entry,
    write_vault,
)

ROUTE = entry_route("vault", "episodes", "e1")


def one_entry(tmp_path, **overrides):
    """A v3 vault holding a single episode `e1`."""
    return write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1", **overrides)]))


# Spec: `POST` | Create annotation | JSON with `title`, `timecode`, optional `body`
def test_create_accepts_title_timecode_and_body(serve, tmp_path):
    vault_dir = one_entry(tmp_path)
    create(serve(), ROUTE, title="Chorus", timecode="1:30", body="the good bit")
    assert stored_annotations(vault_dir, "episodes", "e1") == [
        {"id": "a1", "timecode": 90, "title": "Chorus", "body": "the good bit"}
    ]


# Spec: `POST` | ... | Redirect to entry detail page with `?timecode=<seconds>`
def test_create_redirects_to_the_entry_detail_page(serve, tmp_path):
    one_entry(tmp_path)
    response = create(serve(), ROUTE, title="Chorus", timecode="1:30")
    path, query = location(response)
    assert path == ROUTE
    assert query == {"timecode": ["90"]}


# Spec: `body` | string | no | `null` (the default when the field is omitted)
def test_body_defaults_to_null_when_omitted(serve, tmp_path):
    vault_dir = one_entry(tmp_path)
    create(serve(), ROUTE, title="Chorus", timecode="90")
    assert stored_annotations(vault_dir, "episodes", "e1")[0]["body"] is None


# Spec: `title` | string | yes | none -- stored as provided
def test_title_is_stored_exactly_as_provided(serve, tmp_path):
    vault_dir = one_entry(tmp_path)
    create(serve(), ROUTE, title="  Spaced & <odd>  ", timecode="0")
    assert stored_annotations(vault_dir, "episodes", "e1")[0]["title"] == "  Spaced & <odd>  "


# Spec: `body` | string or `null` | Stored as provided
def test_body_is_stored_exactly_as_provided(serve, tmp_path):
    vault_dir = one_entry(tmp_path)
    create(serve(), ROUTE, title="Chorus", timecode="0", body="")
    assert stored_annotations(vault_dir, "episodes", "e1")[0]["body"] == ""


# Spec: `timecode` | integer | Whole seconds (never the text that was posted)
def test_timecode_is_stored_as_whole_seconds(serve, tmp_path):
    vault_dir = one_entry(tmp_path)
    create(serve(), ROUTE, title="Chorus", timecode="1:01:30")
    stored = stored_annotations(vault_dir, "episodes", "e1")[0]["timecode"]
    assert stored == 3690 and isinstance(stored, int)


# Spec: `id` | string | Unique within entry
def test_each_created_annotation_gets_its_own_id(serve, tmp_path):
    vault_dir = one_entry(tmp_path)
    viewer = serve()
    for index in range(3):
        create(viewer, ROUTE, title=f"Mark {index}", timecode=str(index))
    ids = [item["id"] for item in stored_annotations(vault_dir, "episodes", "e1")]
    assert len(set(ids)) == 3
    assert all(isinstance(value, str) for value in ids)


# Spec: Entry object key `annotations` (T78: a v3 entry stored without the key)
def test_create_works_on_a_v3_entry_that_has_no_annotations_key(serve, tmp_path):
    entry = v3_entry("e1")
    del entry["annotations"]
    vault_dir = write_vault(tmp_path, v3_catalog(episodes=[entry]))
    create(serve(), ROUTE, title="Chorus", timecode="5")
    assert stored_annotations(vault_dir, "episodes", "e1")[0]["timecode"] == 5


# Spec: Annotation identifier inside current entry (annotations are per entry)
def test_annotations_are_scoped_to_one_entry(serve, tmp_path):
    vault_dir = write_vault(
        tmp_path, v3_catalog(episodes=[v3_entry("e1")], clips=[v3_entry("c1")])
    )
    create(serve(), ROUTE, title="Chorus", timecode="5")
    assert stored_annotations(vault_dir, "clips", "c1") == []


# Spec: v3 | Apply annotation directly (the catalog stays v3)
def test_creating_on_a_v3_vault_leaves_the_version_alone(serve, tmp_path):
    vault_dir = one_entry(tmp_path)
    create(serve(), ROUTE, title="Chorus", timecode="5")
    assert stored_annotations(vault_dir, "episodes", "e1")[0]["title"] == "Chorus"
