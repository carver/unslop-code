#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Creates vault directories holding a `catalog.json`, and records the history of
tracked fields keyed by sync timestamp.
"""
import argparse
import json
import os
import shutil
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

CATEGORIES = ("episodes", "streams", "clips")
STATIC_FIELDS = ("id", "published", "width", "height")
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)
SOURCE_FIELDS = STATIC_FIELDS + SOURCE_TRACKED_FIELDS

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"
CATALOG_VERSION = 3
SUPPORTED_VERSIONS = (1, 2, 3)
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/%s"
TS_FORMAT = "%Y-%m-%dT%H:%M:%S"
FETCH_FAILURE = "Source metadata fetch failure"

PROG = "mvault.py"


class MvaultError(Exception):
    """A user-facing failure; the message is printed to stderr."""


class SourceFetchError(MvaultError):
    """The source metadata could not be fetched or is malformed."""

    def __init__(self, detail):
        super().__init__("%s: %s" % (FETCH_FAILURE, detail))


# --------------------------------------------------------------------------
# type helpers
# --------------------------------------------------------------------------

def is_string(value):
    return isinstance(value, str)


def is_integer(value):
    # bool is a subclass of int, but a boolean is not a pixel count.
    return isinstance(value, int) and not isinstance(value, bool)


def is_likes(value):
    return value is None or is_integer(value)


FIELD_CHECKS = {
    "id": is_string,
    "published": is_string,
    "width": is_integer,
    "height": is_integer,
    "title": is_string,
    "description": is_string,
    "views": is_integer,
    "likes": is_likes,
    "preview": is_string,
}


def same_value(left, right):
    """Change detection: `null` is an ordinary value, and bools are not ints."""
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return type(left) is type(right) and left == right


# --------------------------------------------------------------------------
# datetime handling
# --------------------------------------------------------------------------

def format_datetime(moment):
    """Render as `YYYY-MM-DDTHH:MM:SS`, never locale-sensitive."""
    return "%04d-%02d-%02dT%02d:%02d:%02d" % (
        moment.year, moment.month, moment.day,
        moment.hour, moment.minute, moment.second,
    )


def parse_datetime(text):
    """Parse ISO 8601 datetime or date-only text; None when unparseable."""
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    if not candidate:
        return None
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(candidate, pattern)
                break
            except ValueError:
                continue
        else:
            return None
    # Timezone suffixes are dropped, not converted; fractions are truncated.
    return parsed.replace(tzinfo=None, microsecond=0)


def normalize_published(text):
    """Date-only values gain a `00:00:00` time component."""
    parsed = parse_datetime(text)
    if parsed is None:
        return text
    return format_datetime(parsed)


def epoch_to_datetime(text):
    """Parse a version 1 UNIX-epoch-seconds history key; None when unusable."""
    if not isinstance(text, str):
        return None
    try:
        seconds = int(text.strip())
    except (ValueError, AttributeError):
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(
            tzinfo=None, microsecond=0)
    except (OverflowError, OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# history helpers
# --------------------------------------------------------------------------

def history_sort_key(key):
    parsed = parse_datetime(key)
    if parsed is None:
        return (0, datetime.min, key)
    return (1, parsed, key)


def latest_key(history):
    if not history:
        return None
    return max(history, key=history_sort_key)


def current_value(history):
    key = latest_key(history)
    return None if key is None else history[key]


def append_change(history, value, stamp):
    """Record `value` at `stamp` unless it already is the current value."""
    key = latest_key(history)
    if key is not None and same_value(history[key], value):
        return False
    history[stamp] = value
    return True


def newest_history_moment(catalog):
    """The latest datetime appearing as a history key anywhere in the catalog."""
    newest = None
    for category in CATEGORIES:
        for item in catalog.get(category, []):
            if not isinstance(item, dict):
                continue
            for field in TRACKED_FIELDS:
                history = item.get(field)
                if not isinstance(history, dict):
                    continue
                for key in history:
                    moment = parse_datetime(key)
                    if moment is not None and (newest is None or moment > newest):
                        newest = moment
    return newest


def sync_timestamp(catalog):
    """One timestamp per sync, strictly newer than every existing history key."""
    moment = datetime.now().replace(microsecond=0)
    newest = newest_history_moment(catalog)
    if newest is not None and moment <= newest:
        moment = newest + timedelta(seconds=1)
    return format_datetime(moment)


# --------------------------------------------------------------------------
# catalog storage
# --------------------------------------------------------------------------

def catalog_path(vault):
    return os.path.join(vault, CATALOG_NAME)


def backup_path(vault):
    return os.path.join(vault, BACKUP_NAME)


def new_catalog(url):
    return {
        "version": CATALOG_VERSION,
        "source": url,
        "episodes": [],
        "streams": [],
        "clips": [],
    }


def write_catalog(vault, catalog):
    """Back up any existing catalog byte-for-byte, then write the new one."""
    path = catalog_path(vault)
    if os.path.exists(path):
        # A backup that cannot be written aborts the write entirely, so the
        # existing catalog is never replaced without a recovery copy.
        try:
            shutil.copyfile(path, backup_path(vault))
        except OSError as exc:
            raise MvaultError("could not write %s for vault %s (%s)"
                              % (BACKUP_NAME, vault, exc))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(catalog, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def read_catalog_file(name):
    """Read `<name>/catalog.json`, or raise with the vault name."""
    if not os.path.isdir(name):
        raise MvaultError("vault not found: %s" % name)
    path = catalog_path(name)
    if not os.path.isfile(path):
        raise MvaultError("invalid vault: %s: missing %s" % (name, CATALOG_NAME))
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (ValueError, OSError) as exc:
        raise MvaultError("invalid vault: %s: unreadable %s (%s)"
                          % (name, CATALOG_NAME, exc))


def invalid_vault(name, detail):
    return MvaultError("invalid vault: %s: %s" % (name, detail))


def detect_version(name, catalog):
    """The catalog's declared version, validated against the supported set."""
    if not isinstance(catalog, dict):
        raise invalid_vault(name, "catalog root is not an object")
    if "version" not in catalog:
        raise invalid_vault(name, "missing catalog version field")
    version = catalog["version"]
    if not is_integer(version):
        raise invalid_vault(name, "non-integer catalog version %r" % (version,))
    if version not in SUPPORTED_VERSIONS:
        raise invalid_vault(name, "unsupported catalog version %r" % (version,))
    return version


# --------------------------------------------------------------------------
# legacy catalogs
# --------------------------------------------------------------------------

def v1_source_url(source_id):
    return V1_SOURCE_TEMPLATE % source_id


def convert_history(name, entry_id, field, history, epoch_keys):
    """Validate one stored history object, converting v1 epoch keys to ISO."""
    if not isinstance(history, dict):
        raise invalid_vault(
            name, "entry %r has a malformed %r history" % (entry_id, field))
    check = FIELD_CHECKS[field]
    converted = {}
    for key, value in history.items():
        if not is_string(key):
            raise invalid_vault(
                name, "entry %r has a non-string %r history key" % (entry_id, field))
        if epoch_keys:
            moment = epoch_to_datetime(key)
            if moment is None:
                raise invalid_vault(
                    name, "entry %r has a malformed epoch key %r in %r"
                          % (entry_id, key, field))
            key = format_datetime(moment)
        elif parse_datetime(key) is None:
            raise invalid_vault(
                name, "entry %r has a malformed datetime key %r in %r"
                      % (entry_id, key, field))
        if not check(value):
            raise invalid_vault(
                name, "entry %r has a wrong-typed %r history value" % (entry_id, field))
        converted[key] = value
    return converted


def migrate_entry(name, item, stamp, epoch_keys):
    """One legacy entry in v3 shape: converted history, `removed`, `annotations`."""
    if not isinstance(item, dict):
        raise invalid_vault(name, "legacy entry is not an object")
    entry_id = item.get("id")
    if not is_string(entry_id):
        raise invalid_vault(name, "legacy entry has a missing or non-string id")
    if "published" in item and not is_string(item["published"]):
        raise invalid_vault(name, "entry %r has a non-string published" % entry_id)
    for field in ("width", "height"):
        if field in item and not is_integer(item[field]):
            raise invalid_vault(
                name, "entry %r has a non-integer %s" % (entry_id, field))
    migrated = dict(item)
    for field in SOURCE_TRACKED_FIELDS:
        if field in item:
            migrated[field] = convert_history(
                name, entry_id, field, item[field], epoch_keys)
    # Legacy entries carry neither field, so both are additions.
    migrated["removed"] = {stamp: False}
    migrated["annotations"] = []
    return migrated


def migrate_v1(name, catalog, stamp):
    source_id = catalog.get("source_id")
    if not is_string(source_id):
        raise invalid_vault(name, "missing or non-string source_id")
    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise invalid_vault(name, "entries is missing or not an array")
    return {
        "version": CATALOG_VERSION,
        "source": v1_source_url(source_id),
        "episodes": [migrate_entry(name, item, stamp, True) for item in entries],
        "streams": [],
        "clips": [],
    }


def migrate_v2(name, catalog, stamp):
    source = catalog.get("source")
    if not is_string(source):
        raise invalid_vault(name, "missing or non-string source URL")
    migrated = {"version": CATALOG_VERSION, "source": source}
    for category in CATEGORIES:
        items = catalog.get(category)
        if not isinstance(items, list):
            raise invalid_vault(
                name, "category %r is missing or not an array" % category)
        migrated[category] = [migrate_entry(name, item, stamp, False)
                              for item in items]
    return migrated


def migration_timestamp():
    """One ISO 8601 timestamp for a whole migration run."""
    return format_datetime(datetime.now().replace(microsecond=0))


def validate_v3(name, catalog):
    if not is_string(catalog.get("source")):
        raise invalid_vault(name, "missing or non-string source URL")
    for category in CATEGORIES:
        items = catalog.get(category)
        if not isinstance(items, list):
            raise invalid_vault(
                name, "category %r is missing or not an array" % category)
        for item in items:
            if not isinstance(item, dict) or not is_string(item.get("id")):
                raise invalid_vault(
                    name, "category %r holds a malformed entry" % category)
    return catalog


def load_vault(name):
    """Load a vault as a v3 catalog in memory; returns (catalog, on-disk version).

    Version 1 and 2 catalogs are converted here and only here; nothing is
    written, so a read-only command leaves a legacy `catalog.json` alone.
    """
    raw = read_catalog_file(name)
    version = detect_version(name, raw)
    if version == CATALOG_VERSION:
        return validate_v3(name, raw), version
    stamp = migration_timestamp()
    if version == 1:
        return migrate_v1(name, raw, stamp), version
    return migrate_v2(name, raw, stamp), version


def load_catalog(name):
    """The v3 catalog of a vault, whatever version is stored on disk."""
    return load_vault(name)[0]


# --------------------------------------------------------------------------
# source fetching
# --------------------------------------------------------------------------

def fetch_source(url):
    """HTTP GET the source URL with urllib.request and parse its JSON body."""
    try:
        response = urllib.request.urlopen(url)
    except Exception as exc:                      # URLError, HTTPError, ...
        raise SourceFetchError("could not fetch %s (%s)" % (url, exc))
    try:
        raw = response.read()
    except Exception as exc:
        raise SourceFetchError("could not read %s (%s)" % (url, exc))
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
            raise SourceFetchError("undecodable response from %s (%s)" % (url, exc))
    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise SourceFetchError("invalid JSON from %s (%s)" % (url, exc))
    return validate_source(document)


def validate_source(document):
    """Every category must be an array of entries carrying all nine fields."""
    if not isinstance(document, dict):
        raise SourceFetchError("source response is not a JSON object")
    validated = {}
    for category in CATEGORIES:
        items = document.get(category)
        if not isinstance(items, list):
            raise SourceFetchError(
                "source response category %r is missing or not an array" % category)
        for item in items:
            if not isinstance(item, dict):
                raise SourceFetchError(
                    "source entry in %r is not an object" % category)
            for field in SOURCE_FIELDS:
                if field not in item:
                    raise SourceFetchError(
                        "source entry in %r is missing field %r" % (category, field))
                if not FIELD_CHECKS[field](item[field]):
                    raise SourceFetchError(
                        "source entry %r in %r has wrong type for field %r"
                        % (item.get("id"), category, field))
        validated[category] = items
    return validated


# --------------------------------------------------------------------------
# catalog updates
# --------------------------------------------------------------------------

def make_entry(source_entry, stamp):
    entry = {
        "id": source_entry["id"],
        "published": normalize_published(source_entry["published"]),
        "width": source_entry["width"],
        "height": source_entry["height"],
    }
    for field in SOURCE_TRACKED_FIELDS:
        entry[field] = {stamp: source_entry[field]}
    entry["removed"] = {stamp: False}
    entry["annotations"] = []
    return entry


def update_entry(entry, source_entry, stamp):
    for field in TRACKED_FIELDS:
        if not isinstance(entry.get(field), dict):
            entry[field] = {}
    for field in SOURCE_TRACKED_FIELDS:
        append_change(entry[field], source_entry[field], stamp)
    append_change(entry["removed"], False, stamp)


def mark_removed(entry, stamp):
    if not isinstance(entry.get("removed"), dict):
        entry["removed"] = {}
    append_change(entry["removed"], True, stamp)


def sort_entries(entries):
    """Newest `published` first; ties break by lexicographically smaller id."""
    entries.sort(key=lambda item: item.get("id") or "")
    entries.sort(key=lambda item: item.get("published") or "", reverse=True)


def update_catalog(catalog, source, stamp):
    for category in CATEGORIES:
        entries = catalog[category]
        by_id = {entry["id"]: entry for entry in entries}
        seen = set()
        for source_entry in source[category]:
            eid = source_entry["id"]
            seen.add(eid)
            existing = by_id.get(eid)
            if existing is None:
                entry = make_entry(source_entry, stamp)
                entries.append(entry)
                by_id[eid] = entry
            else:
                update_entry(existing, source_entry, stamp)
        for entry in entries:
            if entry["id"] not in seen:
                mark_removed(entry, stamp)
        sort_entries(entries)
    return catalog


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def command_init(args):
    name = args.name
    if os.path.exists(name):
        raise MvaultError("vault already exists: %s" % name)
    try:
        os.makedirs(name)
    except OSError as exc:
        raise MvaultError("could not create vault %s (%s)" % (name, exc))
    write_catalog(name, new_catalog(args.url))
    return 0


def command_migrate(args):
    name = args.name
    catalog, version = load_vault(name)
    if version == CATALOG_VERSION:
        # Already native: no rewrite, and therefore no backup either.
        return 0
    write_catalog(name, catalog)
    return 0


def command_sync(args):
    name = args.name
    # A v1/v2 catalog is migrated in memory here; the single write below backs
    # up the original pre-migration catalog and stores the v3 result.
    catalog = load_catalog(name)
    # Fetching and validating happens before any write, so a failed sync
    # leaves the vault unchanged.
    source = fetch_source(catalog["source"])
    stamp = sync_timestamp(catalog)
    update_catalog(catalog, source, stamp)
    write_catalog(name, catalog)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Create local vaults for media-platform metadata and "
                    "record tracked-field history by sync timestamp.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<subcommand>")

    init_parser = subparsers.add_parser(
        "init", help="create a new vault with an empty catalog")
    init_parser.add_argument("name", help="vault directory to create")
    init_parser.add_argument("url", help="source metadata URL")
    init_parser.set_defaults(func=command_init)

    sync_parser = subparsers.add_parser(
        "sync", help="fetch source metadata and update a vault's catalog")
    sync_parser.add_argument("name", help="existing vault directory")
    sync_parser.set_defaults(func=command_sync)

    migrate_parser = subparsers.add_parser(
        "migrate", help="convert a legacy vault catalog to the v3 format")
    migrate_parser.add_argument("name", help="existing vault directory")
    migrate_parser.set_defaults(func=command_migrate)

    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        parser.print_help(sys.stderr)
        return 2
    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        return args.func(args)
    except MvaultError as exc:
        sys.stderr.write("%s: error: %s\n" % (PROG, exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
