#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Creates a vault directory holding a ``catalog.json`` and records the history of
tracked fields keyed by sync timestamp.

Catalog versions 1 and 2 are loaded transparently: every command that reads a
vault sees the native version 3 shape, and ``migrate`` (or a ``sync`` of a
legacy vault) persists that conversion to disk.
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

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"

VERSION = 3
MIN_VERSION = 1
CATEGORIES = ("episodes", "streams", "clips")

STATIC_FIELDS = ("id", "published", "width", "height")
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)

# Version 1 stores only a short platform identifier; the full source URL is
# derived from it deterministically.
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/%s"
V1_ENTRIES_FIELD = "entries"
V1_SOURCE_FIELD = "source_id"
EPOCH_KEY_RE = re.compile(r"^[+-]?[0-9]+(?:\.[0-9]+)?$")

DT_FORMAT = "%Y-%m-%dT%H:%M:%S"

FETCH_FAILURE = "Source metadata fetch failure"


class MvaultError(Exception):
    """A user-facing error; the message is printed to stderr."""


class SourceError(MvaultError):
    """Anything that makes the source metadata unusable."""

    def __init__(self, detail=None):
        if detail:
            super().__init__("%s: %s" % (FETCH_FAILURE, detail))
        else:
            super().__init__(FETCH_FAILURE)


# --------------------------------------------------------------------------
# datetime helpers
# --------------------------------------------------------------------------

def format_dt(value):
    """Render a datetime as ``YYYY-MM-DDTHH:MM:SS`` (no timezone suffix)."""
    return value.strftime(DT_FORMAT)


def parse_dt(text):
    """Parse a history key / timestamp.  Returns ``None`` when unparseable."""
    if not isinstance(text, str):
        return None
    try:
        return datetime.strptime(text, DT_FORMAT)
    except ValueError:
        pass
    return parse_flexible_dt(text)


def parse_flexible_dt(text):
    """Best-effort ISO 8601 parse, dropping any timezone information."""
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    if not candidate:
        return None
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    candidate = candidate.replace(" ", "T", 1) if " " in candidate else candidate
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        for fmt in (DT_FORMAT, "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(candidate, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    # Timezone suffixes are never persisted; keep the wall-clock components.
    return parsed.replace(tzinfo=None, microsecond=0)


def normalize_published(text):
    """Normalize a published value; date-only text gets a ``00:00:00`` time."""
    parsed = parse_flexible_dt(text)
    if parsed is None:
        return text
    return format_dt(parsed)


# --------------------------------------------------------------------------
# history helpers
# --------------------------------------------------------------------------

def history_sort_key(key):
    parsed = parse_dt(key)
    if parsed is None:
        return (1, key)
    return (0, format_dt(parsed))


def latest_key(history):
    """Latest key of a history object in chronological order."""
    if not isinstance(history, dict) or not history:
        return None
    return max(history, key=history_sort_key)


def current_value(history):
    key = latest_key(history)
    if key is None:
        return None
    return history[key]


def has_history(history):
    return isinstance(history, dict) and bool(history)


def same_value(a, b):
    """Equality that keeps ``null`` distinct from numbers and booleans."""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if isinstance(a, bool):
        return a is b
    return type(a) is type(b) and a == b


def catalog_latest_dt(catalog):
    """Newest timestamp recorded anywhere in the catalog's histories."""
    newest = None
    for category in CATEGORIES:
        for entry in catalog.get(category) or []:
            if not isinstance(entry, dict):
                continue
            for field in TRACKED_FIELDS:
                history = entry.get(field)
                if not isinstance(history, dict):
                    continue
                for key in history:
                    parsed = parse_dt(key)
                    if parsed is not None and (newest is None or parsed > newest):
                        newest = parsed
    return newest


def sync_timestamp(catalog, now=None):
    """Sync timestamp: execution time, advanced past any recorded second."""
    stamp = (now or datetime.now()).replace(microsecond=0)
    newest = catalog_latest_dt(catalog)
    if newest is not None and stamp <= newest:
        stamp = newest + timedelta(seconds=1)
    return stamp


# --------------------------------------------------------------------------
# catalog helpers
# --------------------------------------------------------------------------

def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def sort_entries(entries):
    """Newest ``published`` first; ties broken by lexicographically smaller id."""
    by_id = sorted(entries, key=lambda e: str(e.get("id", "")))
    return sorted(by_id, key=lambda e: str(e.get("published", "")), reverse=True)


def catalog_paths(name):
    vault_dir = name
    return vault_dir, os.path.join(vault_dir, CATALOG_NAME), os.path.join(vault_dir, BACKUP_NAME)


def read_catalog_file(name):
    """Read and JSON-decode ``catalog.json`` without interpreting its shape."""
    vault_dir, catalog_path, _ = catalog_paths(name)
    if not os.path.isdir(vault_dir):
        raise MvaultError("vault '%s' does not exist" % name)
    if not os.path.isfile(catalog_path):
        raise MvaultError("vault '%s' is invalid: missing %s" % (name, CATALOG_NAME))
    try:
        with open(catalog_path, "r", encoding="utf-8") as handle:
            catalog = json.load(handle)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise MvaultError("vault '%s' is invalid: unreadable %s (%s)" % (name, CATALOG_NAME, exc))

    if not isinstance(catalog, dict):
        raise MvaultError("vault '%s' is invalid: %s is not a JSON object" % (name, CATALOG_NAME))
    return catalog


def catalog_version(catalog, name):
    """Return the declared catalog version, rejecting anything unsupported."""
    if "version" not in catalog:
        raise MvaultError("vault '%s' is invalid: missing catalog version field" % name)
    version = catalog["version"]
    if not is_int(version):
        raise MvaultError(
            "vault '%s' is invalid: non-integer catalog version %s" % (name, json.dumps(version))
        )
    if version > VERSION or version < MIN_VERSION:
        raise MvaultError(
            "vault '%s' is invalid: unsupported catalog version %d "
            "(supported versions are %d-%d)" % (name, version, MIN_VERSION, VERSION)
        )
    return version


def validate_v3(catalog, name):
    if not isinstance(catalog.get("source"), str):
        raise MvaultError("vault '%s' is invalid: missing source URL" % name)
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise MvaultError("vault '%s' is invalid: missing '%s' array" % (name, category))
        for entry in catalog[category]:
            if not isinstance(entry, dict):
                raise MvaultError("vault '%s' is invalid: malformed '%s' entry" % (name, category))
    return catalog


def load_vault(name, stamp=None):
    """Load a vault of any supported version as a v3 catalog.

    Returns ``(catalog, version)`` where ``catalog`` is always in the native v3
    shape and ``version`` is the version found on disk.  Nothing is written:
    read-only commands never rewrite ``catalog.json``.

    ``stamp`` is the migration timestamp used for legacy catalogs; when omitted
    the migration-added ``removed`` histories are left open for the caller to
    close with ``apply_migration_stamp``.
    """
    raw = read_catalog_file(name)
    version = catalog_version(raw, name)
    if version == VERSION:
        return validate_v3(raw, name), version
    return migrate_catalog(raw, version, name, stamp), version


def load_catalog(name):
    """Load a vault catalog in the native v3 shape."""
    return load_vault(name, migration_timestamp())[0]


def write_catalog(name, catalog):
    """Back up the existing catalog byte-for-byte, then write the new one."""
    _, catalog_path, backup_path = catalog_paths(name)
    if os.path.isfile(catalog_path):
        try:
            shutil.copyfile(catalog_path, backup_path)
        except (OSError, shutil.Error) as exc:
            # Abort before touching catalog.json so the original survives.
            raise MvaultError(
                "vault '%s': could not write %s (%s)" % (name, BACKUP_NAME, exc)
            )
    payload = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    try:
        with open(catalog_path, "w", encoding="utf-8") as handle:
            handle.write(payload)
    except OSError as exc:
        raise MvaultError("vault '%s': could not write %s (%s)" % (name, CATALOG_NAME, exc))


# --------------------------------------------------------------------------
# legacy catalogs (version 1 and version 2)
# --------------------------------------------------------------------------

STATIC_FIELD_CHECKS = {
    "id": lambda v: isinstance(v, str),
    "published": lambda v: isinstance(v, str),
    "width": is_int,
    "height": is_int,
}

HISTORY_VALUE_CHECKS = {
    "title": lambda v: isinstance(v, str),
    "description": lambda v: isinstance(v, str),
    "views": is_int,
    "likes": lambda v: v is None or is_int(v),
    "preview": lambda v: isinstance(v, str),
}


def migration_timestamp(now=None):
    """ISO 8601 timestamp recorded for migration-added history entries."""
    return format_dt((now or datetime.now()).replace(microsecond=0))


def v1_source_url(source_id):
    """Derive a full source URL from a version 1 ``source_id``."""
    return V1_SOURCE_TEMPLATE % source_id


def legacy_error(name, version, detail):
    return MvaultError(
        "vault '%s' is invalid: malformed version %d catalog: %s" % (name, version, detail)
    )


def epoch_seconds(key):
    """Numeric value of a UNIX epoch-seconds history key, or ``None``."""
    if not isinstance(key, str) or not EPOCH_KEY_RE.match(key.strip()):
        return None
    try:
        return int(float(key.strip()))
    except (TypeError, ValueError):
        return None


def epoch_key_to_iso(seconds):
    """Convert UNIX epoch seconds to ``YYYY-MM-DDTHH:MM:SS`` in UTC."""
    try:
        moment = datetime.fromtimestamp(seconds, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return format_dt(moment.replace(tzinfo=None))


def convert_history(history, field, version, name, where):
    """Validate a legacy history object and return it with v3 keys."""
    if not isinstance(history, dict):
        raise legacy_error(name, version, "%s has a malformed '%s' history object" % (where, field))
    check = HISTORY_VALUE_CHECKS[field]
    converted = []
    for key, value in history.items():
        if not isinstance(key, str) or not key.strip():
            raise legacy_error(
                name, version, "%s has a malformed '%s' history key" % (where, field)
            )
        if version == 1:
            order = epoch_seconds(key)
            iso = epoch_key_to_iso(order) if order is not None else None
            if iso is None:
                raise legacy_error(
                    name, version,
                    "%s has a non-epoch '%s' history key %s" % (where, field, json.dumps(key)),
                )
        else:
            parsed = parse_dt(key)
            if parsed is None:
                raise legacy_error(
                    name, version,
                    "%s has a non-ISO 8601 '%s' history key %s" % (where, field, json.dumps(key)),
                )
            # Version 2 keys are already ISO 8601; they are preserved verbatim.
            iso = key
            order = None
        if not check(value):
            raise legacy_error(
                name, version,
                "%s has an invalid '%s' value at %s" % (where, field, json.dumps(key)),
            )
        converted.append((order, iso, value))

    if version == 1:
        converted.sort(key=lambda item: item[0])
    return {iso: value for _, iso, value in converted}


def convert_entry(entry, version, name, where, stamp):
    """Validate a legacy entry and return its v3 equivalent."""
    if not isinstance(entry, dict):
        raise legacy_error(name, version, "%s is not a JSON object" % where)

    for field, check in STATIC_FIELD_CHECKS.items():
        if field not in entry:
            raise legacy_error(name, version, "%s is missing field '%s'" % (where, field))
        if not check(entry[field]):
            raise legacy_error(
                name, version, "%s has an invalid value for field '%s'" % (where, field)
            )
    for field in SOURCE_TRACKED_FIELDS:
        if field not in entry:
            raise legacy_error(name, version, "%s is missing field '%s'" % (where, field))

    migrated = {}
    # Keep any fields the legacy catalog carried beyond the documented schema.
    for key, value in entry.items():
        if key in SOURCE_TRACKED_FIELDS or key in ("removed", "annotations"):
            continue
        migrated[key] = value
    for field in SOURCE_TRACKED_FIELDS:
        migrated[field] = convert_history(entry[field], field, version, name, where)

    removed = entry.get("removed")
    if has_history(removed):
        migrated["removed"] = removed
    else:
        # ``stamp`` of None defers the decision to apply_migration_stamp().
        migrated["removed"] = {stamp: False} if stamp is not None else {}
    annotations = entry.get("annotations")
    migrated["annotations"] = annotations if isinstance(annotations, list) else []
    return migrated


def migrate_v1(catalog, name, stamp):
    """Convert a version 1 catalog into the native v3 shape."""
    source_id = catalog.get(V1_SOURCE_FIELD)
    if not isinstance(source_id, str) or not source_id:
        raise legacy_error(name, 1, "missing '%s'" % V1_SOURCE_FIELD)
    entries = catalog.get(V1_ENTRIES_FIELD)
    if not isinstance(entries, list):
        raise legacy_error(name, 1, "missing '%s' array" % V1_ENTRIES_FIELD)

    episodes = []
    for index, entry in enumerate(entries):
        where = "entry %d in '%s'" % (index, V1_ENTRIES_FIELD)
        episodes.append(convert_entry(entry, 1, name, where, stamp))

    # Every version 1 entry becomes an episode; the other categories start empty.
    return {
        "version": VERSION,
        "source": v1_source_url(source_id),
        "episodes": episodes,
        "streams": [],
        "clips": [],
    }


def migrate_v2(catalog, name, stamp):
    """Convert a version 2 catalog into the native v3 shape."""
    source = catalog.get("source")
    if not isinstance(source, str):
        raise legacy_error(name, 2, "missing source URL")

    migrated = {"version": VERSION, "source": source}
    for category in CATEGORIES:
        entries = catalog.get(category)
        if not isinstance(entries, list):
            raise legacy_error(name, 2, "missing '%s' array" % category)
        migrated[category] = [
            convert_entry(entry, 2, name, "entry %d in '%s'" % (index, category), stamp)
            for index, entry in enumerate(entries)
        ]
    # Preserve any extra top-level fields the legacy catalog carried.
    for key, value in catalog.items():
        if key not in migrated:
            migrated[key] = value
    return migrated


def apply_migration_stamp(catalog, stamp):
    """Fill in migration-added ``removed`` histories left open by a deferred
    migration, so migration and the operation that triggered it agree on one
    timestamp."""
    for category in CATEGORIES:
        for entry in catalog.get(category) or []:
            if isinstance(entry, dict) and not has_history(entry.get("removed")):
                entry["removed"] = {stamp: False}
    return catalog


def migrate_catalog(catalog, version, name, stamp=None):
    """Return ``catalog`` converted to the native v3 shape (in memory only).

    ``stamp`` is the ISO 8601 timestamp recorded for migration-added ``removed``
    histories.  When it is ``None`` those histories are left empty and the
    caller is expected to close them with ``apply_migration_stamp``.
    """
    if version == VERSION:
        return catalog
    if version == 1:
        return migrate_v1(catalog, name, stamp)
    if version == 2:
        return migrate_v2(catalog, name, stamp)
    raise MvaultError("vault '%s' is invalid: unsupported catalog version %s" % (name, version))



# --------------------------------------------------------------------------
# source fetching
# --------------------------------------------------------------------------

def fetch_source(url):
    try:
        response = urllib.request.urlopen(url)
    except Exception as exc:  # network errors, bad URLs, ...
        raise SourceError(str(exc) or exc.__class__.__name__)
    try:
        raw = response.read()
    except Exception as exc:
        raise SourceError(str(exc) or exc.__class__.__name__)
    finally:
        closer = getattr(response, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass

    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceError("response is not valid UTF-8 (%s)" % exc)
    if not isinstance(raw, str):
        raise SourceError("unexpected response payload")

    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise SourceError("response is not valid JSON (%s)" % exc)
    return validate_source(data)


def validate_source(data):
    """Validate the source document and return ``{category: [entries]}``."""
    if not isinstance(data, dict):
        raise SourceError("response is not a JSON object")

    validators = {
        "id": lambda v: isinstance(v, str),
        "published": lambda v: isinstance(v, str),
        "width": is_int,
        "height": is_int,
        "title": lambda v: isinstance(v, str),
        "description": lambda v: isinstance(v, str),
        "views": is_int,
        "likes": lambda v: v is None or is_int(v),
        "preview": lambda v: isinstance(v, str),
    }

    result = {}
    for category in CATEGORIES:
        items = data.get(category)
        if not isinstance(items, list):
            raise SourceError("missing or malformed '%s' array" % category)
        validated = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                raise SourceError("malformed entry in '%s'" % category)
            for field, check in validators.items():
                if field not in item:
                    raise SourceError("entry in '%s' is missing field '%s'" % (category, field))
                if not check(item[field]):
                    raise SourceError(
                        "entry in '%s' has an invalid value for field '%s'" % (category, field)
                    )
            if item["id"] in seen:
                raise SourceError("duplicate id '%s' in '%s'" % (item["id"], category))
            seen.add(item["id"])
            validated.append(item)
        result[category] = validated
    return result


# --------------------------------------------------------------------------
# sync logic
# --------------------------------------------------------------------------

def new_entry(item, stamp):
    entry = {
        "id": item["id"],
        "published": normalize_published(item["published"]),
        "width": item["width"],
        "height": item["height"],
    }
    for field in SOURCE_TRACKED_FIELDS:
        entry[field] = {stamp: item[field]}
    entry["removed"] = {stamp: False}
    entry["annotations"] = []
    return entry


def update_entry(entry, item, stamp):
    """Append history for tracked fields whose value changed."""
    for field in SOURCE_TRACKED_FIELDS:
        history = entry.get(field)
        if not has_history(history):
            entry[field] = {stamp: item[field]}
            continue
        if not same_value(current_value(history), item[field]):
            history[stamp] = item[field]
    mark_removed(entry, False, stamp)


def mark_removed(entry, removed, stamp):
    history = entry.get("removed")
    if not has_history(history):
        entry["removed"] = {stamp: bool(removed)}
        return
    if current_value(history) is not bool(removed):
        history[stamp] = bool(removed)


def apply_source(catalog, source, stamp):
    for category in CATEGORIES:
        entries = catalog[category]
        by_id = {}
        for entry in entries:
            by_id.setdefault(str(entry.get("id")), entry)

        seen = set()
        for item in source[category]:
            seen.add(item["id"])
            existing = by_id.get(item["id"])
            if existing is None:
                entries.append(new_entry(item, stamp))
            else:
                update_entry(existing, item, stamp)

        for entry in entries:
            if str(entry.get("id")) not in seen:
                mark_removed(entry, True, stamp)

        catalog[category] = sort_entries(entries)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_init(args):
    name = args.name
    vault_dir, catalog_path, _ = catalog_paths(name)
    if os.path.exists(vault_dir):
        raise MvaultError("vault '%s' already exists" % name)
    try:
        os.makedirs(vault_dir)
    except OSError as exc:
        raise MvaultError("could not create vault '%s': %s" % (name, exc))

    catalog = {
        "version": VERSION,
        "source": args.url,
        "episodes": [],
        "streams": [],
        "clips": [],
    }
    write_catalog(name, catalog)
    print("Initialized vault '%s' at %s" % (name, catalog_path))
    return 0


def cmd_sync(args):
    name = args.name
    catalog, version = load_vault(name)
    source = fetch_source(catalog["source"])

    stamp = format_dt(sync_timestamp(catalog))
    if version != VERSION:
        apply_migration_stamp(catalog, stamp)
    apply_source(catalog, source, stamp)
    # Legacy catalogs are migrated in memory above; the write below backs up the
    # original catalog and persists the v3 result.
    write_catalog(name, catalog)

    total = sum(len(catalog[category]) for category in CATEGORIES)
    if version != VERSION:
        print("Migrated vault '%s' from catalog version %d to version %d"
              % (name, version, VERSION))
    print("Synced vault '%s' at %s (%d entries)" % (name, stamp, total))
    return 0


def cmd_migrate(args):
    name = args.name
    catalog, version = load_vault(name, migration_timestamp())
    if version == VERSION:
        print("Vault '%s' is already at catalog version %d" % (name, VERSION))
        return 0
    write_catalog(name, catalog)
    print("Migrated vault '%s' from catalog version %d to version %d"
          % (name, version, VERSION))
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="mvault",
        description="Create local vaults for media-platform metadata and record "
                    "tracked-field history by sync timestamp.  Legacy catalogs "
                    "(versions 1 and 2) are read transparently.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<subcommand>")

    init_parser = subparsers.add_parser(
        "init", help="create a new vault directory with an empty catalog"
    )
    init_parser.add_argument("name", help="vault directory name")
    init_parser.add_argument("url", help="source metadata URL")
    init_parser.set_defaults(func=cmd_init)

    sync_parser = subparsers.add_parser(
        "sync", help="fetch the source and update the vault catalog"
    )
    sync_parser.add_argument("name", help="vault directory name")
    sync_parser.set_defaults(func=cmd_sync)

    migrate_parser = subparsers.add_parser(
        "migrate", help="convert a legacy catalog to the current version on disk"
    )
    migrate_parser.add_argument("name", help="vault directory name")
    migrate_parser.set_defaults(func=cmd_migrate)

    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    if not argv:
        parser.print_usage(sys.stderr)
        print("mvault: error: a subcommand is required", file=sys.stderr)
        return 2

    args = parser.parse_args(argv)
    if getattr(args, "command", None) is None or not hasattr(args, "func"):
        parser.print_usage(sys.stderr)
        print("mvault: error: a subcommand is required", file=sys.stderr)
        return 2

    try:
        return args.func(args)
    except MvaultError as exc:
        print("mvault: error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
