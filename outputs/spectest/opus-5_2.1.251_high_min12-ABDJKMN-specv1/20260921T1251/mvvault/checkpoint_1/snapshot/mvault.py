#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Creates a vault directory holding a ``catalog.json`` and records the history of
tracked fields (``title``, ``description``, ``views``, ``likes``, ``preview``
and the local-only ``removed``) keyed by sync timestamp.

Usage::

    python mvault.py init <name> <url>
    python mvault.py sync <name>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

CATALOG_VERSION = 3
CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"

CATEGORIES = ("episodes", "streams", "clips")
STATIC_FIELDS = ("id", "published", "width", "height")
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)

FETCH_FAILURE = "Source metadata fetch failure"

DATE_ONLY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
DATETIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?")

_MISSING = object()


class MvaultError(Exception):
    """A user-facing error; the message is printed to stderr."""


class FetchFailure(MvaultError):
    """Source metadata could not be fetched or is malformed."""

    def __init__(self, detail):
        super().__init__(f"{FETCH_FAILURE}: {detail}")


# --------------------------------------------------------------------------
# datetime helpers - all text is `YYYY-MM-DDTHH:MM:SS`, no timezone suffix
# --------------------------------------------------------------------------

def format_datetime(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def parse_datetime(text):
    """Parse canonical datetime text; return ``None`` when unparseable."""
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None


def normalize_published(text):
    """Normalize a source ``published`` value to canonical datetime text.

    Date-only values gain a ``00:00:00`` time component; timezone suffixes and
    fractional seconds are dropped. Text that is not recognizably ISO 8601 is
    kept verbatim (the schema only requires it to be a string).
    """
    value = text.strip()
    if DATE_ONLY_RE.match(value):
        return f"{value}T00:00:00"
    match = DATETIME_RE.match(value)
    if match:
        date, hour, minute, second = match.groups()
        return f"{date}T{hour}:{minute}:{second or '00'}"
    return text


# --------------------------------------------------------------------------
# type helpers - JSON types, so booleans are never integers
# --------------------------------------------------------------------------

def is_integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_string(value):
    return isinstance(value, str)


def values_equal(left, right):
    """Compare two tracked values; ``null`` is an ordinary value."""
    if left is _MISSING or right is _MISSING:
        return False
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


# --------------------------------------------------------------------------
# history helpers
# --------------------------------------------------------------------------

def latest_key(history):
    """Latest datetime key, in chronological order (file key order is ignored)."""
    if not isinstance(history, dict) or not history:
        return None
    return sorted(history)[-1]


def current_value(entry, field):
    history = entry.get(field)
    key = latest_key(history)
    if key is None:
        return _MISSING
    return history[key]


def append_history(entry, field, stamp, value):
    history = entry.get(field)
    if not isinstance(history, dict):
        history = {}
        entry[field] = history
    history[stamp] = value


# --------------------------------------------------------------------------
# catalog i/o
# --------------------------------------------------------------------------

def catalog_path(vault_dir):
    return Path(vault_dir) / CATALOG_NAME


def backup_path(vault_dir):
    return Path(vault_dir) / BACKUP_NAME


def serialize_catalog(catalog):
    return json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"


def write_catalog(vault_dir, catalog):
    """Write the catalog, backing up any existing catalog first."""
    path = catalog_path(vault_dir)
    if path.exists():
        shutil.copyfile(path, backup_path(vault_dir))

    text = serialize_catalog(catalog)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_vault(name):
    """Load and validate the vault named ``name``."""
    vault_dir = Path(name)
    if not vault_dir.is_dir():
        raise MvaultError(f"vault {name!r} does not exist")

    path = catalog_path(vault_dir)
    if not path.is_file():
        raise MvaultError(f"vault {name!r} is invalid: missing {CATALOG_NAME}")

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MvaultError(f"vault {name!r} is invalid: cannot read {CATALOG_NAME}: {exc}")

    try:
        catalog = json.loads(raw)
    except ValueError as exc:
        raise MvaultError(f"vault {name!r} is invalid: {CATALOG_NAME} is not valid JSON: {exc}")

    problem = validate_catalog(catalog)
    if problem is not None:
        raise MvaultError(f"vault {name!r} is invalid: {problem}")

    return vault_dir, catalog


def validate_catalog(catalog):
    """Return a problem description, or ``None`` when the catalog is valid."""
    if not isinstance(catalog, dict):
        return f"{CATALOG_NAME} must contain a JSON object"
    if "version" not in catalog:
        return "missing 'version'"
    if catalog["version"] != CATALOG_VERSION or not is_integer(catalog["version"]):
        return f"unsupported version {catalog['version']!r} (expected {CATALOG_VERSION})"
    if not is_string(catalog.get("source")):
        return "missing or non-string 'source'"
    for category in CATEGORIES:
        if category not in catalog:
            return f"missing '{category}'"
        if not isinstance(catalog[category], list):
            return f"'{category}' must be an array"
        for entry in catalog[category]:
            if not isinstance(entry, dict):
                return f"'{category}' contains a non-object entry"
            if not is_string(entry.get("id")):
                return f"'{category}' contains an entry without a string 'id'"
    return None


# --------------------------------------------------------------------------
# source fetching and validation
# --------------------------------------------------------------------------

def fetch_source(url):
    """HTTP GET the source URL and return the validated payload."""
    try:
        response = urllib.request.urlopen(url)
    except urllib.error.HTTPError as exc:
        raise FetchFailure(f"HTTP {exc.code} from {url}")
    except Exception as exc:  # URLError, socket errors, bad URL, ...
        raise FetchFailure(f"could not fetch {url}: {exc}")

    try:
        raw = response.read()
    except Exception as exc:
        raise FetchFailure(f"could not read response from {url}: {exc}")
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FetchFailure(f"response from {url} is not valid UTF-8: {exc}")

    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise FetchFailure(f"response from {url} is not valid JSON: {exc}")

    validate_source_payload(payload)
    return payload


def validate_source_payload(payload):
    if not isinstance(payload, dict):
        raise FetchFailure("source response must be a JSON object")
    for category in CATEGORIES:
        if category not in payload:
            raise FetchFailure(f"source response is missing '{category}'")
        if not isinstance(payload[category], list):
            raise FetchFailure(f"source '{category}' must be an array")
        for index, entry in enumerate(payload[category]):
            validate_source_entry(entry, category, index)


def validate_source_entry(entry, category, index):
    where = f"{category}[{index}]"
    if not isinstance(entry, dict):
        raise FetchFailure(f"source entry {where} must be a JSON object")

    checks = (
        ("id", is_string, "string"),
        ("published", is_string, "string"),
        ("width", is_integer, "integer"),
        ("height", is_integer, "integer"),
        ("title", is_string, "string"),
        ("description", is_string, "string"),
        ("views", is_integer, "integer"),
        ("likes", lambda v: v is None or is_integer(v), "integer or null"),
        ("preview", is_string, "string"),
    )
    for field, check, expected in checks:
        if field not in entry:
            raise FetchFailure(f"source entry {where} is missing '{field}'")
        if not check(entry[field]):
            raise FetchFailure(
                f"source entry {where} field '{field}' must be {expected}, "
                f"got {type(entry[field]).__name__}"
            )


# --------------------------------------------------------------------------
# sync timestamp
# --------------------------------------------------------------------------

def newest_history_key(catalog):
    newest = None
    for category in CATEGORIES:
        for entry in catalog.get(category, []):
            for field in TRACKED_FIELDS:
                history = entry.get(field)
                if isinstance(history, dict):
                    for key in history:
                        if isinstance(key, str) and (newest is None or key > newest):
                            newest = key
    return newest


def next_sync_timestamp(catalog, now=None):
    """Sync timestamp: execution time, advanced past any existing key."""
    moment = (now or datetime.now()).replace(microsecond=0)
    stamp = format_datetime(moment)

    newest = newest_history_key(catalog)
    if newest is not None and stamp <= newest:
        parsed = parse_datetime(newest)
        if parsed is not None:
            stamp = format_datetime(parsed + timedelta(seconds=1))
        else:
            stamp = format_datetime(moment + timedelta(seconds=1))
    return stamp


# --------------------------------------------------------------------------
# sync
# --------------------------------------------------------------------------

def new_entry(source_entry, stamp):
    entry = {
        "id": source_entry["id"],
        "published": normalize_published(source_entry["published"]),
        "width": source_entry["width"],
        "height": source_entry["height"],
    }
    for field in SOURCE_TRACKED_FIELDS:
        entry[field] = {stamp: source_entry[field]}
    entry["removed"] = {stamp: False}
    return entry


def update_entry(entry, source_entry, stamp):
    """Append history for changed tracked values. Returns True if anything changed."""
    changed = False
    for field in SOURCE_TRACKED_FIELDS:
        value = source_entry[field]
        if not values_equal(current_value(entry, field), value):
            append_history(entry, field, stamp, value)
            changed = True
    if current_value(entry, "removed") is not False:
        append_history(entry, "removed", stamp, False)
        changed = True
    return changed


def mark_removed(entry, stamp):
    if current_value(entry, "removed") is True:
        return False
    append_history(entry, "removed", stamp, True)
    return True


def sort_entries(entries):
    """Newest `published` first; ties break by lexicographically smaller `id`."""
    entries.sort(key=lambda entry: str(entry.get("id", "")))
    entries.sort(key=lambda entry: str(entry.get("published", "")), reverse=True)
    return entries


def apply_source(catalog, payload, stamp):
    counts = {"new": 0, "changed": 0, "removed": 0, "restored": 0}

    for category in CATEGORIES:
        entries = catalog[category]
        by_id = {}
        for entry in entries:
            by_id[entry["id"]] = entry

        source_by_id = {}
        for source_entry in payload[category]:
            source_by_id[source_entry["id"]] = source_entry

        for entry_id, source_entry in source_by_id.items():
            existing = by_id.get(entry_id)
            if existing is None:
                entries.append(new_entry(source_entry, stamp))
                counts["new"] += 1
                continue
            was_removed = current_value(existing, "removed") is True
            if update_entry(existing, source_entry, stamp):
                counts["restored" if was_removed else "changed"] += 1

        for entry in entries:
            if entry["id"] not in source_by_id and mark_removed(entry, stamp):
                counts["removed"] += 1

        sort_entries(entries)

    return counts


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_init(args):
    name = args.name
    vault_dir = Path(name)
    if vault_dir.exists():
        raise MvaultError(f"vault {name!r} already exists")

    try:
        vault_dir.mkdir(parents=True)
    except OSError as exc:
        raise MvaultError(f"vault {name!r} could not be created: {exc}")

    catalog = {
        "version": CATALOG_VERSION,
        "source": args.url,
        "episodes": [],
        "streams": [],
        "clips": [],
    }
    write_catalog(vault_dir, catalog)
    print(f"Initialized vault {name!r} at {catalog_path(vault_dir)}")
    return 0


def cmd_sync(args):
    name = args.name
    vault_dir, catalog = load_vault(name)

    payload = fetch_source(catalog["source"])

    stamp = next_sync_timestamp(catalog)
    counts = apply_source(catalog, payload, stamp)
    write_catalog(vault_dir, catalog)

    print(
        f"Synced vault {name!r} at {stamp}: "
        f"{counts['new']} new, {counts['changed']} changed, "
        f"{counts['removed']} removed, {counts['restored']} restored"
    )
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mvault.py",
        description="Create local vaults for media-platform metadata and "
                    "record tracked-field history by sync timestamp.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="{init,sync}")

    init_parser = subparsers.add_parser(
        "init", help="create a new vault with an empty catalog")
    init_parser.add_argument("name", help="vault directory to create")
    init_parser.add_argument("url", help="source URL for the vault")
    init_parser.set_defaults(func=cmd_init)

    sync_parser = subparsers.add_parser(
        "sync", help="fetch the source and update the vault catalog")
    sync_parser.add_argument("name", help="existing vault directory")
    sync_parser.set_defaults(func=cmd_sync)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "func", None) is None:
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: a subcommand is required "
              f"(choose from init, sync)", file=sys.stderr)
        return 2

    try:
        return args.func(args)
    except MvaultError as exc:
        print(f"{parser.prog}: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
