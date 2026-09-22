#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata with tracked-field history."""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"
CATALOG_VERSION = 3
CATEGORIES = ("episodes", "streams", "clips")

STATIC_FIELDS = ("id", "published", "width", "height")
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)

DT_FORMAT = "%Y-%m-%dT%H:%M:%S"


class MVaultError(Exception):
    """Base error for user-facing failures."""


class SourceError(MVaultError):
    """Source metadata fetch failure."""


# --------------------------------------------------------------------------
# datetime helpers (locale independent)
# --------------------------------------------------------------------------

_DATE_ONLY_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")
_DATETIME_RE = re.compile(
    r"^\s*(\d{4})-(\d{2})-(\d{2})"          # date
    r"[Tt ]"                                 # separator
    r"(\d{2}):(\d{2})"                       # hh:mm
    r"(?::(\d{2}))?"                         # optional :ss
    r"(?:[.,](\d+))?"                        # optional fractional seconds
    r"\s*(Z|z|[+-]\d{2}:?\d{2})?\s*$"        # optional timezone
)


def format_dt(dt):
    """Render a datetime as YYYY-MM-DDTHH:MM:SS with no timezone suffix."""
    return "%04d-%02d-%02dT%02d:%02d:%02d" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second
    )


def parse_dt(text):
    """Parse ISO 8601 datetime / date-only text into a naive datetime.

    Timezone suffixes are dropped (wall-clock components are kept).
    Returns None when the text cannot be understood.
    """
    if not isinstance(text, str):
        return None
    m = _DATE_ONLY_RE.match(text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _DATETIME_RE.match(text)
    if m:
        year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
        second = int(m.group(6) or 0)
        try:
            return datetime(year, month, day, hour, minute, second)
        except ValueError:
            return None
    return None


def normalize_published(text):
    """Normalize a published value to YYYY-MM-DDTHH:MM:SS when possible."""
    dt = parse_dt(text)
    if dt is None:
        return text
    return format_dt(dt)


# --------------------------------------------------------------------------
# vault helpers
# --------------------------------------------------------------------------

def catalog_path(name):
    return os.path.join(name, CATALOG_NAME)


def backup_path(name):
    return os.path.join(name, BACKUP_NAME)


def write_catalog(name, catalog):
    """Write the catalog, backing up any pre-existing catalog byte-for-byte."""
    path = catalog_path(name)
    if os.path.isfile(path):
        shutil.copyfile(path, backup_path(name))
    data = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(data)


def load_catalog(name):
    """Load and validate an existing vault's catalog."""
    if not os.path.isdir(name):
        raise MVaultError("vault %r does not exist" % name)
    path = catalog_path(name)
    if not os.path.isfile(path):
        raise MVaultError("vault %r is invalid: missing %s" % (name, CATALOG_NAME))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            catalog = json.load(handle)
    except (OSError, ValueError) as exc:
        raise MVaultError("vault %r is invalid: unreadable %s (%s)"
                          % (name, CATALOG_NAME, exc))
    if not isinstance(catalog, dict):
        raise MVaultError("vault %r is invalid: catalog root must be an object" % name)
    if not isinstance(catalog.get("source"), str):
        raise MVaultError("vault %r is invalid: missing source URL" % name)
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise MVaultError("vault %r is invalid: missing %r array" % (name, category))
    catalog.setdefault("version", CATALOG_VERSION)
    return catalog


# --------------------------------------------------------------------------
# source fetching / validation
# --------------------------------------------------------------------------

def _fetch_with_requests(url):
    import requests  # noqa: F401  (optional dependency)

    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def _fetch_with_urllib(url):
    import urllib.request

    with urllib.request.urlopen(url, timeout=60) as response:
        raw = response.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def fetch_source(url):
    """GET the source URL and return the decoded JSON payload."""
    errors = []
    for fetcher in (_fetch_with_requests, _fetch_with_urllib):
        try:
            return fetcher(url)
        except Exception as exc:  # noqa: BLE001 - any failure falls through
            errors.append("%s: %s" % (type(exc).__name__, exc))
    raise SourceError("failed to fetch source metadata from %s (%s)"
                      % (url, "; ".join(errors)))


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def validate_source(payload, url):
    """Validate the source payload shape and every entry's nine fields."""
    if not isinstance(payload, dict):
        raise SourceError("source metadata from %s is not a JSON object" % url)
    categorized = {}
    for category in CATEGORIES:
        items = payload.get(category)
        if not isinstance(items, list):
            raise SourceError("source metadata from %s is missing the %r array"
                              % (url, category))
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise SourceError("source metadata from %s: %s[%d] is not an object"
                                  % (url, category, index))
            for field in ("id", "published", "title", "description", "preview"):
                if field not in item:
                    raise SourceError("source metadata from %s: %s[%d] is missing %r"
                                      % (url, category, index, field))
                if not isinstance(item[field], str):
                    raise SourceError("source metadata from %s: %s[%d] field %r must "
                                      "be a string" % (url, category, index, field))
            for field in ("width", "height", "views"):
                if field not in item:
                    raise SourceError("source metadata from %s: %s[%d] is missing %r"
                                      % (url, category, index, field))
                if not _is_int(item[field]):
                    raise SourceError("source metadata from %s: %s[%d] field %r must "
                                      "be an integer" % (url, category, index, field))
            if "likes" not in item:
                raise SourceError("source metadata from %s: %s[%d] is missing 'likes'"
                                  % (url, category, index))
            if item["likes"] is not None and not _is_int(item["likes"]):
                raise SourceError("source metadata from %s: %s[%d] field 'likes' must "
                                  "be an integer or null" % (url, category, index))
        categorized[category] = items
    return categorized


# --------------------------------------------------------------------------
# history helpers
# --------------------------------------------------------------------------

def history_current(history):
    """Return the value stored at the latest timestamp key, chronologically."""
    if not isinstance(history, dict) or not history:
        return None, False
    best_key = None
    best_dt = None
    for key in history:
        dt = parse_dt(key)
        if dt is None:
            continue
        if best_dt is None or dt > best_dt or (dt == best_dt and key > best_key):
            best_dt, best_key = dt, key
    if best_key is None:
        best_key = max(history)
    return history[best_key], True


def latest_history_dt(catalog):
    """Newest timestamp key present anywhere in the catalog."""
    newest = None
    for category in CATEGORIES:
        for entry in catalog.get(category, []):
            if not isinstance(entry, dict):
                continue
            for field in TRACKED_FIELDS:
                history = entry.get(field)
                if not isinstance(history, dict):
                    continue
                for key in history:
                    dt = parse_dt(key)
                    if dt is not None and (newest is None or dt > newest):
                        newest = dt
    return newest


def values_equal(left, right):
    """Compare tracked values, keeping null distinct from numbers/strings."""
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if type(left) is not type(right) and not (
        _is_int(left) and _is_int(right)
    ):
        return False
    return left == right


def record(entry, field, value, stamp):
    """Append a history entry for `field` when the value actually changed."""
    history = entry.get(field)
    if not isinstance(history, dict):
        history = {}
        entry[field] = history
    current, present = history_current(history)
    if present and values_equal(current, value):
        return False
    history[stamp] = value
    return True


def sort_entries(entries):
    """Newest published first; lexicographically smaller id first on ties."""
    def published_key(entry):
        value = entry.get("published")
        dt = parse_dt(value) if isinstance(value, str) else None
        if dt is not None:
            return (1, format_dt(dt))
        return (0, value if isinstance(value, str) else "")

    ordered = sorted(entries, key=lambda e: e.get("id") or "")
    ordered.sort(key=published_key, reverse=True)
    return ordered


def new_entry(item):
    return {
        "id": item["id"],
        "published": normalize_published(item["published"]),
        "width": item["width"],
        "height": item["height"],
    }


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_init(name, url):
    if os.path.exists(name):
        raise MVaultError("vault %r already exists" % name)
    catalog = {
        "version": CATALOG_VERSION,
        "source": url,
        "episodes": [],
        "streams": [],
        "clips": [],
    }
    os.makedirs(name)
    write_catalog(name, catalog)
    print("Initialized vault %s from %s" % (name, url))
    return 0


def cmd_sync(name):
    catalog = load_catalog(name)
    url = catalog["source"]
    payload = fetch_source(url)
    source = validate_source(payload, url)

    stamp_dt = datetime.now().replace(microsecond=0)
    newest = latest_history_dt(catalog)
    if newest is not None and stamp_dt <= newest:
        stamp_dt = newest.replace(microsecond=0) + timedelta(seconds=1)
    stamp = format_dt(stamp_dt)

    added = updated = removed = restored = 0

    for category in CATEGORIES:
        entries = [e for e in catalog.get(category, []) if isinstance(e, dict)]
        by_id = {}
        for entry in entries:
            by_id.setdefault(entry.get("id"), entry)

        seen = set()
        for item in source[category]:
            item_id = item["id"]
            seen.add(item_id)
            entry = by_id.get(item_id)
            if entry is None:
                entry = new_entry(item)
                entries.append(entry)
                by_id[item_id] = entry
                for field in SOURCE_TRACKED_FIELDS:
                    entry[field] = {stamp: item[field]}
                entry["removed"] = {stamp: False}
                added += 1
                continue

            entry["published"] = normalize_published(item["published"])
            entry["width"] = item["width"]
            entry["height"] = item["height"]

            changed = False
            for field in SOURCE_TRACKED_FIELDS:
                if record(entry, field, item[field], stamp):
                    changed = True
            was_removed, present = history_current(entry.get("removed"))
            if record(entry, "removed", False, stamp):
                if present and was_removed is True:
                    restored += 1
                changed = True
            if changed:
                updated += 1

        for entry in entries:
            if entry.get("id") in seen:
                continue
            if record(entry, "removed", True, stamp):
                removed += 1

        catalog[category] = sort_entries(entries)

    catalog["version"] = CATALOG_VERSION
    write_catalog(name, catalog)
    print("Synced %s at %s: %d added, %d updated, %d removed, %d restored"
          % (name, stamp, added, updated, removed, restored))
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="mvault",
        description="Create local vaults for media-platform metadata and record "
                    "tracked-field history by sync timestamp.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<subcommand>")

    init_parser = subparsers.add_parser(
        "init", help="create a new vault directory with an empty catalog")
    init_parser.add_argument("name", help="vault directory name")
    init_parser.add_argument("url", help="source metadata URL")

    sync_parser = subparsers.add_parser(
        "sync", help="fetch the source and update the vault catalog")
    sync_parser.add_argument("name", help="vault directory name")

    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        parser.print_usage(sys.stderr)
        print("mvault: error: a subcommand is required "
              "(available: init, sync)", file=sys.stderr)
        return 2
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_usage(sys.stderr)
        print("mvault: error: a subcommand is required "
              "(available: init, sync)", file=sys.stderr)
        return 2
    try:
        if args.command == "init":
            return cmd_init(args.name, args.url)
        if args.command == "sync":
            return cmd_sync(args.name)
    except MVaultError as exc:
        print("mvault: error: %s" % exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print("mvault: error: %s" % exc, file=sys.stderr)
        return 1
    parser.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
