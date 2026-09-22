"""Spec section: Detail Page Source Link -- Version-Aware."""

from conftest import (
    V1_SOURCE_TEMPLATE,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)

#: Source URL the v2 and v3 fixtures store.
SOURCE = "http://example.invalid/source.json"


# Spec: v1 | `https://media.example.com/channel/<source_id>/entry/<id>`
def test_v1_source_link_is_derived_from_the_source_id(serve, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")], source_id="chan-7"))
    expected = V1_SOURCE_TEMPLATE.format("chan-7") + "/entry/e1"
    assert expected in serve().get("/catalog/vault/entries/e1").text


# Spec: v2 | `<source>/entry/<id>`
def test_v2_source_link_extends_the_stored_source(serve, tmp_path):
    write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")], source=SOURCE))
    assert f"{SOURCE}/entry/e1" in serve().get("/catalog/vault/episodes/e1").text


# Spec: v3 | `<source>/entry/<id>`
def test_v3_source_link_extends_the_stored_source(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(clips=[v3_entry("c1")], source=SOURCE))
    assert f"{SOURCE}/entry/c1" in serve().get("/catalog/vault/clips/c1").text


# Spec: Source-platform link | Deterministic URL derived from vault source
# information and entry `id`
def test_source_link_uses_the_entry_id_it_was_asked_for(serve, tmp_path):
    entries = [v3_entry("e1"), v3_entry("e2")]
    write_vault(tmp_path, v3_catalog(episodes=entries, source=SOURCE))
    body = serve().get("/catalog/vault/episodes/e2").text
    assert f"{SOURCE}/entry/e2" in body
    assert f"{SOURCE}/entry/e1" not in body


# Spec: Source link | Version-aware derivation; deterministic for same vault and
# entry
def test_source_link_is_stable_across_requests(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")], source=SOURCE))
    viewer = serve()
    first = viewer.get("/catalog/vault/episodes/e1").text
    assert first == viewer.get("/catalog/vault/episodes/e1").text
