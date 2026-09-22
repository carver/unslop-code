"""`mvault` Determinism rules."""

import re
import subprocess
import sys
from datetime import datetime

from conftest import MVAULT, read_catalog, source_entry

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
