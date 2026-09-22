#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Creates a vault directory holding a ``catalog.json`` and records the history of
tracked fields keyed by sync timestamp.
"""

import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"

VERSION = 3
CATEGORIES = ("episodes", "streams", "clips")

STATIC_FIELDS = ("id", "published", "width", "height")
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)

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


def load_catalog(name):
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
    if catalog.get("version") != VERSION or not is_int(catalog.get("version")):
        raise MvaultError("vault '%s' is invalid: unsupported catalog version" % name)
    if not isinstance(catalog.get("source"), str):
        raise MvaultError("vault '%s' is invalid: missing source URL" % name)
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise MvaultError("vault '%s' is invalid: missing '%s' array" % (name, category))
        for entry in catalog[category]:
            if not isinstance(entry, dict):
                raise MvaultError("vault '%s' is invalid: malformed '%s' entry" % (name, category))
    return catalog


def write_catalog(name, catalog):
    """Back up the existing catalog byte-for-byte, then write the new one."""
    _, catalog_path, backup_path = catalog_paths(name)
    if os.path.isfile(catalog_path):
        shutil.copyfile(catalog_path, backup_path)
    payload = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    with open(catalog_path, "w", encoding="utf-8") as handle:
        handle.write(payload)


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
    catalog = load_catalog(name)
    source = fetch_source(catalog["source"])

    stamp = format_dt(sync_timestamp(catalog))
    apply_source(catalog, source, stamp)
    write_catalog(name, catalog)

    total = sum(len(catalog[category]) for category in CATEGORIES)
    print("Synced vault '%s' at %s (%d entries)" % (name, stamp, total))
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
