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
from datetime import datetime, timedelta, timezone

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"

VERSION = 3
SUPPORTED_VERSIONS = (1, 2, 3)
CATEGORIES = ("episodes", "streams", "clips")

# A version 1 catalog stores a short platform identifier instead of a full URL.
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/%s"

STATIC_FIELDS = ("id", "published", "width", "height")
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)

TS_FORMAT = "%Y-%m-%dT%H:%M:%S"

USAGE = """usage: mvault.py <subcommand> [args...]

Local vaults for media-platform metadata.

subcommands:
  init <name> <url>   create a new vault named <name> tracking the source <url>
  sync <name>         fetch the vault source and record tracked-field changes
  migrate <name>      convert a legacy (version 1 or 2) catalog to version 3

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
# legacy catalog migration
# --------------------------------------------------------------------------- #

HISTORY_VALUE_CHECKS = {
    "title": (lambda v: isinstance(v, str), "must be a string"),
    "description": (lambda v: isinstance(v, str), "must be a string"),
    "views": (is_int, "must be an integer"),
    "likes": (lambda v: v is None or is_int(v), "must be an integer or null"),
    "preview": (lambda v: isinstance(v, str), "must be a string"),
}


def epoch_key_to_iso(key):
    """Convert a version 1 UNIX-epoch history key to ``YYYY-MM-DDTHH:MM:SS`` UTC."""
    if not isinstance(key, str):
        raise ValueError("history key is not a string")

    raw = key.strip()
    if not raw:
        raise ValueError("empty history key")

    try:
        seconds = int(raw, 10)
    except ValueError:
        raise ValueError("%r is not UNIX epoch seconds" % key)

    try:
        moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        raise ValueError("%r is out of range for UNIX epoch seconds" % key)
    return format_timestamp(moment.replace(tzinfo=None))


def migration_timestamp(now=None):
    """ISO 8601 timestamp stamped on history entries added by a migration."""
    return format_timestamp((now or datetime.now()).replace(microsecond=0))


def migrate_history(history, field, version, fail):
    """Return a version 3 history object for one legacy tracked field."""
    if not isinstance(history, dict):
        fail(field, "must be a history object")

    predicate, reason = HISTORY_VALUE_CHECKS[field]
    converted = []
    for key, value in history.items():
        if version == 1:
            try:
                stamp = epoch_key_to_iso(key)
            except ValueError as exc:
                fail(field, "has an invalid history key (%s)" % exc)
        else:
            try:
                parse_timestamp(key)
            except ValueError as exc:
                fail(field, "has an invalid history key (%s)" % exc)
            stamp = key
        if not predicate(value):
            fail(field, "has a history value that %s (got %r)" % (reason, value))
        converted.append((stamp, value))

    if version == 1:
        # Epoch keys order numerically; sort so the converted keys stay
        # chronological and any duplicates resolve to the newest observation.
        converted.sort(key=lambda item: (parse_timestamp(item[0]), item[0]))
    return dict(converted)


def migrate_entry(entry, category, version, stamp, vault):
    """Return a version 3 copy of one version 1 or version 2 entry."""
    if not isinstance(entry, dict):
        raise MvaultError("vault %r is invalid: malformed version %d entry in %r "
                          "(not an object)" % (vault, version, category))

    def fail(field, reason):
        raise MvaultError("vault %r is invalid: malformed version %d entry %r in %r: "
                          "field %r %s"
                          % (vault, version, entry.get("id"), category, field, reason))

    static_checks = (
        ("id", lambda v: isinstance(v, str), "must be a string"),
        ("published", lambda v: isinstance(v, str), "must be a string"),
        ("width", is_int, "must be an integer"),
        ("height", is_int, "must be an integer"),
    )
    for field, predicate, reason in static_checks:
        if field not in entry:
            fail(field, "is missing")
        if not predicate(entry[field]):
            fail(field, reason)

    migrated = dict(entry)
    for field in SOURCE_TRACKED_FIELDS:
        if field not in entry:
            fail(field, "is missing")
        migrated[field] = migrate_history(entry[field], field, version, fail)

    # Legacy entries carry neither of these; both are mandatory in version 3.
    if "removed" not in migrated:
        migrated["removed"] = {stamp: False}
    if "annotations" not in migrated:
        migrated["annotations"] = []
    return migrated


def legacy_categories(vault, catalog, version):
    """Return ``{category: [raw entry, ...]}`` for a legacy catalog."""
    if version == 1:
        entries = catalog.get("entries")
        if entries is None:
            entries = []
        if not isinstance(entries, list):
            raise MvaultError("vault %r is invalid: version 1 %r is not a list"
                              % (vault, "entries"))
        # Every version 1 entry migrates into the episodes category.
        return {"episodes": entries, "streams": [], "clips": []}

    raw = {}
    for category in CATEGORIES:
        items = catalog.get(category)
        if items is None:
            items = []
        if not isinstance(items, list):
            raise MvaultError("vault %r is invalid: version %d %r category is not "
                              "a list" % (vault, version, category))
        raw[category] = items
    return raw


def legacy_source(vault, catalog, version):
    """Resolve the full source URL of a legacy catalog."""
    if version == 1:
        source_id = catalog.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise MvaultError("vault %r is invalid: version 1 catalog is missing "
                              "source_id" % vault)
        return V1_SOURCE_TEMPLATE % source_id

    source = catalog.get("source")
    if not isinstance(source, str):
        raise MvaultError("vault %r is invalid: missing source URL" % vault)
    return source


def migrate_catalog(vault, catalog, version, stamp=None):
    """Return a version 3 catalog built from a version 1 or 2 catalog."""
    stamp = stamp or migration_timestamp()

    source = legacy_source(vault, catalog, version)
    raw = legacy_categories(vault, catalog, version)

    migrated = {"version": VERSION, "source": source}
    for category in CATEGORIES:
        migrated[category] = [migrate_entry(item, category, version, stamp, vault)
                              for item in raw[category]]

    # Anything else the legacy catalog carried is local-only data; keep it.
    replaced = set(CATEGORIES) | {"version", "source", "source_id", "entries"}
    for key, value in catalog.items():
        if key not in replaced:
            migrated[key] = value
    return migrated


def catalog_version(vault, catalog):
    """Validate and return the ``version`` field of a catalog document."""
    if "version" not in catalog:
        raise MvaultError("vault %r is invalid: %s is missing the version field"
                          % (vault, CATALOG_NAME))

    version = catalog["version"]
    if not is_int(version):
        raise MvaultError("vault %r is invalid: catalog version must be an integer "
                          "(got %r)" % (vault, version))
    if version not in SUPPORTED_VERSIONS:
        raise MvaultError("vault %r is invalid: unsupported catalog version %d "
                          "(supported versions: %s)"
                          % (vault, version,
                             ", ".join(str(known) for known in SUPPORTED_VERSIONS)))
    return version


# --------------------------------------------------------------------------- #
# vault io
# --------------------------------------------------------------------------- #

def catalog_path(name):
    return os.path.join(name, CATALOG_NAME)


def backup_path(name):
    return os.path.join(name, BACKUP_NAME)


def load_catalog(name):
    """Load the catalog of an existing vault as a version 3 document.

    Returns ``(catalog, version)`` where ``catalog`` is always in the native
    version 3 shape and ``version`` is the version found on disk.  Legacy
    catalogs are migrated in memory only - nothing is written here, so
    read-only commands never rewrite ``catalog.json``.
    """
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

    version = catalog_version(name, catalog)
    if version != VERSION:
        catalog = migrate_catalog(name, catalog, version)

    if not isinstance(catalog.get("source"), str):
        raise MvaultError("vault %r is invalid: missing source URL" % name)
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise MvaultError("vault %r is invalid: missing %r category"
                              % (name, category))
    for entry in all_entries(catalog):
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise MvaultError("vault %r is invalid: malformed entry" % name)
    return catalog, version


def all_entries(catalog):
    for category in CATEGORIES:
        for entry in catalog.get(category) or []:
            yield entry


def write_catalog(name, catalog):
    """Write the catalog, backing up any pre-existing copy byte-for-byte.

    The backup is taken first, so a failure to write it aborts before the
    on-disk ``catalog.json`` is touched.
    """
    path = catalog_path(name)
    if os.path.isfile(path):
        try:
            shutil.copyfile(path, backup_path(name))
        except OSError as exc:
            raise MvaultError("vault %r: cannot write %s (%s)"
                              % (name, BACKUP_NAME, exc))

    payload = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload)
    except OSError as exc:
        raise MvaultError("vault %r: cannot write %s (%s)"
                          % (name, CATALOG_NAME, exc))


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

    # A legacy catalog is migrated in memory here; the version 3 result is what
    # gets synced and written back below (the backup keeps the original).
    catalog, _version = load_catalog(name)
    source = parse_source(fetch_source(catalog["source"]))

    catalog["version"] = VERSION
    stamp = sync_timestamp(catalog)
    apply_source(catalog, source, stamp)
    write_catalog(name, catalog)

    total = sum(len(catalog[category]) for category in CATEGORIES)
    print("synced vault %s at %s (%d entries)" % (name, stamp, total))
    return 0


def command_migrate(args):
    if len(args) != 1:
        raise MvaultError("usage: mvault.py migrate <name>")
    name = args[0]

    catalog, version = load_catalog(name)
    if version == VERSION:
        print("vault %s is already at version %d" % (name, VERSION))
        return 0

    write_catalog(name, catalog)
    print("migrated vault %s from version %d to version %d"
          % (name, version, VERSION))
    return 0


COMMANDS = {"init": command_init, "sync": command_sync,
            "migrate": command_migrate}


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
