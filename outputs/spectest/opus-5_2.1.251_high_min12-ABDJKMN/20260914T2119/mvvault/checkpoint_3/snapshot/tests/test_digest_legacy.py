"""Spec: `digest` Format-Aware Loading and `digest` Current Value Resolution."""
from digest_helpers import (K1, K2, K3, E1, E2, E3, v1, v2, v3, v3_entry,
                            legacy_entry, v1_entry, sections, entry_titles,
                            trailing_line)


# Spec: "`digest` must work directly on v1, v2, and v3 catalogs without
# migrating." -- v1 history keys are UNIX-epoch strings.
def test_v1_history_key_format_is_epoch(run, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1",
                                        title={E1: "Old", E2: "New"})]))
    res = run("digest", "vault")
    assert res.returncode == 0, res
    assert entry_titles(res.stdout, "Entries", "Updated") == ["New (title)"]


# Spec: "| v1 | ... | History Key Format | UNIX-epoch string keys |" -- ISO
# keys are not what a v1 catalog carries; a v1 catalog with ISO keys is
# malformed and is rejected rather than silently reinterpreted.
def test_v1_rejects_iso_history_keys(run, make_vault):
    make_vault(v1(entries=[legacy_entry(id="e1", title={K1: "X"})]))
    res = run("digest", "vault")
    assert res.returncode != 0
    assert res.stderr != ""


# Spec: "| v1 | Value at the latest key by **numeric** comparison of UNIX-epoch
# strings |" -- "1000000000" > "999999999" numerically but not
# lexicographically.
def test_v1_latest_value_uses_numeric_comparison(run, make_vault):
    # 999999999 == 2001-09-09, 1000000000 == 2001-09-09 one second later.
    make_vault(v1(entries=[v1_entry(
        id="e1", title={"999999999": "Earlier", "1000000000": "Later"})]))
    out = run("digest", "vault").stdout
    assert entry_titles(out, "Entries", "Updated") == ["Later (title)"]


# Spec: "v1 history ordering in digest | Numeric comparison of epoch-second
# strings" -- the *prior* value is the numerically second-largest key too.
def test_v1_prior_value_uses_numeric_comparison(run, make_vault):
    make_vault(v1(entries=[v1_entry(
        id="e1", title={"999999999": "Same", "1000000000": "Same"})]))
    out = run("digest", "vault").stdout
    assert sections(out) == {}


# Spec: "| v2 | Value at the latest key by **lexicographic** comparison of ISO
# 8601 strings |"
def test_v2_latest_value_uses_lexicographic_comparison(run, make_vault):
    make_vault(v2(episodes=[legacy_entry(
        id="e1", title={K1: "First", K3: "Last", K2: "Middle"})]))
    out = run("digest", "vault").stdout
    assert entry_titles(out, "Episodes", "Updated") == ["Last (title)"]


# Spec: "| v3 | Value at the latest key by **lexicographic** comparison of ISO
# 8601 strings |" -- lexicographic order, so a `Z`-suffixed key sorts after the
# bare key for the same instant.
def test_v3_latest_value_uses_lexicographic_comparison(run, make_vault):
    make_vault(v3(episodes=[v3_entry(
        id="e1", title={"2024-02-01T00:00:00": "Bare",
                        "2024-02-01T00:00:00Z": "Suffixed"})]))
    out = run("digest", "vault").stdout
    assert entry_titles(out, "Episodes", "Updated") == ["Suffixed (title)"]


# Spec: "| v3 | ... Full removal detection |"
def test_v3_full_removal_detection(run, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1", title="Gone",
                                     removed={K1: False, K2: True})]))
    assert entry_titles(run("digest", "vault").stdout, "Episodes", "Removed") \
        == ["Gone"]


# Spec: "| v2 | ... | Removal Detection | Not available (no `removed` field) |"
# -- a v2 entry that vanished from the source is simply not detectable.
def test_v2_removal_not_detected(run, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1", title={K1: "A", K2: "B"})]))
    groups = sections(run("digest", "vault").stdout)["Episodes"]
    assert list(groups) == ["Updated"]


# Spec: "| v1 | ... | Removal Detection | Not available (no `removed` field) |"
def test_v1_removal_not_detected(run, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", title={E1: "A", E2: "B"})]))
    groups = sections(run("digest", "vault").stdout)["Entries"]
    assert list(groups) == ["Updated"]


# Spec: "| v1 | `https://media.example.com/channel/<source_id>` |" -- the v1
# source is derived, never read from a `source` key.
def test_v1_source_is_derived_from_source_id(run, make_vault):
    catalog = v1(source_id="abc123", entries=[v1_entry(id="e1")])
    make_vault(catalog)
    line = trailing_line(run("digest", "vault").stdout)
    assert "https://media.example.com/channel/abc123" in line


# Spec: "`digest` must work directly on v1, v2, and v3 catalogs without
# migrating." -- a v1 catalog has no category arrays, and that is fine.
def test_v1_catalog_without_category_arrays_is_accepted(run, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1", title="Solo")]))
    res = run("digest", "vault")
    assert res.returncode == 0, res
    assert entry_titles(res.stdout, "Entries", "Added") == ["Solo"]


# Spec: "without migrating" -- a v2 catalog's entries are read as v2 (five
# tracked fields), so an entry with only initial observations is an addition
# even though a migrated v3 copy would gain a `removed` history.
def test_v2_entry_with_initial_observations_is_an_addition(run, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1", title="Fresh")]))
    assert entry_titles(run("digest", "vault").stdout, "Episodes", "Added") \
        == ["Fresh"]


# Spec: "| Entry text | Current title from latest `title` history value |" --
# resolved with the version's own comparison rule (v1: numeric).
def test_v1_entry_text_uses_numeric_latest_title(run, make_vault):
    make_vault(v1(entries=[v1_entry(
        id="e1", title={E3: "Newest", E1: "Oldest", E2: "Middle"})]))
    assert entry_titles(run("digest", "vault").stdout, "Entries", "Updated") \
        == ["Newest (title)"]
