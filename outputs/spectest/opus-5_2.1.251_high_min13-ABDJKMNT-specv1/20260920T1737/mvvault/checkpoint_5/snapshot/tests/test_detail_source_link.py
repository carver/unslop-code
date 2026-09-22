"""Spec section: Detail Page Source Link -- Version-Aware."""

import pytest
from detail_fixtures import v1_vault, v2_vault, v3_vault


def detail_body(viewer, category="episodes", entry_id="e1"):
    return viewer.client.get(f"/catalog/demo/{category}/{entry_id}").body


# Phrase: "| v1 | `https://media.example.com/channel/<source_id>/entry/<id>` |".
def test_v1_source_link_is_built_from_the_source_id(viewer, tmp_path):
    v1_vault(tmp_path, source_id="chan42")

    assert "https://media.example.com/channel/chan42/entry/e1" in detail_body(viewer, "entries")


# Phrase: "| v1 | `https://media.example.com/channel/<source_id>/entry/<id>` |"
# -- the link follows the vault's own `source_id`, not a fixed one.
def test_v1_source_link_follows_the_stored_source_id(viewer, tmp_path):
    v1_vault(tmp_path, source_id="other-channel")

    assert "https://media.example.com/channel/other-channel/entry/e1" in detail_body(viewer, "entries")


# Phrase: "| v2 | `<source>/entry/<id>` |".
def test_v2_source_link_extends_the_stored_source(viewer, tmp_path):
    v2_vault(tmp_path, source="https://example.test/feed")

    assert "https://example.test/feed/entry/e1" in detail_body(viewer)


# Phrase: "| v3 | `<source>/entry/<id>` |".
def test_v3_source_link_extends_the_stored_source(viewer, tmp_path):
    v3_vault(tmp_path, source="https://example.test/feed")

    assert "https://example.test/feed/entry/e1" in detail_body(viewer)


# Phrase: "| v2 | `<source>/entry/<id>` |" -- the link carries the requested
# entry's id, so sibling entries get distinct links.
@pytest.mark.parametrize("category, entry_id", [("streams", "s1"), ("clips", "c1")])
def test_source_link_carries_the_requested_entry_id(viewer, tmp_path, category, entry_id):
    v3_vault(tmp_path)

    assert f"https://example.test/feed/entry/{entry_id}" in detail_body(viewer, category, entry_id)


# Phrase: "| Source link | Version-aware derivation; deterministic for same
# vault and entry |" -- a v1 vault derives every entry link from its channel
# URL, so no bare `source_id` link is emitted alongside it.
def test_v1_emits_only_the_channel_derived_link(viewer, tmp_path):
    v1_vault(tmp_path, source_id="chan42")

    body = detail_body(viewer, "entries")

    links = [part for part in body.split('"') if part.endswith("/entry/e1")]
    assert links == ["https://media.example.com/channel/chan42/entry/e1"]
