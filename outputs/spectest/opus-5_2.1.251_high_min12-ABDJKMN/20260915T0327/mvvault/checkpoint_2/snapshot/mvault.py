#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Creates local vaults for media-platform metadata and records tracked-field
history by sync timestamp.

Usage:
    python mvault.py init <name> <url>
    python mvault.py sync <name>
    python mvault.py migrate <name>
"""
import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

CATALOG_VERSION = 3
SUPPORTED_VERSIONS = (1, 2, 3)
LEGACY_SOURCE_PREFIX = "https://media.example.com/channel/"
CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"
CATEGORIES = ("episodes", "streams", "clips")
HISTORY_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = HISTORY_FIELDS + ("removed",)
STATIC_FIELDS = ("id", "published", "width", "height")
EPOCH_KEY = re.compile(r"^-?\d+$")
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


def read_catalog_file(name):
    """Read `<name>/catalog.json` as raw JSON, whatever version it declares."""
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
    return catalog


def catalog_version(name, catalog):
    """The declared catalog version, validated against the supported set."""
    if "version" not in catalog:
        raise VaultError(
            "vault '%s' is invalid: catalog is missing the 'version' field" % name
        )
    version = catalog["version"]
    if not is_int(version):
        raise VaultError(
            "vault '%s' is invalid: catalog 'version' must be an integer "
            "(supported versions: %s)"
            % (name, ", ".join(str(v) for v in SUPPORTED_VERSIONS))
        )
    if version not in SUPPORTED_VERSIONS:
        raise VaultError(
            "vault '%s' has unsupported catalog version %d "
            "(supported versions: %s)"
            % (name, version, ", ".join(str(v) for v in SUPPORTED_VERSIONS))
        )
    return version


def validate_native(name, catalog):
    """Root-schema check for a version 3 catalog."""
    if not isinstance(catalog.get("source"), str):
        raise VaultError("vault '%s' is invalid: missing source URL" % name)
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise VaultError(
                "vault '%s' is invalid: '%s' must be an array" % (name, category)
            )
    return catalog


# --------------------------------------------------------------------------
# legacy (version 1 / version 2) migration
# --------------------------------------------------------------------------

def legacy_source_url(source_id):
    """The deterministic source URL of a version 1 vault."""
    return LEGACY_SOURCE_PREFIX + source_id


def malformed(name, detail):
    raise VaultError("vault '%s' has malformed legacy entry data: %s"
                     % (name, detail))


def convert_epoch_key(name, eid, field, key):
    """`"1718444400"` -> `"2024-06-15T09:40:00"` (UTC)."""
    if not isinstance(key, str) or not EPOCH_KEY.match(key.strip()):
        malformed(name, "entry '%s' field '%s' has a non-epoch history key %r"
                        % (eid, field, key))
    try:
        moment = datetime.fromtimestamp(int(key.strip()), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        malformed(name, "entry '%s' field '%s' has an out-of-range epoch key %r"
                        % (eid, field, key))
    return format_dt(moment.replace(tzinfo=None))


def check_history_value(name, eid, field, value):
    if field in ("title", "description", "preview"):
        if not isinstance(value, str):
            malformed(name, "entry '%s' field '%s' has a non-string value %r"
                            % (eid, field, value))
    elif field == "views":
        if not is_int(value):
            malformed(name, "entry '%s' field '%s' has a non-integer value %r"
                            % (eid, field, value))
    elif field == "likes":
        if not (value is None or is_int(value)):
            malformed(name, "entry '%s' field '%s' must be an integer or null, "
                            "got %r" % (eid, field, value))


def convert_history(name, eid, field, history, version):
    """Validate one legacy history object and return it with ISO 8601 keys."""
    if not isinstance(history, dict):
        malformed(name, "entry '%s' field '%s' is not a history object" % (eid, field))
    converted = {}
    for key, value in history.items():
        check_history_value(name, eid, field, value)
        if version == 1:
            converted[convert_epoch_key(name, eid, field, key)] = value
        else:
            if parse_dt(key) is None:
                malformed(name, "entry '%s' field '%s' has a non-ISO 8601 "
                                "history key %r" % (eid, field, key))
            converted[key] = value
    return converted


def migrate_entry(name, item, version, stamp):
    """Convert one legacy entry to the version 3 entry shape."""
    if not isinstance(item, dict):
        malformed(name, "entry is not an object (%r)" % (item,))
    eid = item.get("id")
    if not isinstance(eid, str):
        malformed(name, "entry is missing a string 'id' (%r)" % (item.get("id"),))
    if not isinstance(item.get("published"), str):
        malformed(name, "entry '%s' is missing a string 'published'" % eid)
    for field in ("width", "height"):
        if not is_int(item.get(field)):
            malformed(name, "entry '%s' has a non-integer '%s'" % (eid, field))

    entry = dict(item)
    for field in HISTORY_FIELDS:
        if field not in item:
            malformed(name, "entry '%s' is missing required field '%s'"
                            % (eid, field))
        entry[field] = convert_history(name, eid, field, item[field], version)
    entry["removed"] = {stamp: False}
    entry["annotations"] = []
    return entry


def migrate_catalog(name, catalog, version, moment=None):
    """Return the version 3 representation of a v1 or v2 catalog."""
    stamp = format_dt(moment or datetime.now().replace(microsecond=0))

    if version == 1:
        source_id = catalog.get("source_id")
        if not isinstance(source_id, str):
            raise VaultError(
                "vault '%s' is invalid: version 1 catalog is missing a string "
                "'source_id'" % name
            )
        entries = catalog.get("entries")
        if not isinstance(entries, list):
            raise VaultError(
                "vault '%s' is invalid: version 1 'entries' must be an array" % name
            )
        return {
            "version": CATALOG_VERSION,
            "source": legacy_source_url(source_id),
            "episodes": [migrate_entry(name, item, 1, stamp) for item in entries],
            "streams": [],
            "clips": [],
        }

    source = catalog.get("source")
    if not isinstance(source, str):
        raise VaultError(
            "vault '%s' is invalid: version 2 catalog is missing a string "
            "'source'" % name
        )
    migrated = {"version": CATALOG_VERSION, "source": source}
    for category in CATEGORIES:
        items = catalog.get(category, [])
        if not isinstance(items, list):
            raise VaultError(
                "vault '%s' is invalid: '%s' must be an array" % (name, category)
            )
        migrated[category] = [migrate_entry(name, item, 2, stamp) for item in items]
    return migrated


def load_catalog(name):
    """Load a vault catalog of any supported version as version 3 in memory.

    Returns `(catalog, stored_version)`; nothing is written to disk.
    """
    raw = read_catalog_file(name)
    version = catalog_version(name, raw)
    if version == CATALOG_VERSION:
        return validate_native(name, raw), version
    return migrate_catalog(name, raw, version), version


def save_catalog(name, catalog):
    """Back up the existing catalog, then write the new one."""
    vault_dir = name
    path = catalog_path(vault_dir)
    if os.path.exists(path):
        try:
            shutil.copyfile(path, backup_path(vault_dir))
        except Exception as exc:
            raise VaultError("vault '%s': could not write %s (%s)"
                             % (name, BACKUP_NAME, exc))
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
    for field in HISTORY_FIELDS:
        entry[field][stamp] = item[field]
    entry["removed"][stamp] = False
    entry["annotations"] = []
    return entry


def update_entry(entry, item, moment):
    """Append history entries for tracked fields whose value changed."""
    entry.setdefault("annotations", [])
    for field in TRACKED_FIELDS:
        if not isinstance(entry.get(field), dict):
            entry[field] = {}
    for field in HISTORY_FIELDS:
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
    catalog, _version = load_catalog(name)
    source_data = fetch_source(catalog["source"])
    moment = sync_timestamp(catalog)
    apply_source(catalog, source_data, moment)
    save_catalog(name, catalog)
    return 0


def command_migrate(name):
    """Convert a v1 or v2 catalog to v3 on disk; a v3 catalog is a no-op."""
    raw = read_catalog_file(name)
    version = catalog_version(name, raw)
    if version == CATALOG_VERSION:
        validate_native(name, raw)
        return 0
    migrated = migrate_catalog(name, raw, version)
    save_catalog(name, migrated)
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

    migrate_parser = subparsers.add_parser(
        "migrate", help="convert a legacy (v1/v2) catalog to the v3 format"
    )
    migrate_parser.add_argument("name", help="existing vault directory")

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
        if args.command == "migrate":
            return command_migrate(args.name)
        return command_sync(args.name)
    except VaultError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    except SourceError as exc:
        print("error: source metadata fetch failed: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
