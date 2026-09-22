#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Creates a vault directory holding a ``catalog.json`` and records the history of
tracked fields (title, description, views, likes, preview, removed) keyed by the
timestamp of the sync that observed each value.
"""

import json
import os
import shutil
import sys
from datetime import datetime, timedelta

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"

VERSION = 3
CATEGORIES = ("episodes", "streams", "clips")

STATIC_FIELDS = ("id", "published", "width", "height")
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)

TS_FORMAT = "%Y-%m-%dT%H:%M:%S"

USAGE = """usage: mvault.py <subcommand> [args...]

Local vaults for media-platform metadata.

subcommands:
  init <name> <url>   create a new vault named <name> tracking the source <url>
  sync <name>         fetch the vault source and record tracked-field changes

options:
  -h, --help          show this help message and exit
"""


class MvaultError(Exception):
    """Any failure that should be reported to stderr with a non-zero exit."""


class SourceError(MvaultError):
    """Source metadata fetch failure (network, decoding or schema problem)."""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def is_int(value):
    """True for real integers - booleans are not accepted as integers."""
    return isinstance(value, int) and not isinstance(value, bool)


def format_timestamp(moment):
    return moment.strftime(TS_FORMAT)


def parse_timestamp(text):
    """Parse a history key / published value into a naive datetime.

    Accepts full ISO 8601 datetimes (with or without a timezone suffix) and
    date-only text, which normalizes to a ``00:00:00`` time component.
    """
    if not isinstance(text, str):
        raise ValueError("not a datetime string")

    raw = text.strip()
    if not raw:
        raise ValueError("empty datetime string")

    candidate = raw
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"

    try:
        moment = datetime.fromisoformat(candidate)
    except ValueError:
        moment = None
        for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                        "%Y-%m-%dT%H:%M", "%Y/%m/%d"):
            try:
                moment = datetime.strptime(candidate, pattern)
                break
            except ValueError:
                continue
        if moment is None:
            raise ValueError("unrecognized datetime text: %r" % text)

    if moment.tzinfo is not None:
        moment = moment.replace(tzinfo=None)
    return moment.replace(microsecond=0)


def normalize_published(text):
    """Normalize a published value to ``YYYY-MM-DDTHH:MM:SS``."""
    try:
        return format_timestamp(parse_timestamp(text))
    except ValueError:
        # Unparseable text is kept verbatim so no information is lost.
        return text


def history_keys(history):
    """History keys sorted chronologically."""
    if not isinstance(history, dict):
        return []

    def key(item):
        try:
            return (0, parse_timestamp(item), item)
        except ValueError:
            return (1, datetime.min, item)

    return sorted(history.keys(), key=key)


def latest_value(history, default=None):
    keys = history_keys(history)
    if not keys:
        return default
    return history[keys[-1]]


def latest_moment(history):
    """Newest timestamp in a history object, or ``None`` when empty."""
    newest = None
    if not isinstance(history, dict):
        return None
    for raw in history:
        try:
            moment = parse_timestamp(raw)
        except ValueError:
            continue
        if newest is None or moment > newest:
            newest = moment
    return newest


# --------------------------------------------------------------------------- #
# vault io
# --------------------------------------------------------------------------- #

def catalog_path(name):
    return os.path.join(name, CATALOG_NAME)


def backup_path(name):
    return os.path.join(name, BACKUP_NAME)


def load_catalog(name):
    """Load and validate the catalog of an existing vault."""
    path = catalog_path(name)
    if not os.path.isdir(name):
        raise MvaultError("vault %r does not exist" % name)
    if not os.path.isfile(path):
        raise MvaultError("vault %r is invalid: missing %s" % (name, CATALOG_NAME))

    try:
        with open(path, "r", encoding="utf-8") as handle:
            catalog = json.load(handle)
    except (OSError, ValueError) as exc:
        raise MvaultError("vault %r is invalid: unreadable %s (%s)"
                          % (name, CATALOG_NAME, exc))

    if not isinstance(catalog, dict):
        raise MvaultError("vault %r is invalid: %s is not a JSON object"
                          % (name, CATALOG_NAME))
    if not isinstance(catalog.get("source"), str):
        raise MvaultError("vault %r is invalid: missing source URL" % name)
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise MvaultError("vault %r is invalid: missing %r category"
                              % (name, category))
    for entry in all_entries(catalog):
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise MvaultError("vault %r is invalid: malformed entry" % name)
    return catalog


def all_entries(catalog):
    for category in CATEGORIES:
        for entry in catalog.get(category) or []:
            yield entry


def write_catalog(name, catalog):
    """Write the catalog, backing up any pre-existing copy byte-for-byte."""
    path = catalog_path(name)
    if os.path.isfile(path):
        shutil.copyfile(path, backup_path(name))

    payload = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload)


# --------------------------------------------------------------------------- #
# source fetching
# --------------------------------------------------------------------------- #

def fetch_source(url):
    """HTTP GET the source URL and return the decoded JSON document."""
    if not isinstance(url, str) or not url:
        raise SourceError("source metadata fetch failed: missing source URL")

    try:
        body = http_get(url)
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError("source metadata fetch failed for %s: %s" % (url, exc))

    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceError("source metadata fetch failed for %s: %s" % (url, exc))

    try:
        return json.loads(body)
    except ValueError as exc:
        raise SourceError("source metadata fetch failed for %s: invalid JSON (%s)"
                          % (url, exc))


def http_get(url):
    """Perform the GET, preferring ``requests`` when it is installed."""
    try:
        import requests  # noqa: WPS433 (optional dependency)
    except ImportError:
        requests = None

    if requests is not None:
        response = requests.get(url)
        raise_for_status = getattr(response, "raise_for_status", None)
        if callable(raise_for_status):
            raise_for_status()
        text = getattr(response, "text", None)
        if text is not None:
            return text
        return response.content

    from urllib.request import urlopen

    with urlopen(url) as response:
        return response.read()


def parse_source(document):
    """Validate the source document and return ``{category: [entry, ...]}``."""
    if not isinstance(document, dict):
        raise SourceError("source metadata fetch failed: "
                          "expected a JSON object at the document root")

    parsed = {}
    for category in CATEGORIES:
        items = document.get(category)
        if not isinstance(items, list):
            raise SourceError("source metadata fetch failed: "
                              "missing or invalid %r array" % category)
        parsed[category] = [validate_source_entry(item, category) for item in items]
    return parsed


def validate_source_entry(item, category):
    """Validate one source entry, returning a normalized copy."""
    if not isinstance(item, dict):
        raise SourceError("source metadata fetch failed: "
                          "malformed entry in %r (not an object)" % category)

    def fail(field, reason):
        raise SourceError("source metadata fetch failed: malformed entry %r in %r: "
                          "field %r %s" % (item.get("id"), category, field, reason))

    checks = (
        ("id", lambda v: isinstance(v, str), "must be a string"),
        ("published", lambda v: isinstance(v, str), "must be a string"),
        ("width", is_int, "must be an integer"),
        ("height", is_int, "must be an integer"),
        ("title", lambda v: isinstance(v, str), "must be a string"),
        ("description", lambda v: isinstance(v, str), "must be a string"),
        ("views", is_int, "must be an integer"),
        ("likes", lambda v: v is None or is_int(v), "must be an integer or null"),
        ("preview", lambda v: isinstance(v, str), "must be a string"),
    )
    for field, predicate, reason in checks:
        if field not in item:
            fail(field, "is missing")
        if not predicate(item[field]):
            fail(field, reason)

    entry = {
        "id": item["id"],
        "published": normalize_published(item["published"]),
        "width": item["width"],
        "height": item["height"],
    }
    for field in SOURCE_TRACKED_FIELDS:
        entry[field] = item[field]
    return entry


# --------------------------------------------------------------------------- #
# sync logic
# --------------------------------------------------------------------------- #

def sync_timestamp(catalog, now=None):
    """The timestamp used for every history entry appended by this sync.

    Always strictly newer than every timestamp already recorded in the catalog,
    so repeated syncs within the same second still advance.
    """
    moment = (now or datetime.now()).replace(microsecond=0)
    newest = None
    for entry in all_entries(catalog):
        for field in TRACKED_FIELDS:
            candidate = latest_moment(entry.get(field))
            if candidate is not None and (newest is None or candidate > newest):
                newest = candidate
    if newest is not None and moment <= newest:
        moment = newest + timedelta(seconds=1)
    return format_timestamp(moment)


def record(entry, field, value, stamp):
    """Append ``value`` to a tracked field when it differs from the current one."""
    history = entry.get(field)
    if not isinstance(history, dict):
        history = {}
        entry[field] = history

    if history:
        current = latest_value(history)
        if current == value and type(current) is type(value):
            return False

    history[stamp] = value
    return True


def sort_entries(entries):
    """Newest ``published`` first, ties broken by lexicographically smaller id."""
    ordered = sorted(entries, key=lambda entry: str(entry.get("id") or ""))
    return sorted(ordered, key=lambda entry: str(entry.get("published") or ""),
                  reverse=True)


def apply_source(catalog, source, stamp):
    """Merge fetched source entries into the catalog in place."""
    for category in CATEGORIES:
        entries = catalog.get(category) or []
        by_id = {}
        for entry in entries:
            by_id.setdefault(entry["id"], entry)

        seen = set()
        for item in source[category]:
            seen.add(item["id"])
            entry = by_id.get(item["id"])
            if entry is None:
                entry = {field: item[field] for field in STATIC_FIELDS}
                entries.append(entry)
                by_id[item["id"]] = entry
            for field in SOURCE_TRACKED_FIELDS:
                record(entry, field, item[field], stamp)
            record(entry, "removed", False, stamp)

        for entry in entries:
            if entry["id"] not in seen:
                record(entry, "removed", True, stamp)

        catalog[category] = sort_entries(entries)


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def command_init(args):
    if len(args) != 2:
        raise MvaultError("usage: mvault.py init <name> <url>")
    name, url = args

    if os.path.exists(name):
        raise MvaultError("cannot create vault %r: %s already exists" % (name, name))

    try:
        os.makedirs(name)
    except OSError as exc:
        raise MvaultError("cannot create vault %r: %s" % (name, exc))

    catalog = {"version": VERSION, "source": url,
               "episodes": [], "streams": [], "clips": []}
    write_catalog(name, catalog)
    print("initialized vault %s tracking %s" % (name, url))
    return 0


def command_sync(args):
    if len(args) != 1:
        raise MvaultError("usage: mvault.py sync <name>")
    name = args[0]

    catalog = load_catalog(name)
    source = parse_source(fetch_source(catalog["source"]))

    catalog["version"] = VERSION
    stamp = sync_timestamp(catalog)
    apply_source(catalog, source, stamp)
    write_catalog(name, catalog)

    total = sum(len(catalog[category]) for category in CATEGORIES)
    print("synced vault %s at %s (%d entries)" % (name, stamp, total))
    return 0


COMMANDS = {"init": command_init, "sync": command_sync}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv:
        sys.stderr.write(USAGE)
        return 2

    subcommand, args = argv[0], argv[1:]

    if subcommand in ("-h", "--help", "help"):
        sys.stdout.write(USAGE)
        return 0

    handler = COMMANDS.get(subcommand)
    if handler is None:
        sys.stderr.write("error: unknown subcommand %r\n\n" % subcommand)
        sys.stderr.write(USAGE)
        return 2

    if any(arg in ("-h", "--help") for arg in args):
        sys.stdout.write(USAGE)
        return 0

    try:
        return handler(args)
    except MvaultError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
