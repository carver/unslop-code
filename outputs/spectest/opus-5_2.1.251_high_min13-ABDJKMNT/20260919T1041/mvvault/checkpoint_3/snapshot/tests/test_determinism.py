"""`mvault` Determinism rules."""

import re
import subprocess
import sys
from datetime import datetime

from conftest import (
    MVAULT,
    V1_SOURCE_URL,
    read_catalog,
    source_entry,
    stored_names,
    v1_catalog,
    v1_entry,
    v3_catalog,
    v3_entry,
)

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
TRACKED = ["title", "description", "views", "likes", "preview", "removed"]


def sync(run_cli, source, episodes=()):
    source.payload = {"episodes": list(episodes), "streams": [], "clips": []}
    result = run_cli("sync", "v")
    assert result.returncode == 0, result.stderr


def all_keys(vault):
    return [key for entry in read_catalog(vault)["episodes"] for field in TRACKED for key in entry[field]]


# Spec: Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix
def test_history_keys_use_the_required_datetime_text(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a")])
    assert all(ISO.match(key) for key in all_keys(vault))


# Spec: Datetime text | `YYYY-MM-DDTHH:MM:SS` without timezone suffix (stored `published`)
def test_published_uses_the_required_datetime_text(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a", published="2024-04-05T06:07:08Z")])
    assert read_catalog(vault)["episodes"][0]["published"] == "2024-04-05T06:07:08"


# Spec: Date-only source values | Normalize to `00:00:00` time component
def test_date_only_published_is_normalized(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a", published="2024-04-05")])
    assert read_catalog(vault)["episodes"][0]["published"] == "2024-04-05T00:00:00"


# Spec: Datetime text ... (fractional seconds are truncated, AMBIGUITIES T2)
def test_fractional_seconds_are_truncated(run_cli, vault, source):
    sync(run_cli, source, episodes=[source_entry("a", published="2024-04-05T06:07:08.912345")])
    assert read_catalog(vault)["episodes"][0]["published"] == "2024-04-05T06:07:08"


# Spec: Sync timestamps | Reflect sync execution time
def test_sync_timestamp_is_close_to_execution_time(run_cli, vault, source):
    before = datetime.now().replace(microsecond=0)
    sync(run_cli, source, episodes=[source_entry("a")])
    stamp = datetime.strptime(max(all_keys(vault)), "%Y-%m-%dT%H:%M:%S")
    assert 0 <= (stamp - before).total_seconds() < 120


# Spec: Sync timestamps | ... remain strictly increasing whenever new history
# entries are appended
def test_sync_timestamps_strictly_increase_across_runs(run_cli, vault, source):
    stamps = []
    for views in (1, 2, 3):
        sync(run_cli, source, episodes=[source_entry("a", views=views)])
        stamps.append(max(all_keys(vault)))
    assert stamps == sorted(stamps) and len(set(stamps)) == 3


# Spec: History interpretation | Chronological timestamp order (keys sort as text)
def test_keys_sort_chronologically_as_text(run_cli, vault, source):
    for views in (1, 2, 3):
        sync(run_cli, source, episodes=[source_entry("a", views=views)])
    history = read_catalog(vault)["episodes"][0]["views"]
    ordered = sorted(history, key=lambda key: datetime.strptime(key, "%Y-%m-%dT%H:%M:%S"))
    assert list(sorted(history)) == ordered
    assert [history[key] for key in ordered] == [1, 2, 3]


# Spec: Locale | No locale-sensitive formatting anywhere
def test_output_is_locale_independent(run_cli, vault, source, tmp_path):
    source.payload = {"episodes": [source_entry("a", published="2024-12-31")], "streams": [], "clips": []}
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "de_DE.UTF-8", "LANG": "de_DE.UTF-8"}
    result = subprocess.run(
        [sys.executable, str(MVAULT), "sync", "v"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    catalog = read_catalog(vault)
    assert catalog["episodes"][0]["published"] == "2024-12-31T00:00:00"
    assert all(ISO.match(key) for key in all_keys(vault))


# --- Determinism rules covering `digest` and the download phase ---

DIGEST_T1 = "2024-01-01T00:00:00"
DIGEST_T2 = "2024-02-01T00:00:00"


def mixed_v3_catalog():
    """A catalog holding one addition, one removal and one update per category."""
    entries = [
        v3_entry("new", published="2024-05-01T00:00:00"),
        v3_entry("gone", published="2024-04-01T00:00:00", removed={DIGEST_T1: False, DIGEST_T2: True}),
        v3_entry("changed", published="2024-03-01T00:00:00", views={DIGEST_T1: 1, DIGEST_T2: 2}),
    ]
    return v3_catalog("http://source.invalid/feed.json", episodes=entries, streams=entries, clips=entries)


def digest_body(run_cli):
    """The digest output without its trailing run-metadata line."""
    result = run_cli("digest", "v")
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()[:-1]


# Spec: Digest category order | Deterministic
# Spec: Digest group order | Deterministic
# Spec: Digest entry order | Deterministic
def test_digest_output_is_stable_across_runs(run_cli, make_vault):
    make_vault(mixed_v3_catalog())
    assert digest_body(run_cli) == digest_body(run_cli)


# Spec: Digest category order | Deterministic
def test_digest_categories_follow_the_catalog_order(run_cli, make_vault):
    make_vault(mixed_v3_catalog())
    headers = [line for line in digest_body(run_cli) if line and not line.startswith(" ")]
    assert headers == ["Episodes", "Streams", "Clips"]


# Spec: Digest group order | Deterministic
def test_digest_groups_follow_the_precedence_order(run_cli, make_vault):
    make_vault(mixed_v3_catalog())
    groups = [line.strip() for line in digest_body(run_cli) if line.startswith("  ") and line.endswith(":")]
    assert groups[:3] == ["Removed:", "Added:", "Updated:"]


# Spec: Digest trailing line | Deterministic format
def test_digest_trailing_line_has_a_stable_shape(run_cli, make_vault):
    make_vault(v1_catalog([v1_entry("a")]))
    trailing = run_cli("digest", "v").stdout.splitlines()[-1]
    assert V1_SOURCE_URL in trailing
    assert any(ISO.match(word) for word in trailing.split())


# Spec: v1 history ordering in digest | Numeric comparison of epoch-second strings
def test_digest_orders_v1_history_numerically(run_cli, make_vault):
    make_vault(v1_catalog([v1_entry("a", title={"999999999": "older", "1000000000": "newest"})]))
    assert "newest" in run_cli("digest", "v").stdout


# Spec: Wall-clock usage outside digest trailing line | Not part of file naming or
# vault content
def test_downloaded_file_names_carry_no_timestamp(run_cli, vault, source):
    source.payload = {"episodes": [source_entry("a")], "streams": [], "clips": []}
    assert run_cli("sync", "v").returncode == 0
    assert stored_names(vault / "media") == ["a.mp4"]
    assert stored_names(vault / "previews") == ["a.mp4"]
