#!/usr/bin/env python3
"""mvault -- local vaults for media-platform metadata.

Creates local vaults holding a media platform's metadata and records the
history of every tracked field, keyed by sync timestamp.

    python mvault.py init <name> <url>
    python mvault.py sync <name>
    python mvault.py migrate <name>
    python mvault.py digest <name>

Catalogs written by older releases (version 1 and version 2) are loaded
transparently: every command that reads a vault migrates the catalog to the
native version 3 shape in memory, and only commands that write the catalog
persist the migration.
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
# Version 1 catalogs store only a short platform identifier; the full source
# URL is derived from it deterministically.
V1_SOURCE_PREFIX = "https://media.example.com/channel/"
CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"

CATEGORIES = ("episodes", "streams", "clips")

# Tracked fields sourced from the remote payload, in stored order.
SOURCE_TRACKED = ("title", "description", "views", "likes", "preview")
# `removed` is local-only: the source never provides it.
TRACKED = SOURCE_TRACKED + ("removed",)
STATIC = ("id", "published", "width", "height")

TS_FORMAT = "%Y-%m-%dT%H:%M:%S"
DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EPOCH_KEY_RE = re.compile(r"^-?\d+$")

_MISSING = object()


class MvaultError(Exception):
    """An error that is reported to stderr with a non-zero exit code."""


# ---------------------------------------------------------------------------
# datetime helpers (locale independent: no %b/%a, no strftime of names)
# ---------------------------------------------------------------------------
def format_ts(moment):
    """Render a datetime as `YYYY-MM-DDTHH:MM:SS`, no timezone suffix."""
    return "%04d-%02d-%02dT%02d:%02d:%02d" % (
        moment.year, moment.month, moment.day,
        moment.hour, moment.minute, moment.second,
    )


def parse_ts(text):
    """Parse a history key. Returns None when the text is not a timestamp."""
    if not isinstance(text, str):
        return None
    try:
        return datetime.strptime(text, TS_FORMAT)
    except ValueError:
        return None


def normalize_published(text):
    """Normalize a source `published` value to `YYYY-MM-DDTHH:MM:SS`.

    Date-only values gain a `00:00:00` time component; any timezone suffix is
    dropped without shifting the wall-clock reading. Text that is not a
    recognisable ISO 8601 value is stored verbatim.
    """
    value = text.strip()
    if DATE_ONLY_RE.match(value):
        return value + "T00:00:00"
    candidate = value
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1]
    try:
        moment = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            return text
    return format_ts(moment.replace(tzinfo=None))


# ---------------------------------------------------------------------------
# history helpers
# ---------------------------------------------------------------------------
def latest_key(history):
    """The chronologically newest key of a history object, or None."""
    if not isinstance(history, dict) or not history:
        return None
    dated = [(parse_ts(key), key) for key in history]
    dated = [item for item in dated if item[0] is not None]
    if not dated:
        # Unparseable keys are not part of the contract; fall back to text
        # order so the catalog stays readable rather than crashing.
        return max(history)
    return max(dated)[1]


def current_value(history):
    """Current value of a tracked field = value at the latest datetime key."""
    key = latest_key(history)
    if key is None:
        return _MISSING
    return history[key]


def newest_key_in(catalog):
    """The newest history key present anywhere in the catalog, or None."""
    newest = None
    for category in CATEGORIES:
        for entry in catalog.get(category, []):
            if not isinstance(entry, dict):
                continue
            for value in entry.values():
                if not isinstance(value, dict):
                    continue
                key = latest_key(value)
                moment = parse_ts(key) if key is not None else None
                if moment is not None and (newest is None or moment > newest):
                    newest = moment
    return newest


def sync_timestamp(catalog):
    """Timestamp used for every history entry appended by this sync.

    Reflects the sync execution time, but is advanced to a strictly later
    second whenever it would reuse an existing (or non-newer) second.
    """
    now = datetime.now().replace(microsecond=0)
    newest = newest_key_in(catalog)
    if newest is not None and now <= newest:
        return newest + timedelta(seconds=1)
    return now


# ---------------------------------------------------------------------------
# source validation
# ---------------------------------------------------------------------------
def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_str(value):
    return isinstance(value, str)


SOURCE_SCHEMA = (
    ("id", is_str, "string"),
    ("published", is_str, "string"),
    ("width", is_int, "integer"),
    ("height", is_int, "integer"),
    ("title", is_str, "string"),
    ("description", is_str, "string"),
    ("views", is_int, "integer"),
    ("likes", lambda v: v is None or is_int(v), "integer or null"),
    ("preview", is_str, "string"),
)


def validate_source(payload):
    """Validate the source response shape; raise MvaultError on any problem."""
    if not isinstance(payload, dict):
        raise MvaultError("source response is not a JSON object")

    validated = {}
    for category in CATEGORIES:
        if category not in payload:
            raise MvaultError(
                "source response is missing the %r array" % category)
        items = payload[category]
        if not isinstance(items, list):
            raise MvaultError("source response field %r is not an array" % category)

        entries = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise MvaultError(
                    "source entry %s[%d] is not an object" % (category, index))
            for field, check, expected in SOURCE_SCHEMA:
                if field not in item:
                    raise MvaultError(
                        "source entry %s[%d] is missing required field %r"
                        % (category, index, field))
                if not check(item[field]):
                    raise MvaultError(
                        "source entry %s[%d] field %r must be %s"
                        % (category, index, field, expected))
            entries.append(item)
        validated[category] = entries
    return validated


def fetch_source(url):
    """HTTP GET the source URL and return its validated payload."""
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise MvaultError("source metadata fetch failed for %s: HTTP %s"
                          % (url, exc.code))
    except Exception as exc:  # transport, DNS, unsupported scheme, ...
        raise MvaultError("source metadata fetch failed for %s: %s" % (url, exc))

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise MvaultError("source metadata fetch failed for %s: invalid JSON (%s)"
                          % (url, exc))

    try:
        return validate_source(payload)
    except MvaultError as exc:
        raise MvaultError("source metadata fetch failed for %s: %s" % (url, exc))


# ---------------------------------------------------------------------------
# vault I/O
# ---------------------------------------------------------------------------
def vault_paths(name):
    return os.path.join(name, CATALOG_NAME), os.path.join(name, BACKUP_NAME)


def read_catalog_file(name):
    """Read `<name>/catalog.json` and return `(catalog, version)`.

    Performs no migration and no write: it only parses the file, determines the
    declared version and validates the shape documented for that version.
    """
    catalog_path, _ = vault_paths(name)
    if not os.path.isdir(name):
        raise MvaultError("vault %r does not exist" % name)
    if not os.path.isfile(catalog_path):
        raise MvaultError("vault %r is invalid: %s is missing" % (name, CATALOG_NAME))
    try:
        with open(catalog_path, "r", encoding="utf-8") as handle:
            catalog = json.load(handle)
    except Exception as exc:
        raise MvaultError("vault %r is invalid: could not read %s (%s)"
                          % (name, CATALOG_NAME, exc))

    if not isinstance(catalog, dict):
        raise MvaultError("vault %r is invalid: %s is not a JSON object"
                          % (name, CATALOG_NAME))

    version = detect_version(name, catalog)
    if version == 1:
        validate_v1(name, catalog)
    elif version == 2:
        validate_v2(name, catalog)
    else:
        validate_v3(name, catalog)
    return catalog, version


def detect_version(name, catalog):
    """Read and check the `version` field of a parsed catalog."""
    if "version" not in catalog:
        raise MvaultError("vault %r is invalid: %s has no version field"
                          % (name, CATALOG_NAME))
    version = catalog["version"]
    if not is_int(version):
        raise MvaultError(
            "vault %r is invalid: catalog version must be an integer, got %r"
            % (name, version))
    if version > CATALOG_VERSION:
        raise MvaultError(
            "vault %r is invalid: unsupported catalog version %d (this mvault "
            "supports versions 1 through %d)" % (name, version, CATALOG_VERSION))
    if version not in SUPPORTED_VERSIONS:
        raise MvaultError(
            "vault %r is invalid: unsupported catalog version %d (this mvault "
            "supports versions 1 through %d)" % (name, version, CATALOG_VERSION))
    return version


# ---------------------------------------------------------------------------
# legacy catalog validation
# ---------------------------------------------------------------------------
LEGACY_STATIC_SCHEMA = (
    ("id", is_str, "string"),
    ("published", is_str, "string"),
    ("width", is_int, "integer"),
    ("height", is_int, "integer"),
)

LEGACY_HISTORY_SCHEMA = (
    ("title", is_str, "string"),
    ("description", is_str, "string"),
    ("views", is_int, "integer"),
    ("likes", lambda v: v is None or is_int(v), "integer or null"),
    ("preview", is_str, "string"),
)


def valid_epoch_key(key):
    """A version 1 history key: a string of UNIX epoch seconds."""
    if not is_str(key) or not EPOCH_KEY_RE.match(key):
        return False
    try:
        epoch_to_iso(key)
    except (ValueError, OverflowError, OSError):
        return False
    return True


def valid_iso_key(key):
    """A version 2 history key: an ISO 8601 datetime string."""
    if not is_str(key):
        return False
    candidate = key[:-1] if key.endswith(("Z", "z")) else key
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return True


def epoch_to_iso(key):
    """Convert epoch-seconds text to `YYYY-MM-DDTHH:MM:SS` in UTC."""
    moment = datetime.fromtimestamp(int(key), tz=timezone.utc)
    return format_ts(moment)


def validate_legacy_entry(name, version, where, entry):
    """Validate one version 1 / version 2 entry against its schema."""
    if not isinstance(entry, dict):
        raise MvaultError("vault %r is invalid: %s is not an object"
                          % (name, where))
    for field, check, expected in LEGACY_STATIC_SCHEMA:
        if field not in entry:
            raise MvaultError("vault %r is invalid: %s is missing required "
                              "field %r" % (name, where, field))
        if not check(entry[field]):
            raise MvaultError("vault %r is invalid: %s field %r must be %s"
                              % (name, where, field, expected))
    key_ok = valid_epoch_key if version == 1 else valid_iso_key
    key_kind = "UNIX epoch seconds" if version == 1 else "an ISO 8601 datetime"
    for field, check, expected in LEGACY_HISTORY_SCHEMA:
        if field not in entry:
            raise MvaultError("vault %r is invalid: %s is missing required "
                              "field %r" % (name, where, field))
        history = entry[field]
        if not isinstance(history, dict):
            raise MvaultError("vault %r is invalid: %s field %r must be a "
                              "history object" % (name, where, field))
        for key, value in history.items():
            if not key_ok(key):
                raise MvaultError(
                    "vault %r is invalid: %s field %r has history key %r, "
                    "which is not %s" % (name, where, field, key, key_kind))
            if not check(value):
                raise MvaultError(
                    "vault %r is invalid: %s field %r history values must be "
                    "%s" % (name, where, field, expected))


def validate_v1(name, catalog):
    """Validate the version 1 catalog schema."""
    if not is_str(catalog.get("source_id")):
        raise MvaultError("vault %r is invalid: version 1 catalog requires a "
                          "string source_id" % name)
    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise MvaultError("vault %r is invalid: version 1 catalog requires an "
                          "entries array" % name)
    for index, entry in enumerate(entries):
        validate_legacy_entry(name, 1, "entries[%d]" % index, entry)


def validate_v2(name, catalog):
    """Validate the version 2 catalog schema."""
    if not is_str(catalog.get("source")):
        raise MvaultError("vault %r is invalid: version 2 catalog requires a "
                          "string source" % name)
    for category in CATEGORIES:
        entries = catalog.get(category)
        if not isinstance(entries, list):
            raise MvaultError("vault %r is invalid: version 2 catalog requires "
                              "a %s array" % (name, category))
        for index, entry in enumerate(entries):
            validate_legacy_entry(name, 2, "%s[%d]" % (category, index), entry)


def validate_v3(name, catalog):
    """Validate the native (version 3) catalog root schema."""
    if not is_str(catalog.get("source")):
        raise MvaultError("vault %r is invalid: source must be a string" % name)
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise MvaultError("vault %r is invalid: %s must be an array"
                              % (name, category))


# ---------------------------------------------------------------------------
# legacy migration
# ---------------------------------------------------------------------------
def v1_source_url(source_id):
    """Derive the full source URL of a version 1 vault from its `source_id`."""
    return V1_SOURCE_PREFIX + source_id


def convert_entry(entry, version):
    """Convert a legacy entry to the v3 shape, minus the migration-added keys."""
    converted = {}
    for field in STATIC:
        converted[field] = entry[field]
    for field in SOURCE_TRACKED:
        history = entry[field]
        if version == 1:
            converted[field] = {epoch_to_iso(key): value
                                for key, value in history.items()}
        else:
            converted[field] = dict(history)
    return converted


def migrate_catalog(catalog, version):
    """Return the version 3 form of a parsed v1/v2 catalog.

    The input object is left untouched, so a caller that only reads the vault
    can discard the result without having modified anything on disk.
    """
    if version == CATALOG_VERSION:
        return catalog

    migrated = {"version": CATALOG_VERSION}
    if version == 1:
        migrated["source"] = v1_source_url(catalog["source_id"])
        # Every version 1 entry becomes an episode; the other two categories
        # are created empty.
        migrated["episodes"] = [convert_entry(entry, 1)
                                for entry in catalog["entries"]]
        migrated["streams"] = []
        migrated["clips"] = []
        skip = {"version", "source_id", "entries"}
    else:
        migrated["source"] = catalog["source"]
        for category in CATEGORIES:
            migrated[category] = [convert_entry(entry, 2)
                                  for entry in catalog[category]]
        skip = {"version", "source"} | set(CATEGORIES)

    # The migration-added `removed` timestamp is newer than every history key
    # already present, so the migrated value reads as the current one.
    stamp = format_ts(sync_timestamp(migrated))
    for category in CATEGORIES:
        for converted, original in zip(migrated[category],
                                       legacy_entries(catalog, version, category)):
            converted["removed"] = {stamp: False}
            converted["annotations"] = original.get("annotations", [])
            for key, value in original.items():
                if key not in converted:
                    converted[key] = value

    for key, value in catalog.items():
        if key not in skip and key not in migrated:
            migrated[key] = value
    return migrated


def legacy_entries(catalog, version, category):
    """The legacy source list that feeds `category` of the migrated catalog."""
    if version == 1:
        return catalog["entries"] if category == "episodes" else []
    return catalog[category]


def load_catalog(name):
    """Load a vault of any supported version as an in-memory v3 catalog.

    Returns `(catalog, version)` where `version` is the version found on disk;
    nothing is written, so read-only callers leave `catalog.json` alone.
    """
    catalog, version = read_catalog_file(name)
    return migrate_catalog(catalog, version), version


def dump_catalog(catalog):
    return json.dumps(catalog, indent=2) + "\n"


def write_catalog(name, catalog):
    """Write the catalog, backing up any existing one byte-for-byte first."""
    catalog_path, backup_path = vault_paths(name)
    if os.path.isfile(catalog_path):
        try:
            shutil.copyfile(catalog_path, backup_path)
        except OSError as exc:
            raise MvaultError("could not write backup %s: %s"
                              % (backup_path, exc))
    temp_path = catalog_path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write(dump_catalog(catalog))
        os.replace(temp_path, catalog_path)
    except OSError as exc:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise MvaultError("could not write %s: %s" % (catalog_path, exc))


# ---------------------------------------------------------------------------
# sync logic
# ---------------------------------------------------------------------------
def new_entry(source_entry, stamp):
    """Build a first-observation entry with history for all six tracked fields."""
    entry = {
        "id": source_entry["id"],
        "published": normalize_published(source_entry["published"]),
        "width": source_entry["width"],
        "height": source_entry["height"],
    }
    for field in SOURCE_TRACKED:
        entry[field] = {stamp: source_entry[field]}
    entry["removed"] = {stamp: False}
    return entry


def record(entry, field, value, stamp):
    """Append a history entry when the tracked value changed."""
    history = entry.get(field)
    if not isinstance(history, dict):
        history = {}
        entry[field] = history
    existing = current_value(history)
    if existing is _MISSING or not same_value(existing, value):
        history[stamp] = value
        return True
    return False


def same_value(left, right):
    """Change detection; `null` is an ordinary value and `0 != False`."""
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


def sort_entries(entries):
    """Newest `published` first; ties broken by lexicographically smaller id."""
    ordered = sorted(entries, key=lambda item: str(item.get("id", "")))
    ordered.sort(key=lambda item: str(item.get("published", "")), reverse=True)
    return ordered


def apply_sync(catalog, payload, stamp):
    """Apply a validated source payload to the catalog in place."""
    for category in CATEGORIES:
        entries = catalog[category]
        by_id = {}
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                by_id.setdefault(entry["id"], entry)

        seen = set()
        for source_entry in payload[category]:
            entry_id = source_entry["id"]
            seen.add(entry_id)
            entry = by_id.get(entry_id)
            if entry is None:
                entry = new_entry(source_entry, stamp)
                entries.append(entry)
                by_id[entry_id] = entry
                continue
            for field in SOURCE_TRACKED:
                record(entry, field, source_entry[field], stamp)
            record(entry, "removed", False, stamp)

        for entry_id, entry in by_id.items():
            if entry_id not in seen:
                record(entry, "removed", True, stamp)

        catalog[category] = sort_entries(entries)
    return catalog


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_init(args):
    name = args.name
    if os.path.exists(name):
        raise MvaultError("cannot create vault %r: %s already exists"
                          % (name, name))
    try:
        os.makedirs(name)
    except OSError as exc:
        raise MvaultError("cannot create vault %r: %s" % (name, exc))

    catalog = {
        "version": CATALOG_VERSION,
        "source": args.url,
        "episodes": [],
        "streams": [],
        "clips": [],
    }
    write_catalog(name, catalog)
    print("initialized vault %s" % name)
    return 0


def cmd_sync(args):
    name = args.name
    catalog, version = load_catalog(name)
    payload = fetch_source(catalog["source"])
    stamp = format_ts(sync_timestamp(catalog))
    apply_sync(catalog, payload, stamp)
    write_catalog(name, catalog)
    total = sum(len(catalog[category]) for category in CATEGORIES)
    if version != CATALOG_VERSION:
        print("migrated vault %s from version %d to version %d"
              % (name, version, CATALOG_VERSION))
    print("synced vault %s at %s (%d entries)" % (name, stamp, total))
    return 0


def cmd_migrate(args):
    """Convert a v1/v2 catalog to v3 on disk; a v3 catalog is left alone."""
    name = args.name
    catalog, version = read_catalog_file(name)
    if version == CATALOG_VERSION:
        # No-op: no migration, no backup, no write.
        print("vault %s is already at version %d" % (name, CATALOG_VERSION))
        return 0
    migrated = migrate_catalog(catalog, version)
    write_catalog(name, migrated)
    print("migrated vault %s from version %d to version %d"
          % (name, version, CATALOG_VERSION))
    return 0


def cmd_digest(args):
    """Read-only summary of a vault; never writes to the vault."""
    name = args.name
    catalog, version = load_catalog(name)
    counts = ", ".join("%d %s" % (len(catalog[category]), category)
                       for category in CATEGORIES)
    print("vault %s (catalog version %d): %s" % (name, version, counts))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mvault.py",
        description="Create local vaults for media-platform metadata and "
                    "record tracked-field history by sync timestamp.",
    )
    subparsers = parser.add_subparsers(dest="command", title="subcommands")

    init_parser = subparsers.add_parser(
        "init", help="create a new vault with an empty catalog")
    init_parser.add_argument("name", help="vault directory to create")
    init_parser.add_argument("url", help="source URL for the vault")
    init_parser.set_defaults(func=cmd_init)

    sync_parser = subparsers.add_parser(
        "sync", help="fetch the source and update the vault catalog")
    sync_parser.add_argument("name", help="existing vault directory")
    sync_parser.set_defaults(func=cmd_sync)

    migrate_parser = subparsers.add_parser(
        "migrate", help="convert a legacy catalog to the native version 3 format")
    migrate_parser.add_argument("name", help="existing vault directory")
    migrate_parser.set_defaults(func=cmd_migrate)

    digest_parser = subparsers.add_parser(
        "digest", help="print a read-only summary of a vault")
    digest_parser.add_argument("name", help="existing vault directory")
    digest_parser.set_defaults(func=cmd_digest)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help(sys.stderr)
        return 2
    try:
        return args.func(args)
    except MvaultError as exc:
        sys.stderr.write("mvault: %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
