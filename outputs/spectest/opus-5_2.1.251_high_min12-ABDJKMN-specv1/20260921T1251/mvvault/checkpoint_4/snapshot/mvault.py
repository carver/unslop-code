#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Creates a vault directory holding a ``catalog.json`` and records the history of
tracked fields (``title``, ``description``, ``views``, ``likes``, ``preview``
and the local-only ``removed``) keyed by sync timestamp.

Usage::

    python mvault.py init <name> <url>
    python mvault.py sync <name> [options]
    python mvault.py migrate <name>
    python mvault.py digest <name>
    python mvault.py serve [<name>] [--host=<host>] [--port=<port>]

Legacy catalogs (version 1 and version 2) are loaded transparently: every
command migrates them to the version 3 shape in memory, and the commands that
write a catalog persist the migrated form. ``digest`` is the exception: it is
format-aware and reads v1, v2 and v3 catalogs directly, without migrating.

``serve`` starts a local browser viewer on ``127.0.0.1:8840`` that reads v1,
v2 and v3 vaults as they are, without migrating them, and ``digest`` and the
post-sync summary append viewer links to every changed-entry line.

``sync`` runs in two phases - a metadata phase that fetches the source and
persists the catalog, and a download phase that retrieves media and preview
files into ``<vault>/media/`` and ``<vault>/previews/``.
"""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import re
import shutil
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CATALOG_VERSION = 3
SUPPORTED_VERSIONS = (1, 2, 3)
CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"

# | `source_id` | Convert to `source` using
#   `https://media.example.com/channel/<source_id>` |
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/{source_id}"

CATEGORIES = ("episodes", "streams", "clips")
STATIC_FIELDS = ("id", "published", "width", "height")
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)

FETCH_FAILURE = "Source metadata fetch failure"

PROG = "mvault.py"

# | Media | ... | `<vault>/media/` | ... | Preview | ... | `<vault>/previews/` |
MEDIA_DIRNAME = "media"
PREVIEW_DIRNAME = "previews"
MEDIA_PATH_SEGMENT = "media"
PREVIEW_PATH_SEGMENT = "preview"

# | Partial artifacts | Stale partial-download artifacts must not block a later
#   successful download |
PARTIAL_SUFFIX = ".part"
PARTIAL_SUFFIXES = (".part", ".partial", ".tmp", ".download", ".crdownload")

# | Transient download failure | Retry, then warn to stderr after retries
#   exhausted; continue with remaining entries |
DOWNLOAD_ATTEMPTS = 3
TRANSIENT_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504, 507, 509})

# | Media extension without override | Derive from HTTP `Content-Type` |
DEFAULT_EXTENSION = "bin"
CONTENT_TYPE_EXTENSIONS = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/mpeg": "mpeg",
    "video/quicktime": "mov",
    "video/x-matroska": "mkv",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "application/octet-stream": DEFAULT_EXTENSION,
    "application/json": "json",
    "text/plain": "txt",
}
EXTENSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# | Category grouping | v1: single `Entries` group; v2/v3: per-category |
V1_GROUP_LABEL = "Entries"
CATEGORY_LABELS = {"episodes": "Episodes", "streams": "Streams", "clips": "Clips"}

# | Priority | `1` Removals (v3 only) | `2` Additions | `3` Field updates |
GROUP_REMOVALS = "Removals"
GROUP_ADDITIONS = "Additions"
GROUP_UPDATES = "Field updates"
DIGEST_GROUP_ORDER = (GROUP_REMOVALS, GROUP_ADDITIONS, GROUP_UPDATES)

# | No notable changes anywhere | Indicate that no notable changes were found |
NO_CHANGES_TEXT = "No notable changes found."
# | Reappearance after removal (v3 only) | Indicate reappearance alongside any
#   other changed fields |
REAPPEARED_LABEL = "reappeared"

# | Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>` |
# | Default scheme | `http://` | | Default host | `127.0.0.1` |
# | Default port | `8840` |
VIEWER_SCHEME = "http"
VIEWER_HOST = "127.0.0.1"
VIEWER_PORT = 8840

# | v1 | `entries` | | v2 | `episodes`, `streams`, `clips` | | v3 | same as v2 |
V1_CATEGORY = "entries"
VIEWER_CATEGORIES = {1: (V1_CATEGORY,), 2: CATEGORIES, 3: CATEGORIES}
# | v1 | `/catalog/<name>/entries` | | v2 | `/catalog/<name>/episodes` | ...
VIEWER_DEFAULT_CATEGORY = {1: V1_CATEGORY, 2: "episodes", 3: "episodes"}

# Landing-page state: visited vaults survive both the browser session and the
# server process, so they are kept in a cookie *and* in a small state file next
# to the vaults being served.
RECENT_STATE_NAME = ".mvault-viewer.json"
RECENT_COOKIE = "mvault_recent"
RECENT_LIMIT = 24
COOKIE_MAX_AGE = 60 * 60 * 24 * 365


EPOCH_KEY_RE = re.compile(r"^-?\d+$")
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
    """Write the catalog, backing up any existing catalog first.

    A backup that cannot be written aborts the write, leaving the existing
    ``catalog.json`` intact.
    """
    path = catalog_path(vault_dir)
    if path.exists():
        try:
            shutil.copyfile(path, backup_path(vault_dir))
        except OSError as exc:
            raise MvaultError(f"could not write {BACKUP_NAME}: {exc}")

    text = serialize_catalog(catalog)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise MvaultError(f"could not write {CATALOG_NAME}: {exc}")


def load_vault(name):
    """Load the vault ``name``, migrating a legacy catalog in memory.

    Returns ``(vault_dir, catalog, version)`` where ``catalog`` is always in the
    version 3 shape and ``version`` is the version found on disk. Nothing is
    written: a read-only command leaves a v1 or v2 ``catalog.json`` untouched.
    """
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

    try:
        version = detect_version(catalog)
        if version != CATALOG_VERSION:
            catalog = migrate_catalog(catalog, version, migration_timestamp())
    except MvaultError as exc:
        raise MvaultError(f"vault {name!r} is invalid: {exc}")

    problem = validate_catalog(catalog)
    if problem is not None:
        raise MvaultError(f"vault {name!r} is invalid: {problem}")

    return vault_dir, catalog, version


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
# multi-version loading
#
# | Version detection | Read `version` field from `catalog.json` |
# --------------------------------------------------------------------------

def detect_version(catalog):
    """Return the catalog version, or raise for an unusable ``version`` field."""
    if not isinstance(catalog, dict):
        raise MvaultError(f"{CATALOG_NAME} must contain a JSON object")
    if "version" not in catalog:
        raise MvaultError(f"{CATALOG_NAME} is missing 'version'")

    version = catalog["version"]
    if not is_integer(version):
        raise MvaultError(
            f"catalog 'version' must be an integer, got {version!r}")
    if version not in SUPPORTED_VERSIONS:
        supported = ", ".join(str(v) for v in SUPPORTED_VERSIONS)
        raise MvaultError(
            f"unsupported catalog version {version} "
            f"(supported versions: {supported})")
    return version


def migration_timestamp(now=None):
    """Timestamp stamped on migration-added ``removed`` history."""
    return format_datetime((now or datetime.now()).replace(microsecond=0))


def v1_source_url(source_id):
    """| v1 `source_id` conversion | `https://media.example.com/channel/<id>` |"""
    return V1_SOURCE_TEMPLATE.format(source_id=source_id)


def epoch_key_to_iso(key, where, field):
    """Convert a UNIX-epoch-seconds key to `YYYY-MM-DDTHH:MM:SS` in UTC."""
    if not is_string(key) or not EPOCH_KEY_RE.match(key):
        raise MvaultError(
            f"malformed entry {where}: {field!r} history key {key!r} is not "
            f"UNIX epoch seconds")
    try:
        moment = datetime.fromtimestamp(int(key), tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise MvaultError(
            f"malformed entry {where}: {field!r} history key {key!r} is not a "
            f"usable timestamp: {exc}")
    return format_datetime(moment.replace(tzinfo=None))


HISTORY_VALUE_CHECKS = (
    ("title", is_string, "a string"),
    ("description", is_string, "a string"),
    ("views", is_integer, "an integer"),
    ("likes", lambda value: value is None or is_integer(value), "an integer or null"),
    ("preview", is_string, "a string"),
)

STATIC_FIELD_CHECKS = (
    ("id", is_string, "a string"),
    ("published", is_string, "a string"),
    ("width", is_integer, "an integer"),
    ("height", is_integer, "an integer"),
)


def validate_legacy_entry(entry, where, epoch_keys):
    """Raise for malformed v1/v2 entry data."""

    def bad(detail):
        raise MvaultError(f"malformed entry {where}: {detail}")

    if not isinstance(entry, dict):
        bad("must be a JSON object")

    for field, check, expected in STATIC_FIELD_CHECKS:
        if field not in entry:
            bad(f"missing {field!r}")
        if not check(entry[field]):
            bad(f"{field!r} must be {expected}")

    for field, check, expected in HISTORY_VALUE_CHECKS:
        if field not in entry:
            bad(f"missing {field!r}")
        history = entry[field]
        if not isinstance(history, dict):
            bad(f"{field!r} must be a history object")
        for key, value in history.items():
            if not is_string(key):
                bad(f"{field!r} history key {key!r} must be a string")
            if epoch_keys and not EPOCH_KEY_RE.match(key):
                bad(f"{field!r} history key {key!r} is not UNIX epoch seconds")
            if not check(value):
                bad(f"{field!r} history value at {key!r} must be {expected}")

    if "annotations" in entry and not isinstance(entry["annotations"], list):
        bad("'annotations' must be an array")


def migrate_legacy_entry(entry, where, stamp, epoch_keys):
    """v1/v2 entry -> v3 entry: re-keyed history plus `removed`/`annotations`."""
    validate_legacy_entry(entry, where, epoch_keys)

    migrated = dict(entry)
    if epoch_keys:
        for field in SOURCE_TRACKED_FIELDS:
            migrated[field] = {
                epoch_key_to_iso(key, where, field): value
                for key, value in entry[field].items()
            }
    migrated["removed"] = {stamp: False}
    if not isinstance(migrated.get("annotations"), list):
        migrated["annotations"] = []
    return migrated


def migrate_v1_catalog(catalog, stamp):
    """Version 1 to version 3."""
    source_id = catalog.get("source_id")
    if not is_string(source_id):
        raise MvaultError("version 1 catalog has a missing or non-string 'source_id'")

    entries = catalog.get("entries", [])
    if not isinstance(entries, list):
        raise MvaultError("version 1 catalog 'entries' must be an array")

    episodes = [
        migrate_legacy_entry(entry, f"entries[{index}]", stamp, epoch_keys=True)
        for index, entry in enumerate(entries)
    ]
    return {
        "version": CATALOG_VERSION,
        "source": v1_source_url(source_id),
        "episodes": episodes,
        "streams": [],
        "clips": [],
    }


def migrate_v2_catalog(catalog, stamp):
    """Version 2 to version 3."""
    source = catalog.get("source")
    if not is_string(source):
        raise MvaultError("version 2 catalog has a missing or non-string 'source'")

    migrated = {"version": CATALOG_VERSION, "source": source}
    for category in CATEGORIES:
        entries = catalog.get(category, [])
        if not isinstance(entries, list):
            raise MvaultError(f"version 2 catalog '{category}' must be an array")
        migrated[category] = [
            migrate_legacy_entry(entry, f"{category}[{index}]", stamp, epoch_keys=False)
            for index, entry in enumerate(entries)
        ]
    return migrated


def migrate_catalog(catalog, version, stamp):
    """Return the version 3 form of ``catalog`` (a v3 catalog is returned as-is)."""
    if version == 1:
        return migrate_v1_catalog(catalog, stamp)
    if version == 2:
        return migrate_v2_catalog(catalog, stamp)
    return catalog


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
    # | Entries created by `sync` | Written in v3 shape, with `annotations` as `[]` |
    entry["annotations"] = []
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
    """Apply source metadata; return ``(counts, changes)``.

    ``changes`` holds ``(category, entry)`` for every entry this sync added,
    removed or updated, in category order and then catalog order - the order
    the post-sync summary lists them in.
    """
    counts = {"new": 0, "changed": 0, "removed": 0, "restored": 0}
    touched = {category: set() for category in CATEGORIES}

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
                touched[category].add(entry_id)
                continue
            was_removed = current_value(existing, "removed") is True
            if update_entry(existing, source_entry, stamp):
                counts["restored" if was_removed else "changed"] += 1
                touched[category].add(entry_id)

        for entry in entries:
            if entry["id"] not in source_by_id and mark_removed(entry, stamp):
                counts["removed"] += 1
                touched[category].add(entry["id"])

        sort_entries(entries)

    changes = [(category, entry)
               for category in CATEGORIES
               for entry in catalog[category]
               if entry["id"] in touched[category]]
    return counts, changes


# --------------------------------------------------------------------------
# download phase
#
# | Download phase | Retrieve media and preview files after metadata phase |
# --------------------------------------------------------------------------

class DownloadFailure(Exception):
    """One asset could not be downloaded.

    ``transient`` marks failures worth retrying (5xx, throttling, socket
    errors); everything else is permanent for this run.
    """

    def __init__(self, detail, transient=False):
        super().__init__(detail)
        self.transient = transient


def warn(message, stream=None):
    """| Permanent download failure | Warning to stderr; ... |"""
    print(f"{PROG}: warning: {message}", file=stream or sys.stderr)


def normalize_format(text):
    """The `--format` override, or ``None`` when it is absent or empty."""
    if not is_string(text):
        return None
    value = text.strip().lstrip(".")
    return value or None


def content_type_extension(content_type):
    """| Media extension without override | Derive from HTTP `Content-Type` |"""
    if not is_string(content_type):
        return DEFAULT_EXTENSION
    main = content_type.split(";")[0].strip().lower()
    if not main:
        return DEFAULT_EXTENSION
    if main in CONTENT_TYPE_EXTENSIONS:
        return CONTENT_TYPE_EXTENSIONS[main]
    guessed = mimetypes.guess_extension(main)
    if guessed:
        return guessed.lstrip(".")
    # `video/x-flv` -> `flv`, `image/svg+xml` -> `svg`
    subtype = main.partition("/")[2].split("+")[0]
    if subtype.startswith("x-"):
        subtype = subtype[2:]
    if subtype and EXTENSION_RE.match(subtype):
        return subtype
    return DEFAULT_EXTENSION


def join_source(source, *parts):
    """`<source>/media/<entry_id>` and friends."""
    base = source.rstrip("/") if is_string(source) else ""
    return "/".join([base] + [str(part) for part in parts])


def is_partial_name(name):
    """| Candidate selection | ... apart from partial downloads |"""
    if name.startswith("."):
        return True
    lowered = name.lower()
    return any(lowered.endswith(suffix) for suffix in PARTIAL_SUFFIXES)


def stored_names(directory):
    try:
        return [item.name for item in Path(directory).iterdir() if item.is_file()]
    except OSError:
        return []


def has_asset(directory, entry_id):
    """| ... | A file matches if the name contains entry `id` ... |"""
    return any(entry_id in name and not is_partial_name(name)
               for name in stored_names(directory))


def http_download(url):
    """GET ``url``; return ``(bytes, content type)`` or raise DownloadFailure."""
    try:
        response = urllib.request.urlopen(url)
    except urllib.error.HTTPError as exc:
        transient = exc.code in TRANSIENT_STATUSES or exc.code >= 500
        raise DownloadFailure(f"HTTP {exc.code} from {url}", transient=transient)
    except urllib.error.URLError as exc:
        raise DownloadFailure(f"could not reach {url}: {exc.reason}",
                              transient=True)
    except Exception as exc:  # bad URL, socket errors, ...
        raise DownloadFailure(f"could not fetch {url}: {exc}", transient=True)

    try:
        data = response.read()
        headers = getattr(response, "headers", None)
        content_type = headers.get("Content-Type") if headers is not None else None
    except Exception as exc:
        raise DownloadFailure(f"could not read {url}: {exc}", transient=True)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    return data, content_type


def download_bytes(url, attempts=DOWNLOAD_ATTEMPTS):
    """| Transient download failure | Retry, then warn ... after retries exhausted |"""
    failure = None
    for _attempt in range(max(1, attempts)):
        try:
            return http_download(url)
        except DownloadFailure as exc:
            if not exc.transient:
                raise
            failure = exc
    raise failure


def store_asset(directory, entry_id, data, extension):
    """Write through a partial artifact, then rename it into place."""
    directory = Path(directory)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DownloadFailure(f"could not create {directory}: {exc}")

    partial = directory / f"{entry_id}{PARTIAL_SUFFIX}"
    name = f"{entry_id}.{extension}" if extension else entry_id
    final = directory / name
    try:
        partial.write_bytes(data)
        os.replace(partial, final)
    except OSError as exc:
        try:
            partial.unlink()
        except OSError:
            pass
        raise DownloadFailure(f"could not write {final}: {exc}")
    return final


def download_asset(url, directory, entry_id, override=None):
    data, content_type = download_bytes(url)
    extension = override or content_type_extension(content_type)
    return store_asset(directory, entry_id, data, extension)


def download_candidates(entries, media_dir, limit):
    """| Candidate order | Catalog order within category |

    | Per-category limit | Download first `N` candidates in candidate order |
    | Omitted limit | No limit for that category |
    """
    candidates = [entry for entry in entries
                  if isinstance(entry, dict) and is_string(entry.get("id"))
                  and not has_asset(media_dir, entry["id"])]
    if limit is None:
        return candidates
    return candidates[:limit]


def run_download_phase(vault_dir, catalog, limits, override=None, stream=None):
    """Retrieve media and previews for the candidates of every category."""
    source = catalog.get("source", "")
    media_dir = Path(vault_dir) / MEDIA_DIRNAME
    preview_dir = Path(vault_dir) / PREVIEW_DIRNAME
    stats = {"media": 0, "previews": 0, "failed": 0}

    for category in CATEGORIES:
        entries = catalog.get(category)
        if not isinstance(entries, list):
            continue
        for entry in download_candidates(entries, media_dir, limits.get(category)):
            entry_id = entry["id"]

            # | Media | `<source>/media/<entry_id>` | ... |
            # | Media with format override | `<source>/media/<entry_id>.<format>` |
            remote = f"{entry_id}.{override}" if override else entry_id
            url = join_source(source, MEDIA_PATH_SEGMENT, remote)
            try:
                download_asset(url, media_dir, entry_id, override)
                stats["media"] += 1
            except DownloadFailure as exc:
                stats["failed"] += 1
                warn(f"skipped media for entry {entry_id!r}: {exc}", stream)

            # | Preview | `<source>/preview/<entry_id>` | `<vault>/previews/` |
            if has_asset(preview_dir, entry_id):
                continue
            url = join_source(source, PREVIEW_PATH_SEGMENT, entry_id)
            try:
                download_asset(url, preview_dir, entry_id)
                stats["previews"] += 1
            except DownloadFailure as exc:
                stats["failed"] += 1
                warn(f"skipped preview for entry {entry_id!r}: {exc}", stream)

    return stats


# --------------------------------------------------------------------------
# digest
#
# `digest` is format-aware: it reads v1, v2 and v3 catalogs directly and never
# writes anything back.
# --------------------------------------------------------------------------

def load_raw_vault(name, root=None):
    """Load ``name`` without migrating; returns ``(vault_dir, catalog, version)``.

    ``root`` resolves the vault against a directory other than the process
    working directory; the viewer serves the directory `serve` was started in.
    """
    vault_dir = Path(name) if root is None else Path(root) / name
    if not vault_dir.is_dir():
        raise MvaultError(f"vault {name!r} does not exist")

    path = catalog_path(vault_dir)
    if not path.is_file():
        raise MvaultError(f"vault {name!r} is invalid: missing {CATALOG_NAME}")

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MvaultError(
            f"vault {name!r} is invalid: cannot read {CATALOG_NAME}: {exc}")

    try:
        catalog = json.loads(raw)
    except ValueError as exc:
        raise MvaultError(
            f"vault {name!r} is invalid: {CATALOG_NAME} is not valid JSON: {exc}")

    try:
        version = detect_version(catalog)
    except MvaultError as exc:
        raise MvaultError(f"vault {name!r} is invalid: {exc}")

    return vault_dir, catalog, version


def digest_tracked_fields(version):
    """v1 and v2 have no `removed` field; v3 tracks it as well."""
    return TRACKED_FIELDS if version == CATALOG_VERSION else SOURCE_TRACKED_FIELDS


def history_sort_key(version):
    """| v1 | ... **numeric** comparison ... | v2/v3 | **lexicographic** ... |"""
    if version != 1:
        return None

    def key(text):
        if EPOCH_KEY_RE.match(text):
            return (0, int(text), "")
        return (1, 0, text)

    return key


def digest_history(entry, field, version):
    """History of ``field`` as ``(key, value)`` pairs, oldest first."""
    history = entry.get(field) if isinstance(entry, dict) else None
    if not isinstance(history, dict):
        return []
    keys = sorted((key for key in history if is_string(key)),
                  key=history_sort_key(version))
    return [(key, history[key]) for key in keys]


def digest_current(entry, field, version):
    """| Current Value Resolution | Value at the latest key ... |"""
    history = digest_history(entry, field, version)
    return history[-1][1] if history else _MISSING


def is_removal(histories, version):
    """| Removals | Latest `removed` is `true` and prior value, if present, `false` |"""
    if version != CATALOG_VERSION:
        return False
    history = histories.get("removed") or []
    if not history or history[-1][1] is not True:
        return False
    return len(history) < 2 or history[-2][1] is False


def is_reappearance(histories, version):
    """| Reappearance after removal (v3 only) | Indicate reappearance ... |"""
    if version != CATALOG_VERSION:
        return False
    history = histories.get("removed") or []
    return len(history) >= 2 and history[-1][1] is False and history[-2][1] is True


def changed_fields(histories):
    """Tracked fields whose latest two history values differ."""
    changed = []
    for field in SOURCE_TRACKED_FIELDS:
        history = histories.get(field) or []
        if len(history) >= 2 and not values_equal(history[-1][1], history[-2][1]):
            changed.append(field)
    return changed


def classify_entry(entry, version):
    """Return ``(group, labels)`` for one entry, or ``(None, [])``.

    | Priority | `1` Removals (v3 only) | `2` Additions | `3` Field updates |
    Each entry may appear once, so the first matching rule wins.
    """
    histories = {field: digest_history(entry, field, version)
                 for field in digest_tracked_fields(version)}

    if is_removal(histories, version):
        return GROUP_REMOVALS, []

    # | Additions | ... no tracked field has a second history entry |
    if all(len(history) < 2 for history in histories.values()):
        return GROUP_ADDITIONS, []

    labels = []
    if is_reappearance(histories, version):
        labels.append(REAPPEARED_LABEL)
    labels.extend(changed_fields(histories))
    if labels:
        return GROUP_UPDATES, labels
    return None, []


def digest_title(entry, version):
    """| Entry text | Current title from latest `title` history value |"""
    value = digest_current(entry, "title", version)
    if value is _MISSING or value is None:
        entry_id = entry.get("id")
        return entry_id if is_string(entry_id) else "<unknown entry>"
    return value if is_string(value) else str(value)


def digest_sections(catalog, version):
    """| Category grouping | v1: single `Entries` group; v2/v3: per-category |

    Each section is ``(label, route_category, entries)``; the route category is
    the one the viewer link uses:
    | v1 | `entries` | | v2/v3 | Category where entry resides |
    """
    return [(digest_label(category), category, entries)
            for category, entries in viewer_categories_of(catalog, version)]


def digest_label(category):
    return V1_GROUP_LABEL if category == V1_CATEGORY else CATEGORY_LABELS[category]


def digest_source_url(catalog, version):
    """| v1 | `https://media.example.com/channel/<source_id>` | v2/v3 | `source` |"""
    if version == 1:
        source_id = catalog.get("source_id")
        return v1_source_url(source_id if is_string(source_id) else "")
    source = catalog.get("source")
    return source if is_string(source) else ""


def digest_trailing_line(catalog, version, name, generated):
    """| Trailing line | Metadata about the digest run | (deterministic format)"""
    return (f"Digest of vault {name!r}: catalog version {version}, "
            f"source {digest_source_url(catalog, version)}, "
            f"generated {generated}")


def build_digest(catalog, version, name, generated,
                 host=VIEWER_HOST, port=VIEWER_PORT):
    """The full digest, as a list of stdout lines."""
    body = []
    for label, category, entries in digest_sections(catalog, version):
        buckets = {group: [] for group in DIGEST_GROUP_ORDER}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            group, labels = classify_entry(entry, version)
            if group is None:
                continue
            text = digest_title(entry, version)
            if labels:
                text = f"{text} ({', '.join(labels)})"
            # | `digest <name>` | Each changed-entry line includes viewer link
            #   on same line as title |
            link = entry_link(name, category, entry, host, port)
            if link is not None:
                text = f"{text} {link}"
            buckets[group].append(text)

        # | Empty category | Omitted |
        if not any(buckets.values()):
            continue
        body.append(f"{label}:")
        for group in DIGEST_GROUP_ORDER:
            if not buckets[group]:
                continue
            body.append(f"  {group}:")
            body.extend(f"    - {text}" for text in buckets[group])

    if not body:
        body.append(NO_CHANGES_TEXT)
    body.append("")
    body.append(digest_trailing_line(catalog, version, name, generated))
    return body


# --------------------------------------------------------------------------
# viewer links
#
# | Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>` |
# | Default scheme | `http://` | | Default host | `127.0.0.1` |
# | Default port | `8840` |
# --------------------------------------------------------------------------

def viewer_categories(version):
    """| Version-Aware Valid Categories |"""
    return VIEWER_CATEGORIES.get(version, CATEGORIES)


def viewer_default_category(version):
    """| Version-Aware Default Category Redirect |"""
    return VIEWER_DEFAULT_CATEGORY.get(version, "episodes")


def viewer_default_path(name, version):
    """The default category page of ``name``, as a site-relative path."""
    return f"/catalog/{url_segment(name)}/{viewer_default_category(version)}"


def url_segment(text):
    """One path segment, percent-encoded (identity for ordinary names)."""
    return urllib.parse.quote(str(text), safe="")


def viewer_link(name, category, entry_id, host=VIEWER_HOST, port=VIEWER_PORT):
    """| Link format | `http://<host>:<port>/catalog/<name>/<category>/<id>` |"""
    return (f"{VIEWER_SCHEME}://{host}:{port}/catalog/"
            f"{url_segment(name)}/{url_segment(category)}/{url_segment(entry_id)}")


def entry_link(name, category, entry, host=VIEWER_HOST, port=VIEWER_PORT):
    """Viewer link for one catalog entry, or ``None`` when it has no usable id."""
    entry_id = entry.get("id") if isinstance(entry, dict) else None
    if not is_string(entry_id) or not entry_id:
        return None
    return viewer_link(name, category, entry_id, host, port)


def viewer_categories_of(catalog, version):
    """``(category, entries)`` pairs under the *route* name of each category."""
    if version == 1:
        entries = catalog.get("entries")
        return [(V1_CATEGORY, entries if isinstance(entries, list) else [])]
    pairs = []
    for category in CATEGORIES:
        entries = catalog.get(category)
        pairs.append((category, entries if isinstance(entries, list) else []))
    return pairs


def entry_is_downloaded(vault_dir, entry_id):
    """| Downloaded state | media filename in `<vault>/media/` contains `id` |"""
    if not is_string(entry_id) or not entry_id:
        return False
    return has_asset(Path(vault_dir) / MEDIA_DIRNAME, entry_id)


def entry_is_removed(entry, version):
    """| Removed indicator (v3 only) | latest `removed` value `true` |"""
    if version != CATALOG_VERSION:
        return False
    return digest_current(entry, "removed", version) is True


# --------------------------------------------------------------------------
# viewer HTML
# --------------------------------------------------------------------------

VIEWER_TITLE = "mvault viewer"

VIEWER_STYLE = """
body { font-family: system-ui, sans-serif; max-width: 54rem; margin: 2rem auto;
       padding: 0 1rem; line-height: 1.5; color: #12161c; background: #fbfcfd; }
h1 { font-size: 1.4rem; margin-bottom: 0.2rem; }
h2 { font-size: 1.1rem; margin-top: 1.6rem; }
a { color: #1a4fd6; }
ol.entries, ul.recent { list-style: none; padding: 0; }
li.entry { border: 1px solid #d7dde5; border-left-width: 6px; border-radius: 6px;
           padding: 0.5rem 0.75rem; margin: 0.35rem 0; background: #fff; }
li.entry .tag { font-size: 0.8rem; margin-left: 0.5rem;
                border: 1px solid currentColor; border-radius: 999px;
                padding: 0 0.45rem; }
ul.recent li { margin: 0.2rem 0; }
nav.categories a { margin-right: 0.75rem; }
p.notice { border: 1px solid #c8391f; background: #fdecea; color: #7b1c0b;
           padding: 0.5rem 0.75rem; border-radius: 6px; }
form input { padding: 0.35rem 0.5rem; }
"""


def viewer_escape(value):
    return html.escape(str(value), quote=True)


def viewer_page(title, body):
    """A complete, well-formed HTML document."""
    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{viewer_escape(title)}</title>\n"
        f"<style>{VIEWER_STYLE}</style>\n"
        "</head>\n<body>\n"
        f"{body}\n"
        "</body>\n</html>\n"
    )


def landing_page(recent, missing=None):
    """| `GET` | `/` | HTML page containing a form input for vault name |"""
    parts = [f"<h1>{viewer_escape(VIEWER_TITLE)}</h1>"]

    # | Non-existent vault ... | landing page shows vault-not-found indication |
    if missing:
        parts.append(
            f"<p class=\"notice\" role=\"alert\">Vault "
            f"&quot;{viewer_escape(missing)}&quot; was not found.</p>")

    parts.append(
        "<form method=\"post\" action=\"/\">\n"
        "<label for=\"catalog\">Vault name</label>\n"
        "<input type=\"text\" id=\"catalog\" name=\"catalog\" value=\"\" "
        "size=\"32\" autofocus>\n"
        "<button type=\"submit\">Open</button>\n"
        "</form>")

    # | Display location | Landing page | | Ordering | Most recently visited first |
    # | Empty state | Area may be empty or absent |
    if recent:
        items = "\n".join(
            f"<li><a href=\"{viewer_escape(path)}\">{viewer_escape(name)}</a></li>"
            for name, path in recent)
        parts.append("<h2>Recent vaults</h2>\n"
                     f"<ul class=\"recent\">\n{items}\n</ul>")

    return viewer_page(VIEWER_TITLE, "\n".join(parts))


def entry_item(name, category, entry, version, vault_dir, focused):
    """One listed entry: title link, download state and (v3) removal state."""
    entry_id = entry.get("id") if isinstance(entry, dict) else None
    entry_id = entry_id if is_string(entry_id) else ""
    title = digest_title(entry, version)

    classes = ["entry"]
    tags = []

    # | Visual distinction | Downloaded and undownloaded states must be
    #   distinguishable |
    if entry_is_downloaded(vault_dir, entry_id):
        classes.append("downloaded")
        border, tag = "#1f8a45", "downloaded"
    else:
        classes.append("absent")
        border, tag = "#c2c8d0", "missing"
    tags.append(f"<span class=\"tag\" style=\"color: {border}\">{tag}</span>")

    # | Removed indicator (v3 only) | ... visually distinct from active entries |
    if entry_is_removed(entry, version):
        classes.append("removed")
        border = "#c8391f"
        tags.append("<span class=\"tag\" style=\"color: #c8391f\">removed</span>")

    style = f"border-left-color: {border};"
    current = ""
    if focused and entry_id == focused:
        classes.append("selected")
        style += " background: #fff8d8; outline: 2px solid #e0b400;"
        current = " aria-current=\"true\""

    # | Entry navigation | Each listed entry includes a link to
    #   `/catalog/<name>/<category>/<id>` |
    href = (f"/catalog/{url_segment(name)}/{url_segment(category)}/"
            f"{url_segment(entry_id)}")
    return (f"<li class=\"{' '.join(classes)}\" style=\"{style}\"{current}>"
            f"<a class=\"entry-link\" href=\"{viewer_escape(href)}\">"
            f"{viewer_escape(title)}</a>"
            f"{''.join(tags)}</li>")


def category_page(name, version, category, entries, vault_dir, focused=None):
    """| `GET` | `/catalog/<name>/<category>` | HTML listing for category |"""
    title = f"{name} / {category}"
    parts = [f"<h1>{viewer_escape(name)}</h1>"]

    links = " ".join(
        f"<a href=\"/catalog/{url_segment(name)}/{url_segment(item)}\">"
        f"{viewer_escape(item)}</a>"
        for item in viewer_categories(version))
    parts.append(f"<nav class=\"categories\">{links}</nav>")
    parts.append(f"<h2>{viewer_escape(category)}</h2>")
    parts.append(f"<p class=\"meta\">catalog version {viewer_escape(version)}, "
                 f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'}</p>")

    if focused:
        parts.append(f"<p class=\"focus\">Selected entry: "
                     f"{viewer_escape(focused)}</p>")

    # | Entry order | Same order as category array in `catalog.json` |
    items = "\n".join(
        entry_item(name, category, entry, version, vault_dir, focused)
        for entry in entries if isinstance(entry, dict))
    parts.append(f"<ol class=\"entries\">\n{items}\n</ol>")
    parts.append("<p class=\"back\"><a href=\"/\">All vaults</a></p>")
    return viewer_page(title, "\n".join(parts))


def message_page(heading, detail):
    """A well-formed page for an HTTP error; never a stack trace."""
    return viewer_page(heading,
                       f"<h1>{viewer_escape(heading)}</h1>\n"
                       f"<p>{viewer_escape(detail)}</p>\n"
                       "<p><a href=\"/\">Back to the vault list</a></p>")


def redirect_page(location):
    return viewer_page(
        "Redirecting",
        f"<p>Continue to <a href=\"{viewer_escape(location)}\">"
        f"{viewer_escape(location)}</a>.</p>")


# --------------------------------------------------------------------------
# viewer state: recently visited vaults
# --------------------------------------------------------------------------

def read_recent_file(root):
    """Visited vault names held next to the served vaults, newest first."""
    path = Path(root) / RECENT_STATE_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    names = data.get("recent") if isinstance(data, dict) else None
    if not isinstance(names, list):
        return []
    return [item for item in names if is_string(item)][:RECENT_LIMIT]


def write_recent_file(root, names):
    path = Path(root) / RECENT_STATE_NAME
    payload = json.dumps({"recent": list(names)[:RECENT_LIMIT]}, indent=2) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass


def decode_recent_cookie(header):
    """Recent vault names carried by the browser, newest first."""
    if not header:
        return []
    for chunk in header.split(";"):
        key, _, value = chunk.strip().partition("=")
        if key != RECENT_COOKIE:
            continue
        try:
            data = json.loads(urllib.parse.unquote(value))
        except ValueError:
            return []
        if isinstance(data, list):
            return [item for item in data if is_string(item)][:RECENT_LIMIT]
    return []


def encode_recent_cookie(names):
    value = urllib.parse.quote(json.dumps(list(names)[:RECENT_LIMIT]), safe="")
    return (f"{RECENT_COOKIE}={value}; Path=/; Max-Age={COOKIE_MAX_AGE}; "
            f"SameSite=Lax")


def promote(names, name):
    """| Ordering | Most recently visited first | (and listed only once)"""
    ordered = [item for item in names if item != name]
    return [name] + ordered[:RECENT_LIMIT - 1]


def merge_recent(cookie_names, file_names):
    """The browser's own order wins; the server's file fills in the rest."""
    merged = list(cookie_names)
    for item in file_names:
        if item not in merged:
            merged.append(item)
    return merged[:RECENT_LIMIT]


# --------------------------------------------------------------------------
# viewer vault access
#
# "The viewer works on vaults of any supported version without requiring prior
# migration" - so every read goes through the raw, non-migrating loader.
# --------------------------------------------------------------------------

def safe_vault_name(name):
    """Reject anything that is not a plain directory name."""
    if not name or name in (".", ".."):
        return False
    if "/" in name or "\\" in name or "\0" in name:
        return False
    return True


def viewer_vault(root, name):
    """``(vault_dir, catalog, version)`` for ``name``, or ``None``."""
    if not safe_vault_name(name):
        return None
    try:
        return load_raw_vault(name, root=root)
    except MvaultError:
        return None
    except OSError:
        return None


# --------------------------------------------------------------------------
# viewer HTTP server
# --------------------------------------------------------------------------

class ViewerHandler(BaseHTTPRequestHandler):
    """| HTTP behavior defined above | Required |"""

    server_version = "mvault-viewer"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # ---- plumbing -------------------------------------------------------

    def log_message(self, *args):
        """Keep the console reserved for the two `serve` startup lines."""
        return

    @property
    def root(self):
        return self.server.root

    def send_body(self, status, text, content_type="text/html; charset=utf-8",
                  location=None, cookie=None):
        payload = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        if location is not None:
            self.send_header("Location", location)
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def redirect(self, location, cookie=None, status=303):
        """| Redirect status | HTTP `302` or `303` |"""
        self.send_body(status, redirect_page(location), location=location,
                       cookie=cookie)

    # ---- entry points ---------------------------------------------------

    def do_GET(self):  # noqa: N802 - http.server API
        self.dispatch("GET")

    def do_HEAD(self):  # noqa: N802 - http.server API
        self.dispatch("GET")

    def do_POST(self):  # noqa: N802 - http.server API
        self.dispatch("POST")

    def dispatch(self, method):
        """| Any HTTP error | ... no raw exception or stack trace exposure |"""
        try:
            split = urllib.parse.urlsplit(self.path)
            segments = [urllib.parse.unquote(part)
                        for part in split.path.split("/") if part != ""]
            if method == "POST":
                self.route_post(segments)
            else:
                self.route_get(segments, urllib.parse.parse_qs(split.query))
        except Exception:  # noqa: BLE001 - never leak a traceback to a browser
            try:
                self.send_body(500, message_page(
                    "Viewer error", "The viewer could not build that page."))
            except OSError:
                pass

    # ---- routes ---------------------------------------------------------

    def route_get(self, segments, query):
        if not segments:
            return self.landing(query)
        if segments[0] == "catalog":
            return self.catalog_route(segments[1:])
        self.send_body(404, message_page("Not found", "No such viewer page."))

    def route_post(self, segments):
        """| `POST` | `/` | Accept form-encoded body; redirect to
        `/catalog/<value>` when `catalog` field is present, otherwise redirect
        to `/` |
        """
        # Always drain the body: a request whose body is left unread would
        # desynchronize a keep-alive connection.
        body = self.read_form_body()
        if segments:
            self.send_body(404, message_page("Not found", "No such viewer page."))
            return
        fields = urllib.parse.parse_qs(body)
        values = [value for value in fields.get("catalog", []) if value.strip()]
        if not values:
            # | Missing `catalog` field on `POST /` | Redirect to `/` |
            self.redirect("/")
            return
        self.redirect(f"/catalog/{url_segment(values[0].strip())}")

    def read_form_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return ""
        try:
            return self.rfile.read(length).decode("utf-8", "replace")
        except OSError:
            return ""

    def landing(self, query=None):
        """| `GET` | `/` | HTML page containing a form input for vault name |"""
        names = merge_recent(
            decode_recent_cookie(self.headers.get("Cookie")),
            self.server.recent_names())
        recent = []
        for name in names:
            loaded = viewer_vault(self.root, name)
            if loaded is None:
                continue
            recent.append((name, viewer_default_path(name, loaded[2])))

        missing = self.server.take_missing()
        if not missing and query:
            values = query.get("missing") or query.get("vault") or []
            missing = values[0] if values else None
        self.send_body(200, landing_page(recent, missing))

    def catalog_route(self, parts):
        """| `/catalog/<name>` | `/catalog/<name>/<category>` |
        `/catalog/<name>/<category>/<id>` |
        """
        if not parts:
            self.redirect("/")
            return
        if len(parts) > 3:
            self.send_body(404, message_page("Not found", "No such viewer page."))
            return

        name = parts[0]
        loaded = viewer_vault(self.root, name)
        if loaded is None:
            # | Non-existent vault on any `/catalog/<name>` route | Redirect to
            #   `/`; landing page shows vault-not-found indication |
            self.server.note_missing(name)
            self.redirect("/")
            return

        vault_dir, catalog, version = loaded
        # | Trigger | Navigation to any vault through viewer |
        cookie = self.remember(name)

        default_path = viewer_default_path(name, version)
        if len(parts) == 1:
            # | `GET` | `/catalog/<name>` | Redirect to default category page |
            self.redirect(default_path, cookie=cookie)
            return

        category = parts[1]
        # | Category matching | Case-sensitive |
        if category not in viewer_categories(version):
            self.redirect(default_path, cookie=cookie)
            return

        entries = dict(viewer_categories_of(catalog, version)).get(category, [])
        focused = parts[2] if len(parts) == 3 else None
        page = category_page(name, version, category, entries, vault_dir, focused)
        self.send_body(200, page, cookie=cookie)

    def remember(self, name):
        """Record a visit; the reply carries the browser's copy of the list."""
        names = self.server.record_visit(name)
        browser = promote(decode_recent_cookie(self.headers.get("Cookie")), name)
        return encode_recent_cookie(merge_recent(browser, names))


class ViewerServer(ThreadingHTTPServer):
    """Serves vaults found in ``root``; keeps the recent-vault list."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, root):
        super().__init__(address, ViewerHandler)
        self.root = Path(root)
        self.state_lock = threading.Lock()
        self.missing = None

    def recent_names(self):
        with self.state_lock:
            return read_recent_file(self.root)

    def record_visit(self, name):
        with self.state_lock:
            names = promote(read_recent_file(self.root), name)
            write_recent_file(self.root, names)
            return names

    def note_missing(self, name):
        self.missing = name

    def take_missing(self):
        name, self.missing = self.missing, None
        return name


def open_browser(url):
    """Open the viewer in a browser without ever blocking the server."""

    def target():
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - a headless box has no browser
            pass

    threading.Thread(target=target, daemon=True).start()


def viewer_start_path(root, name):
    """| `serve` without `<name>` | ... `/` | | `serve <name>` | ... default
    category page for vault |
    """
    if not name:
        return "/"
    loaded = viewer_vault(root, name)
    if loaded is None:
        return f"/catalog/{url_segment(name)}"
    return viewer_default_path(name, loaded[2])


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def sync_summary_lines(name, stamp, counts, changes,
                       host=VIEWER_HOST, port=VIEWER_PORT):
    """| Trigger | Successful `sync` run that includes metadata phase |

    | Counts reported | Added, removed, updated |
    | Post-sync summary | Each changed-entry line includes viewer link on same
      line as title |

    A vault is always at v3 by the time a sync summary is printed - a v1 vault
    is auto-migrated first, so its entries are listed under `episodes`:
    | v1 vault after `sync` auto-migrates it to v3 | `episodes` for migrated
      episode entries |
    """
    lines = [
        f"Synced vault {name!r} at {stamp}: "
        f"{counts['new']} added, {counts['removed']} removed, "
        f"{counts['changed'] + counts['restored']} updated"
    ]
    for category, entry in changes:
        text = digest_title(entry, CATALOG_VERSION)
        link = entry_link(name, category, entry, host, port)
        lines.append(f"  - {text} {link}" if link else f"  - {text}")
    return lines


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
    vault_dir, catalog, _version = load_vault(name)

    summary = None
    # | Metadata phase | Load vault, optionally fetch source metadata, update
    #   catalog history, persist metadata |
    if not args.skip_metadata:
        payload = fetch_source(catalog["source"])
        stamp = next_sync_timestamp(catalog)
        counts, changes = apply_source(catalog, payload, stamp)
        # | Persistence boundary | Metadata changes must be durably saved
        #   before successful sync returns ... |
        write_catalog(vault_dir, catalog)
        summary = (stamp, counts, changes)

    # | Download phase | Retrieve media and preview files after metadata phase |
    if not args.skip_download:
        limits = {category: getattr(args, category) for category in CATEGORIES}
        stats = run_download_phase(
            vault_dir, catalog, limits, normalize_format(args.format))
        print(f"Downloaded {stats['media']} media and "
              f"{stats['previews']} preview file(s) into {vault_dir}")

    # | Trigger | Successful `sync` run that includes metadata phase |
    if summary is None:
        print(f"Sync of vault {name!r} finished (metadata phase skipped)")
        return 0

    stamp, counts, changes = summary
    for line in sync_summary_lines(name, stamp, counts, changes,
                                   viewer_host(args), viewer_port(args)):
        print(line)
    return 0


def cmd_digest(args):
    name = args.name
    catalog, version = load_raw_vault(name)[1:]
    generated = format_datetime(datetime.now().replace(microsecond=0))
    for line in build_digest(catalog, version, name, generated,
                             viewer_host(args), viewer_port(args)):
        print(line)
    return 0


def cmd_migrate(args):
    name = args.name
    vault_dir, catalog, version = load_vault(name)

    if version == CATALOG_VERSION:
        # | Effect on v3 | No-op; no backup written |
        print(f"Vault {name!r} is already at catalog version {CATALOG_VERSION}")
        return 0

    write_catalog(vault_dir, catalog)
    print(f"Migrated vault {name!r} from catalog version {version} "
          f"to {CATALOG_VERSION}")
    return 0


def viewer_host(args):
    """| Default host | `127.0.0.1` | (overridable with `--host`)"""
    host = getattr(args, "host", None)
    return host if host else VIEWER_HOST


def viewer_port(args):
    """| Default port | `8840` | (overridable with `--port`)"""
    port = getattr(args, "port", None)
    return VIEWER_PORT if port is None else port


def cmd_serve(args):
    """| Syntax | `python mvault.py serve [<name>] [--host=<host>]
    [--port=<port>]` |
    """
    host = viewer_host(args)
    port = viewer_port(args)
    root = Path.cwd()

    try:
        httpd = ViewerServer((host, port), root)
    except OSError as exc:
        raise MvaultError(f"cannot serve on {host}:{port}: {exc}")

    bound_port = httpd.server_address[1]
    # | `--host=<host>` | Override bind host; the browser URL uses this host as
    #   given |
    target = f"{VIEWER_SCHEME}://{host}:{bound_port}" \
             f"{viewer_start_path(root, getattr(args, 'name', None))}"

    print(f"mvault viewer listening on {host}:{bound_port}")
    print(f"Opening {target}", flush=True)
    open_browser(target)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def port_number(text):
    """| `--port=<port>` | Override bind port |"""
    value = text.strip()
    if not re.fullmatch(r"\d+", value) or not 0 <= int(value) <= 65535:
        raise argparse.ArgumentTypeError(f"{text!r} is not a valid port number")
    return int(value)


def nonnegative_int(text):
    """| `--episodes=<n>` | non-negative integer | ... |

    | Malformed numeric category limit | stderr | non-zero | Abort before any
    sync work | - argparse rejects the value before any command runs.
    """
    value = text.strip()
    if not re.fullmatch(r"\d+", value):
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a non-negative integer")
    return int(value)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mvault.py",
        description="Create local vaults for media-platform metadata and "
                    "record tracked-field history by sync timestamp.",
    )
    subparsers = parser.add_subparsers(
        dest="command", metavar="{init,sync,migrate,digest,serve}")

    def add_viewer_options(target):
        """| Link format | `http://<host>:<port>/...` | with the documented
        defaults, overridable for reports served from another address."""
        target.add_argument(
            "--host", default=None, metavar="<host>",
            help=f"viewer host for links (default {VIEWER_HOST})")
        target.add_argument(
            "--port", type=port_number, default=None, metavar="<port>",
            help=f"viewer port for links (default {VIEWER_PORT})")

    init_parser = subparsers.add_parser(
        "init", help="create a new vault with an empty catalog")
    init_parser.add_argument("name", help="vault directory to create")
    init_parser.add_argument("url", help="source URL for the vault")
    init_parser.set_defaults(func=cmd_init)

    sync_parser = subparsers.add_parser(
        "sync", help="fetch the source, update the catalog and download media")
    sync_parser.add_argument("name", help="existing vault directory")
    for category in CATEGORIES:
        sync_parser.add_argument(
            f"--{category}", type=nonnegative_int, default=None, metavar="<n>",
            help=f"maximum number of {category[:-1]} media downloads")
    sync_parser.add_argument(
        "--skip-metadata", action="store_true",
        help="skip the source fetch and metadata update; download only")
    sync_parser.add_argument(
        "--skip-download", action="store_true",
        help="skip the download phase; fetch and persist metadata only")
    sync_parser.add_argument(
        "--format", default=None, metavar="<str>",
        help="override the media download format and output extension")
    add_viewer_options(sync_parser)
    sync_parser.set_defaults(func=cmd_sync)

    migrate_parser = subparsers.add_parser(
        "migrate", help="convert a legacy catalog to the current version")
    migrate_parser.add_argument("name", help="existing vault directory")
    migrate_parser.set_defaults(func=cmd_migrate)

    digest_parser = subparsers.add_parser(
        "digest", help="summarize notable changes recorded in the catalog")
    digest_parser.add_argument("name", help="existing vault directory")
    add_viewer_options(digest_parser)
    digest_parser.set_defaults(func=cmd_digest)

    # | CLI `serve` command | Required |
    serve_parser = subparsers.add_parser(
        "serve", help="browse vaults in a local web viewer")
    serve_parser.add_argument(
        "name", nargs="?", default=None,
        help="vault to open in the browser (default: the vault list)")
    add_viewer_options(serve_parser)
    serve_parser.set_defaults(func=cmd_serve)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "func", None) is None:
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: a subcommand is required "
              f"(choose from init, sync, migrate, digest, serve)",
              file=sys.stderr)
        return 2

    try:
        return args.func(args)
    except MvaultError as exc:
        print(f"{parser.prog}: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
