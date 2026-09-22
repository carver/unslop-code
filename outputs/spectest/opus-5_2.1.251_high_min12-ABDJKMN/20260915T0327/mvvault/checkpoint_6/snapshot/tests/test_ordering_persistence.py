"""Spec sections: `catalog.json` Ordering, `catalog.json` Persistence,
`mvault` Determinism."""
import json
import re

import pytest

from conftest import current, entry, find, payload, read_catalog

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


# --- Phrase: "| `1` | Newest `published` first |"
def test_entries_sorted_newest_published_first(run, source, vault, tmp_path):
    source.set_payload(
        payload(
            episodes=[
                entry("a", published="2022-01-01T00:00:00"),
                entry("b", published="2024-06-01T12:00:00"),
                entry("c", published="2023-03-15T08:30:00"),
            ]
        )
    )
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    assert [e["id"] for e in catalog["episodes"]] == ["b", "c", "a"]


# --- Phrase: "| `2` | Lexicographically smaller `id` first when `published`
#     values are equal |"
def test_ties_break_on_lexicographically_smaller_id(run, source, vault, tmp_path):
    source.set_payload(
        payload(
            episodes=[
                entry("zz", published="2024-01-01T00:00:00"),
                entry("aa", published="2024-01-01T00:00:00"),
                entry("Ab", published="2024-01-01T00:00:00"),
                entry("ab", published="2024-01-01T00:00:00"),
            ]
        )
    )
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    assert [e["id"] for e in catalog["episodes"]] == ["Ab", "aa", "ab", "zz"]


# --- Phrase: "Entry order | Newest `published` first; ties break by
#     lexicographically smaller `id`" (context: applies to every category, and
#     to removed entries too)
@pytest.mark.parametrize("category", ["episodes", "streams", "clips"])
def test_ordering_applies_to_every_category(run, source, vault, tmp_path, category):
    items = [
        entry("old", published="2020-01-01T00:00:00"),
        entry("new", published="2026-01-01T00:00:00"),
    ]
    source.set_payload(payload(**{category: items}))
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    assert [e["id"] for e in catalog[category]] == ["new", "old"]


def test_ordering_is_maintained_after_later_syncs(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("m", published="2023-01-01")]))
    run("sync", "vault")
    source.set_payload(
        payload(
            episodes=[
                entry("z", published="2025-01-01"),
                entry("a", published="2021-01-01"),
            ]
        )
    )
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    # "m" is now removed but is still ordered by its published value.
    assert [e["id"] for e in catalog["episodes"]] == ["z", "m", "a"]


# --- Phrase: "Date-only source values | Normalize to `00:00:00` time
#     component" (see AMBIGUITIES T2)
def test_date_only_published_is_normalized(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", published="2024-02-29")]))
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    assert stored["published"] == "2024-02-29T00:00:00"


# --- Phrase: "Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix"
@pytest.mark.parametrize(
    "given,expected",
    [
        ("2024-05-04T10:20:30", "2024-05-04T10:20:30"),
        ("2024-05-04T10:20:30Z", "2024-05-04T10:20:30"),
        ("2024-05-04T10:20:30+02:00", "2024-05-04T10:20:30"),
        ("2024-05-04", "2024-05-04T00:00:00"),
    ],
)
def test_published_text_has_no_timezone_suffix(
    run, source, vault, tmp_path, given, expected
):
    source.set_payload(payload(episodes=[entry("e1", published=given)]))
    assert run("sync", "vault").returncode == 0
    stored = find(read_catalog(tmp_path), "e1")
    assert stored["published"] == expected


# --- Phrase: "Date-only source values | Normalize to `00:00:00`" (context:
#     ordering compares the normalized values)
def test_mixed_date_and_datetime_ordering(run, source, vault, tmp_path):
    source.set_payload(
        payload(
            episodes=[
                entry("a", published="2024-01-02"),
                entry("b", published="2024-01-01T23:59:59"),
                entry("c", published="2024-01-02T00:00:01"),
            ]
        )
    )
    run("sync", "vault")
    catalog = read_catalog(tmp_path)
    assert [e["id"] for e in catalog["episodes"]] == ["c", "a", "b"]


# --- Phrase: "Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix"
#     (context: history keys use the same format)
def test_history_keys_have_no_timezone_suffix(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault")
    stored = find(read_catalog(tmp_path), "e1")
    for field in ["title", "removed"]:
        for key in stored[field]:
            assert ISO.match(key), key
            assert "Z" not in key and "+" not in key


# --- Phrase: "Sync timestamps | Reflect sync execution time"
def test_sync_timestamp_is_near_execution_time(run, source, vault, tmp_path):
    from datetime import datetime

    before = datetime.now().replace(microsecond=0)
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault")
    after = datetime.now().replace(microsecond=0)
    stored = find(read_catalog(tmp_path), "e1")
    (key,) = list(stored["removed"])
    stamp = datetime.strptime(key, "%Y-%m-%dT%H:%M:%S")
    assert before <= stamp <= after, (before, stamp, after)


# --- Phrase: "Backup trigger | Before every write to existing `catalog.json`"
#     + "Backup path | `catalog.bak`" (see AMBIGUITIES T1)
def test_backup_is_created_in_the_vault_directory(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault")
    assert (tmp_path / "vault" / "catalog.bak").is_file()


# --- Phrase: "Backup trigger | Before every write to existing `catalog.json`"
#     (context: `init` creates the catalog, so no backup exists yet)
def test_init_does_not_create_a_backup(run, tmp_path):
    run("init", "vault", "https://example.invalid/f.json")
    assert not (tmp_path / "vault" / "catalog.bak").exists()


# --- Phrase: "Backup content | Byte-for-byte copy of pre-write `catalog.json`"
def test_backup_is_byte_for_byte_copy_of_previous_catalog(
    run, source, vault, tmp_path
):
    source.set_payload(payload(episodes=[entry("e1", title="one")]))
    run("sync", "vault")
    before = (tmp_path / "vault" / "catalog.json").read_bytes()
    source.set_payload(payload(episodes=[entry("e1", title="two")]))
    run("sync", "vault")
    assert (tmp_path / "vault" / "catalog.bak").read_bytes() == before


# --- Phrase: "Backup overwrite | Replace existing `catalog.bak`"
def test_backup_is_replaced_on_each_write(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", title="one")]))
    run("sync", "vault")
    source.set_payload(payload(episodes=[entry("e1", title="two")]))
    run("sync", "vault")
    second = (tmp_path / "vault" / "catalog.json").read_bytes()
    source.set_payload(payload(episodes=[entry("e1", title="three")]))
    run("sync", "vault")
    assert (tmp_path / "vault" / "catalog.bak").read_bytes() == second


# --- Phrase: "Backup content | Byte-for-byte copy of pre-write
#     `catalog.json`" (context: the first sync backs up the pristine init
#     catalog)
def test_first_sync_backs_up_the_init_catalog(run, source, vault, tmp_path):
    pristine = (tmp_path / "vault" / "catalog.json").read_bytes()
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault")
    assert (tmp_path / "vault" / "catalog.bak").read_bytes() == pristine
    assert json.loads(pristine)["episodes"] == []


# --- Phrase: "Backup trigger | Before every write" (context: a sync that
#     changes nothing still completes successfully, see AMBIGUITIES T6)
def test_no_op_sync_succeeds_and_keeps_catalog_content(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1")]))
    run("sync", "vault")
    first = json.loads((tmp_path / "vault" / "catalog.json").read_text())
    assert run("sync", "vault").returncode == 0
    second = json.loads((tmp_path / "vault" / "catalog.json").read_text())
    assert first == second


# --- Phrase: "Locale | No locale-sensitive formatting anywhere"
def test_output_is_locale_independent(run, source, vault, tmp_path):
    import os
    import subprocess
    import sys

    from conftest import MVAULT

    source.set_payload(payload(episodes=[entry("e1", views=1234567)]))
    env = dict(os.environ, LC_ALL="de_DE.UTF-8", LANG="de_DE.UTF-8")
    proc = subprocess.run(
        [sys.executable, MVAULT, "sync", "vault"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    stored = find(read_catalog(tmp_path), "e1")
    assert current(stored, "views") == 1234567
    (key,) = list(stored["removed"])
    assert ISO.match(key), key


# --- Phrase: "Catalog path | `<name>/catalog.json`" (context: the catalog is
#     valid JSON text, readable without the tool)
def test_catalog_is_utf8_json_text(run, source, vault, tmp_path):
    source.set_payload(payload(episodes=[entry("e1", title="Ünïcodé — ☃")]))
    run("sync", "vault")
    text = (tmp_path / "vault" / "catalog.json").read_bytes().decode("utf-8")
    catalog = json.loads(text)
    assert current(catalog["episodes"][0], "title") == "Ünïcodé — ☃"
