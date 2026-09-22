"""Spec section: `entry` Stored Fields."""

from conftest import entry_by_id, payload, read_catalog, run_cli, source_entry

STATIC = ["id", "published", "width", "height"]
TRACKED = ["title", "description", "views", "likes", "preview", "removed"]


def synced_entry(vault, source, entry, category="episodes"):
    source.serve(payload(**{category: [entry]}))
    result = run_cli("sync", "demo", cwd=vault.parent)
    assert result.returncode == 0, result.stderr
    return entry_by_id(read_catalog(vault), category, entry["id"])


# Stored Fields: an entry holds exactly the four static and six tracked fields.
def test_entry_holds_the_documented_fields(vault, source):
    stored = synced_entry(vault, source, source_entry("e1"))
    assert set(stored) == set(STATIC + TRACKED)


# Stored Fields: "Static | `id` | string | Source identifier" and
# "`published` | string | Original publication datetime".
def test_static_text_fields_copy_the_source(vault, source):
    stored = synced_entry(vault, source, source_entry("e1", published="2021-07-04T11:22:33"))
    assert stored["id"] == "e1"
    assert stored["published"] == "2021-07-04T11:22:33"


# Stored Fields: "Static | `width` | integer" and "`height` | integer".
def test_static_dimensions_copy_the_source(vault, source):
    stored = synced_entry(vault, source, source_entry("e1", width=640, height=360))
    assert stored["width"] == 640
    assert stored["height"] == 360


# Stored Fields: the six tracked fields are history objects, not bare values.
def test_tracked_fields_are_history_objects(vault, source):
    stored = synced_entry(vault, source, source_entry("e1"))
    for field in TRACKED:
        assert isinstance(stored[field], dict), field
        assert stored[field], field


# Stored Fields: "Tracked | `title` ... Values are strings" and
# "`description` ... Values are strings" and "`preview` ... Values are strings".
def test_tracked_string_values_are_stored_as_strings(vault, source):
    stored = synced_entry(
        vault, source, source_entry("e1", title="T", description="D", preview="P")
    )
    assert list(stored["title"].values()) == ["T"]
    assert list(stored["description"].values()) == ["D"]
    assert list(stored["preview"].values()) == ["P"]


# Stored Fields: "Tracked | `views` ... Values are integers".
def test_tracked_views_values_are_integers(vault, source):
    stored = synced_entry(vault, source, source_entry("e1", views=1234))
    assert list(stored["views"].values()) == [1234]


# Stored Fields: "Tracked | `likes` ... Values are integers or `null`".
def test_tracked_likes_accepts_integer_and_null(vault, source):
    assert list(synced_entry(vault, source, source_entry("e1", likes=9))["likes"].values()) == [9]
    stored = synced_entry(vault, source, source_entry("e2", likes=None), category="clips")
    assert list(stored["likes"].values()) == [None]


# Stored Fields: "Tracked | `removed` ... Values are booleans".
def test_tracked_removed_values_are_booleans(vault, source):
    stored = synced_entry(vault, source, source_entry("e1"))
    assert list(stored["removed"].values()) == [False]


# History Format: "Local-only fields | Source data does not include `removed` or
# `annotations`" — a source that supplies them does not get them stored as
# source-driven values.
def test_source_supplied_local_only_fields_are_not_adopted(vault, source):
    entry = source_entry("e1")
    entry["removed"] = True
    entry["annotations"] = {"note": "hi"}
    stored = synced_entry(vault, source, entry)

    assert list(stored["removed"].values()) == [False]
    assert "annotations" not in stored


# Stored Fields: "Static" fields keep their first-observation values even when
# the source later reports different ones (see AMBIGUITIES T9).
def test_static_fields_are_not_rewritten_by_later_syncs(vault, source):
    synced_entry(vault, source, source_entry("e1", published="2020-01-01T00:00:00", width=100))
    stored = synced_entry(
        vault, source, source_entry("e1", published="2030-01-01T00:00:00", width=999)
    )
    assert stored["published"] == "2020-01-01T00:00:00"
    assert stored["width"] == 100
