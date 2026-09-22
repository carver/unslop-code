"""Vault builders shared by the entry-detail and static-endpoint tests.

Each version gets a vault whose `views`/`likes` histories carry two points, so
the same fixture exercises the current value, the chart payload and the
version's own key ordering.
"""

from conftest import legacy_entry, v1_catalog, v2_catalog, v3_catalog, v3_entry, write_vault

#: v1 epoch keys chosen so numeric and lexicographic order disagree: numerically
#: `999999999` is the older key, lexicographically it sorts last.
EPOCH_OLD = "999999999"
EPOCH_NEW = "1718444400"
EPOCH_OLD_AS_ISO = "2001-09-09T01:46:39"
EPOCH_NEW_AS_ISO = "2024-06-15T09:40:00"

#: ISO keys for the v2/v3 fixtures, whose lexicographic order is chronological.
ISO_OLD = "2024-01-02T00:00:00"
ISO_NEW = "2024-06-15T09:40:00"

V1_SOURCE_ID = "chan42"
MODERN_SOURCE = "https://example.test/feed"


def tracked(old_key, new_key, entry_id):
    """Two-point `title`, `description`, `views` and `likes` histories.

    The newer key is written first so a page that preserves insertion order
    instead of sorting is caught.
    """
    return {
        "title": {new_key: f"new-title-{entry_id}", old_key: f"old-title-{entry_id}"},
        "description": {new_key: f"new-description-{entry_id}", old_key: f"old-description-{entry_id}"},
        "views": {new_key: 250, old_key: 100},
        "likes": {new_key: None, old_key: 7},
    }


def v1_vault(tmp_path, name="demo", entry_id="e1", source_id=V1_SOURCE_ID):
    """A v1 vault: one flat `entries` list keyed by UNIX-epoch strings."""
    entry = legacy_entry(entry_id, EPOCH_NEW, **tracked(EPOCH_OLD, EPOCH_NEW, entry_id))
    return write_vault(tmp_path, name, v1_catalog(entry, source_id=source_id))


def v2_vault(tmp_path, name="demo", source=MODERN_SOURCE):
    """A v2 vault carrying one two-point entry in each category."""
    catalog = v2_catalog(
        source,
        episodes=[legacy_entry("e1", ISO_NEW, **tracked(ISO_OLD, ISO_NEW, "e1"))],
        streams=[legacy_entry("s1", ISO_NEW, **tracked(ISO_OLD, ISO_NEW, "s1"))],
        clips=[legacy_entry("c1", ISO_NEW, **tracked(ISO_OLD, ISO_NEW, "c1"))],
    )
    return write_vault(tmp_path, name, catalog)


def v3_vault(tmp_path, name="demo", source=MODERN_SOURCE, removed=None):
    """A v3 vault carrying one two-point entry in each category."""
    catalog = v3_catalog(
        source,
        episodes=[v3_entry("e1", removed=removed, **tracked(ISO_OLD, ISO_NEW, "e1"))],
        streams=[v3_entry("s1", **tracked(ISO_OLD, ISO_NEW, "s1"))],
        clips=[v3_entry("c1", **tracked(ISO_OLD, ISO_NEW, "c1"))],
    )
    return write_vault(tmp_path, name, catalog)


#: Each supported version as `(builder, category, entry_id)` for parametrization.
VERSION_CASES = [
    (v1_vault, "entries", "e1"),
    (v2_vault, "episodes", "e1"),
    (v3_vault, "episodes", "e1"),
]
