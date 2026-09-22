"""Spec sections: `mvault` Determinism / `mvault` Error Handling."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
TRACKED = ("title", "description", "views", "likes", "preview", "removed")


# Spec: Determinism | Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix |
def test_history_timestamps_have_no_timezone_suffix(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    for field in TRACKED:
        for key in entry[field]:
            assert ISO_RE.match(key), key
            assert not key.endswith("Z")
            assert "+" not in key
            assert "." not in key


# Spec: Determinism | Date-only source values | Normalize to `00:00:00` time component |
def test_date_only_published_normalized(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", published="2024-07-04")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert entry["published"] == "2024-07-04T00:00:00"


# Spec: Determinism | Datetime text | ... | (full datetimes are stored in canonical form)
def test_full_datetime_published_kept_canonical(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(
        episodes=[helpers.make_source_entry("e1", published="2024-07-04T13:45:09")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert entry["published"] == "2024-07-04T13:45:09"
    assert ISO_RE.match(entry["published"])


# Spec: Determinism | Datetime text | ... without timezone suffix |
# Context: source values carrying a suffix are rendered without one. See AMBIGUITIES.md T3.
def test_published_timezone_suffix_is_dropped(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[
        helpers.make_source_entry("z", published="2024-07-04T13:45:09Z"),
    ]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "z")
    assert ISO_RE.match(entry["published"])
    assert entry["published"].startswith("2024-07-04T13:45:09")


# Spec: Determinism | Datetime text | ... | (fractional seconds are dropped)
def test_published_fractional_seconds_dropped(run_cli, vault, source, helpers, workdir):
    source.set(helpers.make_payload(
        episodes=[helpers.make_source_entry("e1", published="2024-07-04T13:45:09.123456")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert entry["published"] == "2024-07-04T13:45:09"


# Spec: Determinism | Sync timestamps | Reflect sync execution time ... |
def test_sync_timestamp_is_close_to_now(run_cli, vault, source, helpers, workdir):
    before = datetime.now().replace(microsecond=0) - timedelta(seconds=2)
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("sync", "vault").returncode == 0
    after = datetime.now().replace(microsecond=0) + timedelta(seconds=120)

    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    stamp = datetime.strptime(helpers.latest_key(entry["title"]), "%Y-%m-%dT%H:%M:%S")
    assert before <= stamp <= after


# Spec: Determinism | Sync timestamps | ... remain strictly increasing whenever new
#       history entries are appended |
def test_sync_timestamps_strictly_increase_across_runs(run_cli, vault, source, helpers, workdir):
    stamps = []
    for i in range(5):
        source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", views=i)]))
        assert run_cli("sync", "vault").returncode == 0
        entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
        stamps.append(helpers.latest_key(entry["views"]))

    assert stamps == sorted(stamps)
    assert len(set(stamps)) == len(stamps)


# Spec: Determinism | Sync timestamps | ... (a no-op sync appends nothing, so nothing advances)
def test_noop_sync_appends_no_timestamps(run_cli, vault, source, helpers, workdir):
    payload = helpers.make_payload(episodes=[helpers.make_source_entry("e1")])
    source.set(payload)
    assert run_cli("sync", "vault").returncode == 0
    first = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    assert run_cli("sync", "vault").returncode == 0
    second = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    for field in TRACKED:
        assert first[field] == second[field], field


# Spec: Determinism | Entry order | Newest `published` first; ties break by
#       lexicographically smaller `id` | (stable across repeated syncs)
def test_entry_order_is_stable_across_syncs(run_cli, vault, source, helpers, workdir):
    entries = [
        helpers.make_source_entry("b", published="2024-01-01T00:00:00"),
        helpers.make_source_entry("a", published="2024-01-01T00:00:00"),
        helpers.make_source_entry("c", published="2025-01-01T00:00:00"),
    ]
    source.set(helpers.make_payload(episodes=entries))
    assert run_cli("sync", "vault").returncode == 0
    order1 = [e["id"] for e in helpers.read_catalog(workdir)["episodes"]]
    source.set(helpers.make_payload(episodes=list(reversed(entries))))
    assert run_cli("sync", "vault").returncode == 0
    order2 = [e["id"] for e in helpers.read_catalog(workdir)["episodes"]]
    assert order1 == order2 == ["c", "a", "b"]


# Spec: Determinism | History interpretation | Chronological timestamp order |
def test_history_is_interpreted_chronologically_not_by_insertion(
    run_cli, vault, source, helpers, workdir
):
    import json
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", title="now")]))
    assert run_cli("sync", "vault").returncode == 0

    path = vault / "catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    catalog["episodes"][0]["title"]["2000-01-01T00:00:00"] = "ancient"
    path.write_text(json.dumps(catalog), encoding="utf-8")

    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1", title="now")]))
    assert run_cli("sync", "vault").returncode == 0
    entry = helpers.find_entry(helpers.read_catalog(workdir), "e1")
    # latest chronological value is still "now" -> unchanged -> no append
    assert len(entry["title"]) == 2


# Spec: Error Handling | `init` with existing vault directory | stderr | non-zero |
#       Required Detail: Message includes vault name
def test_error_init_existing_directory(run_cli, workdir):
    (workdir / "dup").mkdir()
    result = run_cli("init", "dup", "http://example.invalid/f.json")
    assert result.returncode != 0
    assert result.stderr.strip() != ""
    assert "dup" in result.stderr


# Spec: Error Handling | `sync` with non-existent vault | stderr | non-zero | includes name
def test_error_sync_non_existent_vault(run_cli):
    result = run_cli("sync", "nowhere")
    assert result.returncode != 0
    assert "nowhere" in result.stderr
    assert result.stdout == ""


# Spec: Error Handling | `sync` with invalid vault | stderr | non-zero | includes name
def test_error_sync_invalid_vault(run_cli, workdir):
    bad = workdir / "badvault"
    bad.mkdir()
    (bad / "catalog.json").write_text("[]", encoding="utf-8")
    result = run_cli("sync", "badvault")
    assert result.returncode != 0
    assert "badvault" in result.stderr


# Spec: Error Handling | No subcommand | stderr | non-zero | Usage text |
def test_error_no_subcommand(run_cli):
    result = run_cli()
    assert result.returncode != 0
    assert "usage" in result.stderr.lower()


# Spec: Error Handling | (unknown subcommand is not a valid invocation)
def test_error_unknown_subcommand(run_cli):
    result = run_cli("frobnicate")
    assert result.returncode != 0
    assert result.stderr.strip() != ""


# Spec: Error Handling | Source metadata fetch failure | stderr | non-zero |
#       Message includes `Source metadata fetch failure`
def test_error_fetch_failure_message_exact_phrase(run_cli, vault, source):
    source.set_raw("{oops")
    result = run_cli("sync", "vault")
    assert result.returncode != 0
    assert "Source metadata fetch failure" in result.stderr


# Spec: Error Handling: successful runs exit zero.
def test_success_exit_codes(run_cli, source, helpers, workdir):
    source.set(helpers.make_payload(episodes=[helpers.make_source_entry("e1")]))
    assert run_cli("init", "ok", source.url).returncode == 0
    assert run_cli("sync", "ok").returncode == 0
