"""Spec sections: `sync` Update Rules across categories, and end-to-end
`mvault` Error Handling behavior."""
import json

from conftest import current, entry, find, history_keys, payload, read_catalog


# --- Phrase: "First observation | Add entry to matching category"
#     (context: the same id in different categories is tracked separately,
#     see AMBIGUITIES T7)
def test_same_id_in_two_categories_is_tracked_separately(
    run, source, vault, tmp_path
):
    source.set_payload(
        payload(
            episodes=[entry("x", title="episode")],
            clips=[entry("x", title="clip")],
        )
    )
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    assert current(find(catalog, "x", "episodes"), "title") == "episode"
    assert current(find(catalog, "x", "clips"), "title") == "clip"


# --- Phrase: "Entry absent from current source" (context: absence is scoped to
#     the entry's own category, see AMBIGUITIES T7)
def test_absence_is_per_category(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("x")], clips=[entry("x")]))
    run("sync", "vault")
    source.set_payload(payload(clips=[entry("x")]))
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    assert current(find(catalog, "x", "episodes"), "removed") is True
    assert current(find(catalog, "x", "clips"), "removed") is False


# --- Phrase: "Success effect | Update catalog with new, changed, removed, and
#     restored entries" (context: one sync doing all four at once)
def test_single_sync_handles_new_changed_removed_and_restored(
    run, source, vault, tmp_path
):
    source.set_payload(
        payload(
            episodes=[
                entry("keep", published="2024-01-04", title="keep-v1"),
                entry("gone", published="2024-01-03"),
                entry("back", published="2024-01-02"),
            ]
        )
    )
    run("sync", "vault")
    # "back" disappears.
    source.set_payload(
        payload(
            episodes=[
                entry("keep", published="2024-01-04", title="keep-v1"),
                entry("gone", published="2024-01-03"),
            ]
        )
    )
    run("sync", "vault")
    # "back" returns, "gone" leaves, "keep" changes, "fresh" appears.
    source.set_payload(
        payload(
            episodes=[
                entry("keep", published="2024-01-04", title="keep-v2"),
                entry("back", published="2024-01-02"),
                entry("fresh", published="2024-01-01"),
            ]
        )
    )
    run("sync", "vault")

    catalog = read_catalog(tmp_path)
    assert [e["id"] for e in catalog["episodes"]] == ["keep", "gone", "back", "fresh"]
    keep, gone, back, fresh = catalog["episodes"]
    assert current(keep, "title") == "keep-v2"
    assert len(keep["title"]) == 2
    assert current(gone, "removed") is True
    assert current(back, "removed") is False
    assert [back["removed"][k] for k in history_keys(back, "removed")] == [
        False,
        True,
        False,
    ]
    assert len(fresh["removed"]) == 1
    assert current(fresh, "removed") is False


# --- Phrase: "Removal handling | Never delete entry from `catalog.json`"
#     (context: an empty source keeps every entry on record)
def test_empty_source_keeps_every_entry(run, source, vault, tmp_path):
    source.set_payload(
        payload(
            episodes=[entry("e1")], streams=[entry("s1")], clips=[entry("c1")]
        )
    )
    run("sync", "vault")
    source.set_payload(payload())
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    for cat, eid in (("episodes", "e1"), ("streams", "s1"), ("clips", "c1")):
        assert len(catalog[cat]) == 1
        assert current(find(catalog, eid, cat), "removed") is True


# --- Phrase: "| `sync` with non-existent vault | stderr | non-zero | Message
#     includes vault name |" (context: nothing is written to stdout-only paths)
def test_sync_error_messages_go_to_stderr_not_stdout(run, tmp_path):
    result = run("sync", "nope")
    assert result.returncode != 0
    assert "nope" in result.stderr
    assert "nope" not in result.stdout


# --- Phrase: "| `init` with existing vault directory | stderr | non-zero |
#     Message includes vault name |"
def test_init_error_messages_go_to_stderr_not_stdout(run, tmp_path):
    run("init", "dup", "https://example.invalid/f.json")
    result = run("init", "dup", "https://example.invalid/f.json")
    assert result.returncode != 0
    assert "dup" in result.stderr
    assert "dup" not in result.stdout


# --- Phrase: "| Source metadata fetch failure | stderr | non-zero | Error
#     message |" (context: the vault stays usable afterwards)
def test_vault_still_syncs_after_a_fetch_failure(run, source, vault, tmp_path):
    source.set_raw("not json")
    assert run("sync", "vault").returncode != 0
    source.set_payload(payload(episodes=[entry("e1")]))
    assert run("sync", "vault").returncode == 0
    assert find(read_catalog(tmp_path), "e1") is not None


# --- Phrase: "Vault input | Existing valid vault at `<name>/`" (context: an
#     existing catalog's own history is preserved verbatim across syncs)
def test_existing_history_is_preserved(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", views=1)]))
    run("sync", "vault")
    first = json.loads((tmp_path / "vault" / "catalog.json").read_text())
    first_hist = dict(first["episodes"][0]["views"])
    source.set_payload(payload(episodes=[entry("e1", views=2)]))
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    for key, value in first_hist.items():
        assert stored["views"][key] == value
