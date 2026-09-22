#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata with tracked-field history."""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"
CATALOG_VERSION = 3
SUPPORTED_VERSIONS = (1, 2, 3)
LEGACY_VERSIONS = (1, 2)
CATEGORIES = ("episodes", "streams", "clips")

STATIC_FIELDS = ("id", "published", "width", "height")
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)
ANNOTATIONS_FIELD = "annotations"

DT_FORMAT = "%Y-%m-%dT%H:%M:%S"

# Version 1 vaults only store a short platform identifier; the full source URL
# is derived from it deterministically.
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/%s"


class MVaultError(Exception):
    """Base error for user-facing failures."""


class SourceError(MVaultError):
    """Source metadata fetch failure."""


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


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
_EPOCH_RE = re.compile(r"^\s*[+-]?\d+\s*$")


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


def epoch_key_to_iso(key):
    """Convert a UNIX-epoch-seconds string key to YYYY-MM-DDTHH:MM:SS in UTC.

    Returns None when the key is not a valid epoch-seconds string.
    """
    if not isinstance(key, str) or not _EPOCH_RE.match(key):
        return None
    try:
        seconds = int(key.strip())
    except ValueError:
        return None
    try:
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return format_dt(dt.replace(tzinfo=None))


def now_stamp():
    """Current wall-clock time as an ISO 8601 history key."""
    return format_dt(datetime.now().replace(microsecond=0))


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
        try:
            shutil.copyfile(path, backup_path(name))
        except OSError as exc:
            # The original catalog is left untouched: nothing has been written.
            raise MVaultError("vault %r: failed to write backup %s (%s)"
                              % (name, BACKUP_NAME, exc))
    data = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(data)


def read_catalog_file(name):
    """Read the raw catalog JSON for a vault without interpreting its version."""
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
    return catalog


def detect_version(name, catalog):
    """Return the declared catalog version, rejecting unusable declarations."""
    if "version" not in catalog:
        raise MVaultError("vault %r is invalid: %s is missing the 'version' field"
                          % (name, CATALOG_NAME))
    version = catalog["version"]
    if not _is_int(version):
        raise MVaultError("vault %r is invalid: catalog 'version' must be an "
                          "integer (got %r)" % (name, version))
    if version > CATALOG_VERSION:
        raise MVaultError("vault %r has unsupported catalog version %d: this build "
                          "supports catalog versions %s"
                          % (name, version,
                             ", ".join(str(v) for v in SUPPORTED_VERSIONS)))
    if version not in SUPPORTED_VERSIONS:
        raise MVaultError("vault %r has unsupported catalog version %d: this build "
                          "supports catalog versions %s"
                          % (name, version,
                             ", ".join(str(v) for v in SUPPORTED_VERSIONS)))
    return version


def validate_native_catalog(name, catalog):
    """Validate the shape of a native (version 3) catalog."""
    if not isinstance(catalog.get("source"), str):
        raise MVaultError("vault %r is invalid: missing source URL" % name)
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise MVaultError("vault %r is invalid: missing %r array" % (name, category))
    return catalog


# --------------------------------------------------------------------------
# legacy catalog migration (version 1 / version 2 -> version 3)
# --------------------------------------------------------------------------

_HISTORY_VALUE_KINDS = {
    "title": "string",
    "description": "string",
    "views": "integer",
    "likes": "integer or null",
    "preview": "string",
}


def _bad_entry(name, version, label, index, message):
    raise MVaultError("vault %r is invalid: version %d entry %s[%d] %s"
                      % (name, version, label, index, message))


def _value_ok(field, value):
    kind = _HISTORY_VALUE_KINDS[field]
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return _is_int(value)
    return value is None or _is_int(value)


def _migrate_history(name, version, label, index, field, history):
    """Validate a legacy history object and return it with ISO 8601 keys."""
    if not isinstance(history, dict):
        _bad_entry(name, version, label, index,
                   "field %r must be a history object" % field)
    converted = []
    for key, value in history.items():
        if not isinstance(key, str):
            _bad_entry(name, version, label, index,
                       "field %r has a non-string history key %r" % (field, key))
        if version == 1:
            iso = epoch_key_to_iso(key)
            if iso is None:
                _bad_entry(name, version, label, index,
                           "field %r has an invalid UNIX-epoch history key %r"
                           % (field, key))
            order = int(key.strip())
        else:
            parsed = parse_dt(key)
            if parsed is None:
                _bad_entry(name, version, label, index,
                           "field %r has an invalid ISO 8601 history key %r"
                           % (field, key))
            iso = key
            order = None
        if not _value_ok(field, value):
            _bad_entry(name, version, label, index,
                       "field %r has a history value %r that is not %s"
                       % (field, value, _HISTORY_VALUE_KINDS[field]))
        converted.append((order, iso, value))
    if version == 1:
        converted.sort(key=lambda item: item[0])
    return {iso: value for _, iso, value in converted}


def migrate_entry(name, version, label, index, entry, stamp):
    """Return a version 3 entry built from a validated legacy entry."""
    if not isinstance(entry, dict):
        _bad_entry(name, version, label, index, "is not an object")
    if not isinstance(entry.get("id"), str):
        _bad_entry(name, version, label, index, "is missing a string 'id'")
    if not isinstance(entry.get("published"), str):
        _bad_entry(name, version, label, index, "is missing a string 'published'")
    for field in ("width", "height"):
        if not _is_int(entry.get(field)):
            _bad_entry(name, version, label, index,
                       "is missing an integer %r" % field)
    for field in SOURCE_TRACKED_FIELDS:
        if field not in entry:
            _bad_entry(name, version, label, index, "is missing %r" % field)

    migrated = {
        "id": entry["id"],
        "published": entry["published"],
        "width": entry["width"],
        "height": entry["height"],
    }
    for field in SOURCE_TRACKED_FIELDS:
        migrated[field] = _migrate_history(
            name, version, label, index, field, entry[field])

    removed = entry.get("removed")
    if isinstance(removed, dict) and removed:
        migrated["removed"] = _migrate_removed(name, version, label, index, removed)
    else:
        migrated["removed"] = {stamp: False}

    annotations = entry.get(ANNOTATIONS_FIELD)
    migrated[ANNOTATIONS_FIELD] = annotations if isinstance(annotations, list) else []

    known = set(migrated)
    for key, value in entry.items():
        if key not in known:
            migrated[key] = value
    return migrated


def _migrate_removed(name, version, label, index, history):
    """Carry over a stray legacy 'removed' history, converting v1 keys."""
    converted = {}
    for key, value in history.items():
        if not isinstance(key, str):
            _bad_entry(name, version, label, index,
                       "field 'removed' has a non-string history key %r" % (key,))
        if version == 1:
            iso = epoch_key_to_iso(key)
            if iso is None:
                _bad_entry(name, version, label, index,
                           "field 'removed' has an invalid UNIX-epoch history "
                           "key %r" % (key,))
        else:
            if parse_dt(key) is None:
                _bad_entry(name, version, label, index,
                           "field 'removed' has an invalid ISO 8601 history "
                           "key %r" % (key,))
            iso = key
        if not isinstance(value, bool):
            _bad_entry(name, version, label, index,
                       "field 'removed' has a history value %r that is not a "
                       "boolean" % (value,))
        converted[iso] = value
    return converted


def migrate_catalog(name, catalog, version, stamp=None):
    """Build a version 3 catalog from a validated version 1 or 2 catalog."""
    if version not in LEGACY_VERSIONS:
        raise MVaultError("vault %r: nothing to migrate from catalog version %d"
                          % (name, version))
    if stamp is None:
        stamp = now_stamp()

    if version == 1:
        source_id = catalog.get("source_id")
        if not isinstance(source_id, str):
            raise MVaultError("vault %r is invalid: version 1 catalog is missing "
                              "'source_id'" % name)
        entries = catalog.get("entries")
        if not isinstance(entries, list):
            raise MVaultError("vault %r is invalid: version 1 catalog is missing "
                              "the 'entries' array" % name)
        source = V1_SOURCE_TEMPLATE % source_id
        groups = [("episodes", "entries", entries),
                  ("streams", "streams", []),
                  ("clips", "clips", [])]
    else:
        source = catalog.get("source")
        if not isinstance(source, str):
            raise MVaultError("vault %r is invalid: missing source URL" % name)
        groups = []
        for category in CATEGORIES:
            items = catalog.get(category)
            if not isinstance(items, list):
                raise MVaultError("vault %r is invalid: missing %r array"
                                  % (name, category))
            groups.append((category, category, items))

    migrated = {"version": CATALOG_VERSION, "source": source}
    for category, label, items in groups:
        migrated[category] = [
            migrate_entry(name, version, label, index, entry, stamp)
            for index, entry in enumerate(items)
        ]

    reserved = {"version", "source", "source_id", "entries"} | set(CATEGORIES)
    for key, value in catalog.items():
        if key not in reserved:
            migrated[key] = value
    return migrated


def load_catalog(name):
    """Load a vault catalog of any supported version as a version 3 catalog.

    Returns ``(catalog, version)`` where ``version`` is the version declared on
    disk. Legacy catalogs are migrated in memory only; nothing is written here.
    """
    raw = read_catalog_file(name)
    version = detect_version(name, raw)
    if version == CATALOG_VERSION:
        return validate_native_catalog(name, raw), version
    return migrate_catalog(name, raw, version), version


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


def cmd_migrate(name):
    raw = read_catalog_file(name)
    version = detect_version(name, raw)
    if version == CATALOG_VERSION:
        validate_native_catalog(name, raw)
        print("Vault %s already uses catalog version %d; nothing to migrate"
              % (name, CATALOG_VERSION))
        return 0
    migrated = migrate_catalog(name, raw, version)
    write_catalog(name, migrated)
    print("Migrated %s from catalog version %d to version %d"
          % (name, version, CATALOG_VERSION))
    return 0


def cmd_sync(name):
    catalog, version = load_catalog(name)
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
    # Writing backs up the pre-migration catalog that is still on disk.
    write_catalog(name, catalog)
    if version != CATALOG_VERSION:
        print("Migrated %s from catalog version %d to version %d"
              % (name, version, CATALOG_VERSION))
    print("Synced %s at %s: %d added, %d updated, %d removed, %d restored"
          % (name, stamp, added, updated, removed, restored))
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

COMMANDS = ("init", "sync", "migrate")


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

    migrate_parser = subparsers.add_parser(
        "migrate", help="convert a legacy vault catalog to the native format")
    migrate_parser.add_argument("name", help="vault directory name")

    return parser


def _usage_error(parser):
    parser.print_usage(sys.stderr)
    print("mvault: error: a subcommand is required (available: %s)"
          % ", ".join(COMMANDS), file=sys.stderr)
    return 2


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        return _usage_error(parser)
    args = parser.parse_args(argv)
    if not args.command:
        return _usage_error(parser)
    try:
        if args.command == "init":
            return cmd_init(args.name, args.url)
        if args.command == "sync":
            return cmd_sync(args.name)
        if args.command == "migrate":
            return cmd_migrate(args.name)
    except MVaultError as exc:
        print("mvault: error: %s" % exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print("mvault: error: %s" % exc, file=sys.stderr)
        return 1
    return _usage_error(parser)


if __name__ == "__main__":
    sys.exit(main())
