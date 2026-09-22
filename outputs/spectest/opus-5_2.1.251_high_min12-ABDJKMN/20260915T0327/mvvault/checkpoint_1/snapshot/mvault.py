#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Creates local vaults for media-platform metadata and records tracked-field
history by sync timestamp.

Usage:
    python mvault.py init <name> <url>
    python mvault.py sync <name>
"""
import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

CATALOG_VERSION = 3
CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"
CATEGORIES = ("episodes", "streams", "clips")
TRACKED_FIELDS = ("title", "description", "views", "likes", "preview", "removed")
STATIC_FIELDS = ("id", "published", "width", "height")
DT_FORMAT = "%Y-%m-%dT%H:%M:%S"
FETCH_TIMEOUT = 30


class VaultError(Exception):
    """A vault is missing, invalid, or already exists."""


class SourceError(Exception):
    """Source metadata could not be fetched or is malformed."""


# --------------------------------------------------------------------------
# datetime helpers
# --------------------------------------------------------------------------

def is_int(value):
    """JSON integer: booleans are not integers even though bool subclasses int."""
    return isinstance(value, int) and not isinstance(value, bool)


def format_dt(moment):
    return moment.strftime(DT_FORMAT)


def parse_dt(text):
    """Parse an ISO 8601 datetime/date string, or return None."""
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    if not candidate:
        return None
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1]
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    # The stored text never carries a timezone suffix.
    return parsed.replace(tzinfo=None, microsecond=0)


def normalize_published(text):
    """Normalize source `published` text to YYYY-MM-DDTHH:MM:SS.

    Date-only values gain a 00:00:00 time component; timezone suffixes are
    dropped. Text that is not ISO 8601 is kept verbatim.
    """
    parsed = parse_dt(text)
    if parsed is None:
        return text
    return format_dt(parsed)


def history_sort_key(key):
    """Chronological order for a history key, tolerating odd text."""
    parsed = parse_dt(key)
    if parsed is None:
        return (1, datetime.min, key)
    return (0, parsed, key)


def latest_key(history):
    if not history:
        return None
    return max(history, key=history_sort_key)


def current_value(history):
    key = latest_key(history)
    return None if key is None else history[key]


# --------------------------------------------------------------------------
# source fetching / validation
# --------------------------------------------------------------------------

def fetch_source(url):
    """HTTP GET the source URL and return the parsed JSON object."""
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise SourceError("HTTP %s from %s" % (exc.code, url))
    except Exception as exc:  # network failures, bad URLs, timeouts
        raise SourceError("could not fetch %s: %s" % (url, exc))

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise SourceError("invalid JSON from %s: %s" % (url, exc))

    if not isinstance(data, dict):
        raise SourceError("source response from %s is not a JSON object" % url)

    result = {}
    for category in CATEGORIES:
        if category not in data:
            raise SourceError("source response is missing '%s'" % category)
        items = data[category]
        if not isinstance(items, list):
            raise SourceError("source field '%s' is not an array" % category)
        result[category] = [validate_source_entry(item, category) for item in items]
    return result


def validate_source_entry(item, category):
    """Check the nine required fields and their types."""
    if not isinstance(item, dict):
        raise SourceError("source entry in '%s' is not an object" % category)

    checks = (
        ("id", lambda v: isinstance(v, str), "string"),
        ("published", lambda v: isinstance(v, str), "string"),
        ("width", is_int, "integer"),
        ("height", is_int, "integer"),
        ("title", lambda v: isinstance(v, str), "string"),
        ("description", lambda v: isinstance(v, str), "string"),
        ("views", is_int, "integer"),
        ("likes", lambda v: v is None or is_int(v), "integer or null"),
        ("preview", lambda v: isinstance(v, str), "string"),
    )
    for field, check, expected in checks:
        if field not in item:
            raise SourceError(
                "source entry in '%s' is missing required field '%s'"
                % (category, field)
            )
        if not check(item[field]):
            raise SourceError(
                "source entry '%s' in '%s' has wrong type for '%s' (expected %s)"
                % (item.get("id"), category, field, expected)
            )
    return item


# --------------------------------------------------------------------------
# catalog load / validate / save
# --------------------------------------------------------------------------

def catalog_path(vault_dir):
    return os.path.join(vault_dir, CATALOG_NAME)


def backup_path(vault_dir):
    return os.path.join(vault_dir, BACKUP_NAME)


def load_catalog(name):
    """Load and validate the catalog of an existing vault."""
    vault_dir = name
    if not os.path.isdir(vault_dir):
        raise VaultError("vault '%s' does not exist" % name)
    path = catalog_path(vault_dir)
    if not os.path.isfile(path):
        raise VaultError("vault '%s' is invalid: missing %s" % (name, CATALOG_NAME))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            catalog = json.load(handle)
    except Exception as exc:
        raise VaultError("vault '%s' is invalid: unreadable %s (%s)"
                         % (name, CATALOG_NAME, exc))

    if not isinstance(catalog, dict):
        raise VaultError("vault '%s' is invalid: catalog is not an object" % name)
    if not is_int(catalog.get("version")) or catalog.get("version") != CATALOG_VERSION:
        raise VaultError(
            "vault '%s' is invalid: version must be %d" % (name, CATALOG_VERSION)
        )
    if not isinstance(catalog.get("source"), str):
        raise VaultError("vault '%s' is invalid: missing source URL" % name)
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise VaultError(
                "vault '%s' is invalid: '%s' must be an array" % (name, category)
            )
    return catalog


def save_catalog(name, catalog):
    """Back up the existing catalog, then write the new one."""
    vault_dir = name
    path = catalog_path(vault_dir)
    if os.path.exists(path):
        shutil.copyfile(path, backup_path(vault_dir))
    text = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


# --------------------------------------------------------------------------
# sync logic
# --------------------------------------------------------------------------

def sync_timestamp(catalog):
    """A sync timestamp that is strictly newer than every recorded key."""
    moment = datetime.now().replace(microsecond=0)
    newest = None
    for category in CATEGORIES:
        for stored in catalog.get(category, []):
            if not isinstance(stored, dict):
                continue
            for field in TRACKED_FIELDS:
                history = stored.get(field)
                if not isinstance(history, dict):
                    continue
                for key in history:
                    parsed = parse_dt(key)
                    if parsed is not None and (newest is None or parsed > newest):
                        newest = parsed
    if newest is not None and moment <= newest:
        moment = newest + timedelta(seconds=1)
    return moment


def append_history(history, moment, value):
    """Write `value` at a second strictly later than any existing key."""
    newest = None
    for key in history:
        parsed = parse_dt(key)
        if parsed is not None and (newest is None or parsed > newest):
            newest = parsed
    if newest is not None and moment <= newest:
        moment = newest + timedelta(seconds=1)
    history[format_dt(moment)] = value


def new_entry(item, moment):
    """First observation: static fields plus six initial history entries."""
    entry = {
        "id": item["id"],
        "published": normalize_published(item["published"]),
        "width": item["width"],
        "height": item["height"],
    }
    for field in TRACKED_FIELDS:
        entry[field] = {}
    stamp = format_dt(moment)
    for field in ("title", "description", "views", "likes", "preview"):
        entry[field][stamp] = item[field]
    entry["removed"][stamp] = False
    return entry


def update_entry(entry, item, moment):
    """Append history entries for tracked fields whose value changed."""
    for field in TRACKED_FIELDS:
        if not isinstance(entry.get(field), dict):
            entry[field] = {}
    for field in ("title", "description", "views", "likes", "preview"):
        value = item[field]
        history = entry[field]
        if not history or current_value(history) != value:
            append_history(history, moment, value)
    if not entry["removed"] or current_value(entry["removed"]) is not False:
        append_history(entry["removed"], moment, False)


def mark_removed(entry, moment):
    history = entry.get("removed")
    if not isinstance(history, dict):
        history = entry["removed"] = {}
    if not history or current_value(history) is not True:
        append_history(history, moment, True)


def sort_entries(entries):
    """Newest `published` first; ties break on lexicographically smaller id."""
    def published_key(entry):
        value = entry.get("published")
        return value if isinstance(value, str) else ""

    def entry_id(entry):
        value = entry.get("id")
        return value if isinstance(value, str) else ""

    ordered = sorted(entries, key=entry_id)
    ordered.sort(key=published_key, reverse=True)
    return ordered


def apply_source(catalog, source_data, moment):
    for category in CATEGORIES:
        stored_entries = catalog[category]
        by_id = {}
        for entry in stored_entries:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                by_id.setdefault(entry["id"], entry)

        seen = set()
        for item in source_data[category]:
            eid = item["id"]
            seen.add(eid)
            entry = by_id.get(eid)
            if entry is None:
                entry = new_entry(item, moment)
                stored_entries.append(entry)
                by_id[eid] = entry
            else:
                update_entry(entry, item, moment)

        for entry in stored_entries:
            if isinstance(entry, dict) and entry.get("id") not in seen:
                mark_removed(entry, moment)

        catalog[category] = sort_entries(stored_entries)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def command_init(name, url):
    if os.path.exists(name):
        raise VaultError("vault '%s' already exists" % name)
    catalog = {
        "version": CATALOG_VERSION,
        "source": url,
        "episodes": [],
        "streams": [],
        "clips": [],
    }
    os.makedirs(name)
    save_catalog(name, catalog)
    return 0


def command_sync(name):
    catalog = load_catalog(name)
    source_data = fetch_source(catalog["source"])
    moment = sync_timestamp(catalog)
    apply_source(catalog, source_data, moment)
    save_catalog(name, catalog)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mvault.py",
        description=(
            "Create local vaults for media-platform metadata and record "
            "tracked-field history by sync timestamp."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<subcommand>")

    init_parser = subparsers.add_parser(
        "init", help="create a new vault with an empty catalog"
    )
    init_parser.add_argument("name", help="vault directory to create")
    init_parser.add_argument("url", help="source metadata URL")

    sync_parser = subparsers.add_parser(
        "sync", help="fetch source metadata and update the vault catalog"
    )
    sync_parser.add_argument("name", help="existing vault directory")

    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help(sys.stderr)
        return 2

    try:
        if args.command == "init":
            return command_init(args.name, args.url)
        return command_sync(args.name)
    except VaultError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    except SourceError as exc:
        print("error: source metadata fetch failed: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
