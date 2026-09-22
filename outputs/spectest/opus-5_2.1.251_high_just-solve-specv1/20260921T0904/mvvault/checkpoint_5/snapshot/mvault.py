#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Creates a vault directory holding a ``catalog.json`` and records the history of
tracked fields keyed by sync timestamp.

Catalog versions 1 and 2 are loaded transparently: every command that reads a
vault sees the native version 3 shape, and ``migrate`` (or a ``sync`` of a
legacy vault) persists that conversion to disk.

``sync`` also downloads media and preview files after the metadata phase, and
``digest`` reports notable changes for a vault of any supported version without
migrating it.
"""

import argparse
import html
import http.cookies
import http.server
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

# Download phase -----------------------------------------------------------
MEDIA_DIR = "media"
PREVIEW_DIR = "previews"
MEDIA_ROUTE = "media"
PREVIEW_ROUTE = "preview"
DEFAULT_EXTENSION = "bin"
DOWNLOAD_ATTEMPTS = 3

# Names ending in one of these are treated as partial-download leftovers: they
# never count as an existing asset and are cleaned up after a good download.
PARTIAL_SUFFIXES = (
    ".part", ".partial", ".parts", ".filepart", ".tmp", ".temp",
    ".download", ".crdownload", ".incomplete", ".!ut", ".swp", "~",
)

# Responses that will never become available by retrying.
PERMANENT_HTTP_CODES = frozenset((400, 401, 402, 403, 404, 405, 406, 410, 414, 451))

# Content types whose canonical extension we pin rather than leaving to the
# platform's mimetypes database.
CONTENT_TYPE_EXTENSIONS = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/ogg": "ogv",
    "video/quicktime": "mov",
    "video/x-matroska": "mkv",
    "video/x-msvideo": "avi",
    "video/mpeg": "mpeg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/avif": "avif",
    "image/svg+xml": "svg",
    "application/octet-stream": DEFAULT_EXTENSION,
    "binary/octet-stream": DEFAULT_EXTENSION,
}

# Digest -------------------------------------------------------------------
V1_GROUP_LABEL = "Entries"
DIGEST_REMOVALS = "Removals"
DIGEST_ADDITIONS = "Additions"
DIGEST_UPDATES = "Field updates"
# Listed in precedence order; the output follows the same order.
DIGEST_GROUPS = (DIGEST_REMOVALS, DIGEST_ADDITIONS, DIGEST_UPDATES)

# Viewer -------------------------------------------------------------------
DEFAULT_SCHEME = "http"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8840
# Version 1 catalogs keep every entry in a single 'entries' category.
V1_CATEGORY = V1_ENTRIES_FIELD
V1_CATEGORIES = (V1_CATEGORY,)
# Recent vaults are kept in a persistent cookie (per browser) and mirrored on
# disk, so a later browser session still finds them.
RECENT_COOKIE = "mvault_recent"
RECENT_COOKIE_MAX_AGE = 31536000  # one year
RECENT_STATE_FILE = ".mvault_recent.json"
RECENT_LIMIT = 20
MAX_BODY_BYTES = 64 * 1024
BROWSER_OPEN_TIMEOUT = 1.0

# Static asset routes: ``/vault/<name>/media/<file>`` and
# ``/vault/<name>/preview/<id>`` serve what the download phase saved on disk.
VAULT_ROUTE = "vault"
# Detail pages link back to the platform the entry came from.
ENTRY_ROUTE = "entry"

# Chart data ---------------------------------------------------------------
# Only the numeric histories get charted; both are embedded as machine-readable
# JSON so the page stays useful without any scripting.
CHART_FIELDS = ("views", "likes")
# A single recorded point draws no line, so that field's chart is left out.
CHART_MIN_POINTS = 2
CHART_DATA_ID = "chart-data"
CHART_WIDTH = 640
CHART_HEIGHT = 160
CHART_PADDING = 12

# Content types for the static endpoints, keyed by the saved file's extension.
MEDIA_CONTENT_TYPES = {
    "mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm",
    "ogv": "video/ogg", "ogg": "audio/ogg", "mov": "video/quicktime",
    "mkv": "video/x-matroska", "avi": "video/x-msvideo",
    "mpeg": "video/mpeg", "mpg": "video/mpeg", "ts": "video/mp2t",
    "flv": "video/x-flv", "mp3": "audio/mpeg", "m4a": "audio/mp4",
    "aac": "audio/aac", "wav": "audio/wav", "flac": "audio/flac",
    "opus": "audio/opus", "weba": "audio/webm",
}
IMAGE_CONTENT_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "jpe": "image/jpeg",
    "png": "image/png", "gif": "image/gif", "webp": "image/webp",
    "avif": "image/avif", "svg": "image/svg+xml", "bmp": "image/bmp",
    "tif": "image/tiff", "tiff": "image/tiff", "ico": "image/x-icon",
}
DEFAULT_MEDIA_CONTENT_TYPE = "application/octet-stream"
# The preview route only ever serves preview images, so an unrecognised
# extension still gets an image type rather than a generic binary one.
DEFAULT_IMAGE_CONTENT_TYPE = "image/jpeg"
FILE_CHUNK_BYTES = 64 * 1024


class MvaultError(Exception):
    """A user-facing error; the message is printed to stderr."""


class SourceError(MvaultError):
    """Anything that makes the source metadata unusable."""

    def __init__(self, detail=None):
        if detail:
            super().__init__("%s: %s" % (FETCH_FAILURE, detail))
        else:
            super().__init__(FETCH_FAILURE)


class DownloadError(Exception):
    """A single asset could not be retrieved; sync keeps going regardless."""


class PermanentDownloadError(DownloadError):
    """The asset is gone for good, so retrying cannot help."""


class TransientDownloadError(DownloadError):
    """The asset might come back; worth retrying before giving up."""


def warn(message):
    """Emit a non-fatal warning; warnings never change the exit code."""
    print("mvault: warning: %s" % message, file=sys.stderr)


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
            # Flush to disk here so metadata survives whatever the download
            # phase runs into afterwards.
            handle.flush()
            os.fsync(handle.fileno())
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
    """Append history for tracked fields whose value changed.

    Returns ``True`` when at least one history entry was appended.
    """
    changed = False
    for field in SOURCE_TRACKED_FIELDS:
        history = entry.get(field)
        if not has_history(history):
            entry[field] = {stamp: item[field]}
            changed = True
            continue
        if not same_value(current_value(history), item[field]):
            history[stamp] = item[field]
            changed = True
    # A re-appearance counts as an update of the entry.
    if mark_removed(entry, False, stamp):
        changed = True
    return changed


def mark_removed(entry, removed, stamp):
    """Record a ``removed`` transition; returns ``True`` when one was recorded."""
    history = entry.get("removed")
    if not has_history(history):
        entry["removed"] = {stamp: bool(removed)}
        # Opening the history at ``False`` is the baseline, not a transition.
        return bool(removed)
    if current_value(history) is not bool(removed):
        history[stamp] = bool(removed)
        return True
    return False


def apply_source(catalog, source, stamp):
    """Fold the fetched source into ``catalog``; returns per-change counts."""
    counts = {"added": 0, "removed": 0, "updated": 0}
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
                counts["added"] += 1
            elif update_entry(existing, item, stamp):
                counts["updated"] += 1

        for entry in entries:
            if str(entry.get("id")) not in seen and mark_removed(entry, True, stamp):
                counts["removed"] += 1

        catalog[category] = sort_entries(entries)
    return counts


# --------------------------------------------------------------------------
# download phase
# --------------------------------------------------------------------------

def is_partial_name(filename):
    """True for partial-download leftovers, which never count as an asset."""
    lowered = filename.lower()
    if lowered.startswith("."):
        return True
    return any(lowered.endswith(suffix) for suffix in PARTIAL_SUFFIXES)


def safe_component(entry_id):
    """Keep a downloaded filename inside the target directory."""
    cleaned = entry_id.replace("\\", "_").replace("/", "_").replace("\0", "_")
    cleaned = cleaned.strip().strip(".")
    return cleaned or "entry"


def existing_asset(directory, entry_id):
    """Path of an already-downloaded asset for ``entry_id``, else ``None``."""
    try:
        names = os.listdir(directory)
    except OSError:
        return None
    for name in sorted(names):
        if is_partial_name(name) or entry_id not in name:
            continue
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            return path
    return None


def clear_partials(directory, entry_id):
    """Drop stale partial artifacts left behind for ``entry_id``."""
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if not is_partial_name(name) or entry_id not in name:
            continue
        try:
            os.remove(os.path.join(directory, name))
        except OSError:
            pass


def normalize_extension(text):
    """Turn a ``--format`` value into a bare extension, or ``None``."""
    if text is None:
        return None
    cleaned = str(text).strip().lstrip(".").strip()
    return cleaned or None


def extension_from_content_type(content_type):
    """Derive a file extension from an HTTP ``Content-Type`` header."""
    if not content_type:
        return DEFAULT_EXTENSION
    base = content_type.split(";")[0].strip().lower()
    if not base:
        return DEFAULT_EXTENSION
    if base in CONTENT_TYPE_EXTENSIONS:
        return CONTENT_TYPE_EXTENSIONS[base]
    guessed = mimetypes.guess_extension(base)
    if guessed:
        return guessed.lstrip(".")
    # Fall back to the subtype: "video/x-flv" -> "flv".
    subtype = base.split("/")[-1].split("+")[0]
    if subtype.startswith("x-"):
        subtype = subtype[2:]
    subtype = re.sub(r"[^a-z0-9]", "", subtype)
    return subtype or DEFAULT_EXTENSION


def asset_url(source, route, entry_id, extension=None):
    """Build ``<source>/<route>/<entry_id>[.<extension>]``."""
    base = str(source or "").rstrip("/")
    quoted = urllib.parse.quote(entry_id, safe="")
    if extension:
        quoted = "%s.%s" % (quoted, extension)
    return "%s/%s/%s" % (base, route, quoted)


def response_content_type(response):
    headers = getattr(response, "headers", None)
    if headers is None:
        info = getattr(response, "info", None)
        headers = info() if callable(info) else None
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    return getter("Content-Type")


def request_asset(url):
    """Fetch ``url``; returns ``(payload, content_type)``.

    Raises :class:`PermanentDownloadError` when the content is gone for good
    and :class:`TransientDownloadError` when a retry could still succeed.
    """
    try:
        response = urllib.request.urlopen(url)
    except urllib.error.HTTPError as exc:
        code = getattr(exc, "code", None)
        detail = "HTTP %s" % code if code is not None else (str(exc) or "HTTP error")
        try:
            exc.close()
        except Exception:
            pass
        if code in PERMANENT_HTTP_CODES:
            raise PermanentDownloadError(detail)
        raise TransientDownloadError(detail)
    except urllib.error.URLError as exc:
        raise TransientDownloadError(str(getattr(exc, "reason", None) or exc) or "unreachable")
    except Exception as exc:
        raise TransientDownloadError(str(exc) or exc.__class__.__name__)

    content_type = response_content_type(response)
    try:
        payload = response.read()
    except Exception as exc:
        raise TransientDownloadError(str(exc) or exc.__class__.__name__)
    finally:
        closer = getattr(response, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass

    if payload is None:
        payload = b""
    if isinstance(payload, str):
        payload = payload.encode("utf-8", "replace")
    return bytes(payload), content_type


def store_asset(directory, entry_id, extension, payload):
    """Write ``payload`` via a temporary file, then move it into place."""
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        raise PermanentDownloadError("could not create %s (%s)" % (directory, exc))
    filename = "%s.%s" % (safe_component(entry_id), extension or DEFAULT_EXTENSION)
    final_path = os.path.join(directory, filename)
    temp_path = final_path + ".part"
    try:
        with open(temp_path, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, final_path)
    except OSError as exc:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise PermanentDownloadError("could not write %s (%s)" % (final_path, exc))
    # Any leftover partial artifact for this entry is obsolete now.
    clear_partials(directory, entry_id)
    return final_path


def download_asset(url, directory, entry_id, extension=None):
    """Download ``url`` into ``directory``, retrying transient failures."""
    last = None
    for _ in range(DOWNLOAD_ATTEMPTS):
        try:
            payload, content_type = request_asset(url)
        except PermanentDownloadError:
            raise
        except TransientDownloadError as exc:
            last = exc
            continue
        chosen = extension or extension_from_content_type(content_type)
        return store_asset(directory, entry_id, chosen, payload)
    raise last if last is not None else TransientDownloadError("download failed")


def fetch_into(url, directory, entry_id, label, extension=None):
    """Download one asset, turning failures into warnings.  Returns a bool."""
    try:
        download_asset(url, directory, entry_id, extension)
        return True
    except PermanentDownloadError as exc:
        warn("%s for entry '%s' is unavailable (%s); skipping" % (label, entry_id, exc))
    except TransientDownloadError as exc:
        warn("%s for entry '%s' failed after %d attempts (%s); skipping"
             % (label, entry_id, DOWNLOAD_ATTEMPTS, exc))
    return False


def download_candidates(catalog, category, media_dir, limit):
    """Entries of ``category`` still missing media, in catalog order."""
    candidates = []
    for entry in catalog.get(category) or []:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            continue
        if existing_asset(media_dir, entry_id) is not None:
            continue
        candidates.append(entry_id)
        if limit is not None and len(candidates) >= limit:
            break
    return candidates


def run_download_phase(name, catalog, limits, fmt=None):
    """Retrieve media and previews for the entries still missing them."""
    vault_dir = catalog_paths(name)[0]
    media_dir = os.path.join(vault_dir, MEDIA_DIR)
    preview_dir = os.path.join(vault_dir, PREVIEW_DIR)
    for directory in (media_dir, preview_dir):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            raise MvaultError("vault '%s': could not create %s (%s)" % (name, directory, exc))

    source = catalog.get("source")
    override = normalize_extension(fmt)
    media_count = 0
    preview_count = 0

    for category in CATEGORIES:
        limit = limits.get(category)
        if limit is not None and limit <= 0:
            continue
        for entry_id in download_candidates(catalog, category, media_dir, limit):
            if fetch_into(asset_url(source, MEDIA_ROUTE, entry_id, override),
                          media_dir, entry_id, "media", override):
                media_count += 1
            if existing_asset(preview_dir, entry_id) is not None:
                continue
            if fetch_into(asset_url(source, PREVIEW_ROUTE, entry_id),
                          preview_dir, entry_id, "preview"):
                preview_count += 1

    print("Downloaded %d media file%s and %d preview file%s"
          % (media_count, "" if media_count == 1 else "s",
             preview_count, "" if preview_count == 1 else "s"))
    return media_count, preview_count


# --------------------------------------------------------------------------
# digest
# --------------------------------------------------------------------------

def digest_tracked_fields(version):
    """Tracked fields a catalog of ``version`` can actually carry."""
    return TRACKED_FIELDS if version == VERSION else SOURCE_TRACKED_FIELDS


def digest_key_order(version):
    """History key ordering: numeric epochs for v1, lexicographic otherwise."""
    if version == 1:
        def order(key):
            seconds = epoch_seconds(key)
            if seconds is None:
                return (1, 0, key)
            return (0, seconds, key)
        return order
    return lambda key: (0, 0, key)


def digest_values(history, version):
    """History values ordered oldest to newest for the catalog version."""
    if not isinstance(history, dict) or not history:
        return []
    keys = [key for key in history if isinstance(key, str)]
    keys.sort(key=digest_key_order(version))
    return [history[key] for key in keys]


def digest_entry_histories(entry, version):
    histories = {}
    for field in digest_tracked_fields(version):
        values = digest_values(entry.get(field), version)
        if values:
            histories[field] = values
    return histories


def digest_classify(entry, version):
    """Classify one entry; returns ``(group, changed_fields, removed_values)``."""
    histories = digest_entry_histories(entry, version)
    if not histories:
        return None, [], []

    changed = [
        field for field in digest_tracked_fields(version)
        if len(histories.get(field, ())) >= 2
        and not same_value(histories[field][-1], histories[field][-2])
    ]
    has_second = any(len(values) >= 2 for values in histories.values())

    removed_values = histories.get("removed", []) if version == VERSION else []
    removal = False
    if removed_values and removed_values[-1] is True:
        # A prior value, when there is one, has to be False to count.
        removal = len(removed_values) < 2 or removed_values[-2] is False

    if removal:
        return DIGEST_REMOVALS, changed, removed_values
    if not has_second:
        return DIGEST_ADDITIONS, changed, removed_values
    if changed:
        return DIGEST_UPDATES, changed, removed_values
    return None, changed, removed_values


def digest_title(entry, version):
    """Current title of an entry, falling back to its id."""
    values = digest_values(entry.get("title"), version)
    if values and isinstance(values[-1], str) and values[-1]:
        return values[-1]
    entry_id = entry.get("id")
    if isinstance(entry_id, str) and entry_id:
        return entry_id
    return "(untitled)"


def digest_field_labels(changed, removed_values):
    """Render changed field names, spelling out a re-appearance."""
    labels = []
    for field in changed:
        if field == "removed":
            reappeared = bool(removed_values) and removed_values[-1] is False
            labels.append("reappeared" if reappeared else "removed")
        else:
            labels.append(field)
    return labels


def digest_load(name):
    """Read a vault of any supported version without migrating it.

    Returns ``(version, source_url, [(label, category, entries), ...])`` where
    ``category`` is the viewer route the entries live under.
    """
    raw = read_catalog_file(name)
    version = catalog_version(raw, name)
    if version == 1:
        source_id = raw.get(V1_SOURCE_FIELD)
        source = v1_source_url(source_id) if isinstance(source_id, str) else "(unknown)"
        entries = raw.get(V1_ENTRIES_FIELD)
        groups = [(V1_GROUP_LABEL, V1_CATEGORY,
                   entries if isinstance(entries, list) else [])]
        return version, source, groups

    source = raw.get("source")
    if not isinstance(source, str) or not source:
        source = "(unknown)"
    groups = []
    for category in CATEGORIES:
        entries = raw.get(category)
        groups.append((category.capitalize(), category,
                       entries if isinstance(entries, list) else []))
    return version, source, groups


def digest_lines(version, groups, name=None, host=None, port=None):
    """Build the grouped digest body; returns ``(lines, change_count)``.

    When ``name`` is given every changed-entry line ends with the viewer link
    for that entry, on the same line as its title.
    """
    lines = []
    total = 0
    for label, category, entries in groups:
        buckets = {group: [] for group in DIGEST_GROUPS}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            group, changed, removed_values = digest_classify(entry, version)
            if group is None:
                continue
            text = digest_title(entry, version)
            if group == DIGEST_UPDATES:
                field_labels = digest_field_labels(changed, removed_values)
                if field_labels:
                    text = "%s (%s)" % (text, ", ".join(field_labels))
            link = entry_viewer_link(name, category, entry.get("id"), host, port)
            if link:
                text = "%s %s" % (text, link)
            buckets[group].append(text)

        if not any(buckets.values()):
            continue  # empty categories are omitted entirely
        lines.append("%s:" % label)
        for group in DIGEST_GROUPS:
            if not buckets[group]:
                continue
            lines.append("  %s:" % group)
            for text in buckets[group]:
                lines.append("    - %s" % text)
                total += 1
    return lines, total


def sync_changed_fields(entry, stamp):
    """Tracked fields this sync appended history for."""
    fields = []
    for field in TRACKED_FIELDS:
        history = entry.get(field)
        if not isinstance(history, dict) or stamp not in history:
            continue
        if field == "removed" and len(history) == 1 and history[stamp] is False:
            # Opening the history at False (new entry, or migration) is the
            # baseline rather than a change.
            continue
        fields.append(field)
    return fields


def sync_change_group(entry, stamp, fields):
    """Digest group an entry belongs to after a sync, or ``None``."""
    removed = entry.get("removed")
    if isinstance(removed, dict) and removed.get(stamp) is True:
        return DIGEST_REMOVALS
    fresh = all(
        isinstance(entry.get(field), dict) and list(entry.get(field)) == [stamp]
        for field in SOURCE_TRACKED_FIELDS
    )
    if fresh:
        return DIGEST_ADDITIONS
    if fields:
        return DIGEST_UPDATES
    return None


def sync_change_lines(catalog, stamp, name, host=None, port=None):
    """Per-entry summary of what one sync changed, with viewer links."""
    lines = []
    for category in CATEGORIES:
        buckets = {group: [] for group in DIGEST_GROUPS}
        for entry in catalog.get(category) or []:
            if not isinstance(entry, dict):
                continue
            fields = sync_changed_fields(entry, stamp)
            group = sync_change_group(entry, stamp, fields)
            if group is None:
                continue
            text = digest_title(entry, VERSION)
            if group == DIGEST_UPDATES:
                labels = digest_field_labels(
                    fields, digest_values(entry.get("removed"), VERSION)
                )
                if labels:
                    text = "%s (%s)" % (text, ", ".join(labels))
            link = entry_viewer_link(name, category, entry.get("id"), host, port)
            if link:
                text = "%s %s" % (text, link)
            buckets[group].append(text)

        if not any(buckets.values()):
            continue
        lines.append("%s:" % category.capitalize())
        for group in DIGEST_GROUPS:
            if not buckets[group]:
                continue
            lines.append("  %s:" % group)
            for text in buckets[group]:
                lines.append("    - %s" % text)
    return lines


# --------------------------------------------------------------------------
# viewer (serve)
# --------------------------------------------------------------------------

class VaultNotAvailable(Exception):
    """The viewer could not read the requested vault."""


def viewer_categories(version):
    """Categories a vault of ``version`` exposes through the viewer."""
    return V1_CATEGORIES if version == 1 else CATEGORIES


def viewer_default_category(version):
    """Category the bare ``/catalog/<name>`` route redirects to."""
    return V1_CATEGORY if version == 1 else CATEGORIES[0]


def valid_vault_name(name):
    """True when ``name`` can safely be used as a vault directory name."""
    if not isinstance(name, str) or not name or not name.strip():
        return False
    if name in (".", ".."):
        return False
    if any(bad in name for bad in ("/", "\\", "\0")):
        return False
    return True


def viewer_source(raw, version):
    """Source URL of a raw catalog, derived per version, or ``None``.

    Version 1 stores only a short platform identifier, so the full URL is
    rebuilt from it; versions 2 and 3 carry the URL directly.
    """
    if version == 1:
        source_id = raw.get(V1_SOURCE_FIELD)
        if isinstance(source_id, str) and source_id:
            return v1_source_url(source_id)
        return None
    source = raw.get("source")
    if isinstance(source, str) and source:
        return source
    return None


def entry_source_url(source, entry_id):
    """Source-platform link for one entry: ``<source>/entry/<id>``.

    With the version 1 source URL derived by :func:`viewer_source` this yields
    ``https://media.example.com/channel/<source_id>/entry/<id>``, and for
    versions 2 and 3 it appends to the catalog's own source URL.
    """
    if not source or not isinstance(entry_id, str) or not entry_id:
        return None
    return asset_url(source, ENTRY_ROUTE, entry_id)


def viewer_load(name):
    """Read a vault of any supported version without migrating it.

    Returns ``(version, {category: [entries]}, source)`` using the category
    names that version of the catalog actually exposes.  Anything unreadable
    raises :class:`VaultNotAvailable` so the viewer can fall back to the
    landing page.
    """
    if not valid_vault_name(name):
        raise VaultNotAvailable(name)
    try:
        raw = read_catalog_file(name)
        version = catalog_version(raw, name)
    except MvaultError:
        raise VaultNotAvailable(name)
    except Exception:  # unreadable vault must never reach the client as a 500
        raise VaultNotAvailable(name)

    def entries_of(field):
        value = raw.get(field)
        if not isinstance(value, list):
            return []
        return [entry for entry in value if isinstance(entry, dict)]

    source = viewer_source(raw, version)
    if version == 1:
        return version, {V1_CATEGORY: entries_of(V1_ENTRIES_FIELD)}, source
    return version, {c: entries_of(c) for c in CATEGORIES}, source


def viewer_removed(entry, version):
    """Latest ``removed`` value of an entry; only version 3 carries the field."""
    if version != VERSION:
        return False
    values = digest_values(entry.get("removed"), version)
    return bool(values) and values[-1] is True


def media_filenames(name):
    """Filenames currently present in ``<vault>/media/``."""
    media_dir = os.path.join(catalog_paths(name)[0], MEDIA_DIR)
    try:
        names = sorted(os.listdir(media_dir))
    except OSError:
        return []
    return [item for item in names if os.path.isfile(os.path.join(media_dir, item))]


def entry_downloaded(entry_id, media_names):
    """An entry counts as downloaded when a media filename contains its id."""
    if not entry_id:
        return False
    return any(entry_id in filename for filename in media_names)


def entry_media_filename(entry_id, media_names):
    """Saved media filename matching ``entry_id``, or ``None``.

    A filename matches when it contains the entry id; complete downloads win
    over partial-download leftovers so the detail page never links to a stub.
    """
    if not entry_id:
        return None
    matches = [filename for filename in media_names if entry_id in filename]
    for filename in matches:
        if not is_partial_name(filename):
            return filename
    return matches[0] if matches else None


def preview_filenames(name):
    """Filenames currently present in ``<vault>/previews/``."""
    preview_dir = os.path.join(catalog_paths(name)[0], PREVIEW_DIR)
    try:
        names = sorted(os.listdir(preview_dir))
    except OSError:
        return []
    return [item for item in names
            if os.path.isfile(os.path.join(preview_dir, item))]


def preview_filename(name, entry_id):
    """Saved preview filename whose name contains ``entry_id``, or ``None``."""
    if not entry_id:
        return None
    matches = [item for item in preview_filenames(name) if entry_id in item]
    for filename in matches:
        if not is_partial_name(filename):
            return filename
    return matches[0] if matches else None


def find_entry(entries, entry_id):
    """First entry of ``entries`` whose id is ``entry_id``, or ``None``.

    The caller has already narrowed ``entries`` to one category, so an id that
    is only used in a different category never matches here.
    """
    for entry in entries:
        if isinstance(entry, dict) and entry.get("id") == entry_id:
            return entry
    return None


def current_tracked(entry, field, version):
    """Value at the latest history key of ``field``, ordered for ``version``."""
    values = digest_values(entry.get(field), version)
    return values[-1] if values else None


# -- chart data ------------------------------------------------------------

def chart_timestamp(key, version):
    """A history key as an ISO 8601 chart timestamp.

    Version 1 keys are UNIX-epoch strings and get converted to UTC; version 2
    and 3 keys are already ISO 8601 and pass through untouched.
    """
    if version == 1:
        seconds = epoch_seconds(key)
        if seconds is not None:
            iso = epoch_key_to_iso(seconds)
            if iso is not None:
                return iso
    return key


def chart_points(history, version):
    """Timestamp/value pairs of one history, oldest first.

    Ordering follows the catalog version: numeric for version 1 epoch keys,
    lexicographic for the ISO 8601 keys of versions 2 and 3.  Every recorded
    point is kept, ``null`` values included.
    """
    if not isinstance(history, dict) or not history:
        return []
    keys = [key for key in history if isinstance(key, str)]
    keys.sort(key=digest_key_order(version))
    return [{"timestamp": chart_timestamp(key, version), "value": history[key]}
            for key in keys]


def entry_chart_data(entry, version):
    """Chart points for every charted field of one entry."""
    return dict(
        (field, chart_points(entry.get(field), version)) for field in CHART_FIELDS
    )


# -- static assets ---------------------------------------------------------

def safe_asset_name(value):
    """Return ``value`` when it is a single, non-escaping path component.

    Anything carrying a separator or a traversal component is rejected, so a
    request can never name a file outside the directory it addresses.
    """
    if not isinstance(value, str) or not value or not value.strip():
        return None
    if value in (".", ".."):
        return None
    if any(bad in value for bad in ("/", "\\", "\0")):
        return None
    return value


def traversal_component(value):
    """True when a path component addresses a directory rather than a name.

    Used for the preview route, whose ``<id>`` is matched against saved
    filenames instead of being joined onto a path: an id carrying a separator
    simply matches nothing, but a bare ``.`` or ``..`` is a traversal attempt.
    """
    if not isinstance(value, str) or not value:
        return True
    if value in (".", ".."):
        return True
    return any(bad in value for bad in ("\\", "\0"))


def contained_path(directory, filename):
    """Absolute path of ``filename`` inside ``directory``, or ``None``.

    Resolved with ``realpath`` so neither a crafted name nor a symlink can
    point the viewer outside the directory it is serving.
    """
    root = os.path.realpath(directory)
    target = os.path.realpath(os.path.join(root, filename))
    if target != root and not target.startswith(root + os.sep):
        return None
    return target


def vault_asset_path(name, subdirectory, filename):
    """Path of a file below ``<vault>/<subdirectory>/``, or ``None``."""
    safe = safe_asset_name(filename)
    if safe is None:
        return None
    return contained_path(os.path.join(catalog_paths(name)[0], subdirectory), safe)


def file_extension(filename):
    """Lower-cased extension of ``filename`` without its dot."""
    base = os.path.basename(str(filename or ""))
    _, dot, extension = base.rpartition(".")
    if not dot:
        return ""
    return extension.strip().lower()


def media_content_type(filename):
    """Media MIME type for a saved media file."""
    extension = file_extension(filename)
    if extension in MEDIA_CONTENT_TYPES:
        return MEDIA_CONTENT_TYPES[extension]
    if extension in IMAGE_CONTENT_TYPES:
        return IMAGE_CONTENT_TYPES[extension]
    guessed = mimetypes.guess_type(os.path.basename(str(filename)))[0]
    if guessed and guessed.split("/")[0] in ("video", "audio", "image"):
        return guessed
    return DEFAULT_MEDIA_CONTENT_TYPE


def image_content_type(filename):
    """Image MIME type for a saved preview file."""
    extension = file_extension(filename)
    if extension in IMAGE_CONTENT_TYPES:
        return IMAGE_CONTENT_TYPES[extension]
    guessed = mimetypes.guess_type(os.path.basename(str(filename)))[0]
    if guessed and guessed.startswith("image/"):
        return guessed
    return DEFAULT_IMAGE_CONTENT_TYPE


# -- URLs ------------------------------------------------------------------

def url_host(host):
    """Render a host for use in a URL, bracketing bare IPv6 literals."""
    text = str(host or DEFAULT_HOST)
    if ":" in text and not text.startswith("["):
        return "[%s]" % text
    return text


def viewer_base_url(host=None, port=None):
    """``http://<host>:<port>`` with the documented defaults."""
    chosen_port = DEFAULT_PORT if port is None else port
    return "%s://%s:%s" % (DEFAULT_SCHEME, url_host(host or DEFAULT_HOST), chosen_port)


def quote_segment(value):
    return urllib.parse.quote(str(value), safe="")


def vault_path(name, category=None, entry_id=None):
    """Path of a viewer route below ``/catalog``."""
    path = "/catalog/%s" % quote_segment(name)
    if category is not None:
        path = "%s/%s" % (path, quote_segment(category))
        if entry_id is not None:
            path = "%s/%s" % (path, quote_segment(entry_id))
    return path


def vault_asset_path_url(name, route, component):
    """Path of a ``/vault`` static endpoint."""
    return "/%s/%s/%s/%s" % (
        VAULT_ROUTE, quote_segment(name), route, quote_segment(component)
    )


def media_asset_url(name, filename):
    """``/vault/<name>/media/<file>`` for an exact saved filename."""
    return vault_asset_path_url(name, MEDIA_ROUTE, filename)


def preview_asset_url(name, entry_id):
    """``/vault/<name>/preview/<id>``; the server resolves the saved file."""
    return vault_asset_path_url(name, PREVIEW_ROUTE, entry_id)


def resolved_default_path(name):
    """Path ``/catalog/<name>`` resolves to, version-aware where possible."""
    try:
        version = viewer_load(name)[0]
    except VaultNotAvailable:
        return vault_path(name)
    return vault_path(name, viewer_default_category(version))


def entry_viewer_link(name, category, entry_id, host=None, port=None):
    """Absolute viewer link for one entry, or ``None`` when it has no id."""
    if not name or not category:
        return None
    if not isinstance(entry_id, str) or not entry_id:
        return None
    return viewer_base_url(host, port) + vault_path(name, category, entry_id)


# -- recent vaults ---------------------------------------------------------

def recent_state_path():
    """Where the viewer keeps its recent-vault list between runs."""
    return os.path.join(os.getcwd(), RECENT_STATE_FILE)


def load_recent_state():
    """Recent vault names recorded on disk, most recently visited first."""
    try:
        with open(recent_state_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, UnicodeDecodeError):
        return []
    if isinstance(data, dict):
        data = data.get("recent")
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, str) and item][:RECENT_LIMIT]


def save_recent_state(names):
    try:
        with open(recent_state_path(), "w", encoding="utf-8") as handle:
            json.dump(list(names)[:RECENT_LIMIT], handle)
    except OSError:
        pass  # the cookie still carries the list; persistence is best effort


def remember_on_disk(name):
    names = [item for item in load_recent_state() if item != name]
    names.insert(0, name)
    save_recent_state(names)
    return names


def parse_recent_cookie(header):
    """Recent vault names carried by the browser's cookie."""
    if not header:
        return []
    jar = http.cookies.SimpleCookie()
    try:
        jar.load(header)
    except http.cookies.CookieError:
        return []
    morsel = jar.get(RECENT_COOKIE)
    if morsel is None:
        return []
    try:
        data = json.loads(urllib.parse.unquote(morsel.value))
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, str) and item][:RECENT_LIMIT]


def recent_cookie_header(names):
    """``Set-Cookie`` value persisting ``names`` past the browser session."""
    value = urllib.parse.quote(json.dumps(list(names)[:RECENT_LIMIT]), safe="")
    return "%s=%s; Max-Age=%d; Path=/; SameSite=Lax" % (
        RECENT_COOKIE, value, RECENT_COOKIE_MAX_AGE
    )


def merge_recent(cookie_names, disk_names):
    """Browser list first, then anything only the server remembers."""
    merged = []
    for name in list(cookie_names) + list(disk_names):
        if name not in merged:
            merged.append(name)
    return merged[:RECENT_LIMIT]


# -- HTML ------------------------------------------------------------------

VIEWER_STYLE = """
:root { color-scheme: light dark; }
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
       margin: 2rem auto; max-width: 52rem; padding: 0 1rem; line-height: 1.5; }
h1 { margin-bottom: 0.2rem; }
.meta { color: #666; margin-top: 0; }
.notice { background: #fdecea; border-left: 4px solid #c0392b; color: #7b1b12;
          padding: 0.6rem 0.8rem; border-radius: 4px; }
.vault-form { margin: 1.2rem 0; display: flex; gap: 0.5rem; flex-wrap: wrap;
              align-items: center; }
.vault-form input { padding: 0.4rem 0.6rem; border: 1px solid #999; border-radius: 4px; }
.vault-form button { padding: 0.4rem 0.9rem; border-radius: 4px; }
nav.categories { margin: 0.8rem 0 1.2rem; display: flex; gap: 0.6rem; flex-wrap: wrap; }
nav.categories a { padding: 0.2rem 0.6rem; border: 1px solid #bbb; border-radius: 999px;
                   text-decoration: none; }
nav.categories a.current { border-color: #2b6cb0; font-weight: 700; }
ul.entries, ul.recent { list-style: none; padding: 0; }
ul.entries li { border: 1px solid #ddd; border-left-width: 5px; border-radius: 4px;
                padding: 0.5rem 0.7rem; margin-bottom: 0.4rem; }
ul.entries li.downloaded { border-left-color: #217a3a; background: rgba(33,122,58,0.06); }
ul.entries li.undownloaded { border-left-color: #bbb; opacity: 0.8; }
ul.entries li.removed { border-left-color: #c0392b; background: rgba(192,57,43,0.08); }
ul.entries li.removed a.title { text-decoration: line-through; color: #9b1c1c; }
.state, .badge { font-size: 0.8rem; margin-left: 0.5rem; padding: 0.05rem 0.45rem;
                 border-radius: 999px; border: 1px solid currentColor; white-space: nowrap; }
.state-downloaded { color: #217a3a; }
.state-undownloaded { color: #777; }
.badge-removed { color: #c0392b; }
a { color: #2b6cb0; }
.breadcrumb { margin-bottom: 0.6rem; }
.description { white-space: pre-wrap; }
.details { display: grid; grid-template-columns: auto 1fr; gap: 0.3rem 1rem;
           margin: 1.2rem 0; }
.details dt { font-weight: 700; color: #666; }
.details dd { margin: 0; overflow-wrap: anywhere; }
.preview-image { max-width: 100%; border-radius: 4px; }
.media-player { width: 100%; max-height: 24rem; background: #000; border-radius: 4px; }
section.chart { margin: 1.5rem 0; }
section.chart h2 { font-size: 1.05rem; margin-bottom: 0.4rem; }
.chart-plot { border: 1px solid #ddd; border-radius: 4px; }
table.points { border-collapse: collapse; margin-top: 0.6rem; font-size: 0.9rem; }
table.points th, table.points td { border: 1px solid #ddd; padding: 0.2rem 0.6rem;
                                   text-align: left; }
table.points td.value { text-align: right; font-variant-numeric: tabular-nums; }
"""


def html_page(title, body):
    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>%s</title>\n<style>%s</style>\n</head>\n<body>\n%s\n</body>\n</html>\n"
        % (html.escape(title), VIEWER_STYLE, body)
    )


def render_landing(recent, missing=None):
    """Landing page: the vault-name form plus the recent-vault list."""
    parts = ["<h1>mvault viewer</h1>"]
    if missing:
        parts.append(
            "<p class=\"notice\" id=\"vault-not-found\" role=\"alert\">"
            "Vault &quot;%s&quot; was not found.</p>" % html.escape(str(missing))
        )
    parts.append(
        "<form class=\"vault-form\" method=\"post\" action=\"/\">\n"
        "<label for=\"catalog\">Vault name</label>\n"
        "<input type=\"text\" id=\"catalog\" name=\"catalog\" "
        "placeholder=\"vault name\" autofocus>\n"
        "<button type=\"submit\">Open vault</button>\n"
        "</form>"
    )
    parts.append("<h2>Recent vaults</h2>")
    if recent:
        items = "\n".join(
            "<li><a href=\"%s\">%s</a></li>" % (html.escape(path), html.escape(name))
            for name, path in recent
        )
        parts.append("<ul class=\"recent\" id=\"recent-vaults\">\n%s\n</ul>" % items)
    else:
        parts.append(
            "<p class=\"empty\" id=\"recent-vaults\">No vaults visited yet.</p>"
        )
    return html_page("mvault viewer", "\n".join(parts))


def render_category_nav(name, version, category):
    links = []
    for candidate in viewer_categories(version):
        cls = " class=\"current\"" if candidate == category else ""
        links.append("<a href=\"%s\"%s>%s</a>" % (
            html.escape(vault_path(name, candidate)), cls, html.escape(candidate)
        ))
    return "<nav class=\"categories\">%s</nav>" % "".join(links)


def render_catalog(name, version, category, entries, media_names):
    """Category listing; every entry links to its detail page."""
    parts = [
        "<p><a href=\"/\">&larr; All vaults</a></p>",
        "<h1>%s</h1>" % html.escape(name),
        "<p class=\"meta\">Catalog version %d &middot; category "
        "<strong>%s</strong> &middot; %d entr%s</p>"
        % (version, html.escape(category), len(entries),
           "y" if len(entries) == 1 else "ies"),
        render_category_nav(name, version, category),
    ]

    items = []
    for entry in entries:
        entry_id = entry.get("id")
        entry_id = entry_id if isinstance(entry_id, str) else ""
        title = digest_title(entry, version)
        downloaded = entry_downloaded(entry_id, media_names)
        removed = viewer_removed(entry, version)
        classes = ["entry", "downloaded" if downloaded else "undownloaded"]
        if removed:
            classes.append("removed")
        badges = "<span class=\"state state-%s\">%s</span>" % (
            "downloaded" if downloaded else "undownloaded",
            "Downloaded" if downloaded else "Not downloaded",
        )
        if removed:
            badges += "<span class=\"badge badge-removed\">Removed</span>"
        items.append(
            "<li class=\"%s\" id=\"entry-%s\" data-id=\"%s\">"
            "<a class=\"title\" href=\"%s\">%s</a>%s</li>"
            % (" ".join(classes), html.escape(entry_id), html.escape(entry_id),
               html.escape(vault_path(name, category, entry_id)),
               html.escape(title), badges)
        )

    if items:
        parts.append("<ul class=\"entries\">\n%s\n</ul>" % "\n".join(items))
    else:
        parts.append("<p class=\"empty\">No entries in this category.</p>")

    return html_page("%s - %s" % (name, category), "\n".join(parts))


def render_chart_data(name, category, entry_id, charts):
    """Embed the chart points as machine-readable JSON.

    Every charted field is exposed twice -- at the top level and under
    ``charts`` -- so a consumer can read either shape.  Points keep their
    timestamp/value pairing, stay in chronological order and are never
    filtered, so a ``null`` in the ``likes`` history survives as ``null``.
    """
    payload = {
        "vault": name,
        "category": category,
        "id": entry_id,
        "fields": list(CHART_FIELDS),
        "charts": dict((field, charts.get(field) or []) for field in CHART_FIELDS),
    }
    for field in CHART_FIELDS:
        payload[field] = charts.get(field) or []
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    # Keep any "</" in the data from closing the script element early.
    text = text.replace("</", "<\\/")
    return ("<script type=\"application/json\" id=\"%s\">\n%s\n</script>"
            % (CHART_DATA_ID, text))


def chart_coordinates(points):
    """``(x, y)`` pairs for the plottable points, or ``[]``.

    Points whose value is not a number keep their slot on the x axis but are
    not plotted, so a gap in ``likes`` does not shift the rest of the line.
    """
    plottable = [(index, point["value"]) for index, point in enumerate(points)
                 if is_int(point["value"])]
    if len(plottable) < CHART_MIN_POINTS:
        return []
    values = [value for _, value in plottable]
    low, high = min(values), max(values)
    span = (high - low) or 1
    last = (len(points) - 1) or 1
    inner_width = CHART_WIDTH - 2 * CHART_PADDING
    inner_height = CHART_HEIGHT - 2 * CHART_PADDING
    coordinates = []
    for index, value in plottable:
        x = CHART_PADDING + inner_width * (float(index) / last)
        y = CHART_PADDING + inner_height * (1.0 - (float(value - low) / span))
        coordinates.append((x, y))
    return coordinates


def render_chart(field, points):
    """One field's chart, or ``""`` when a single point leaves nothing to plot.

    The chart is a plain inline SVG; the numbers behind it stay available in
    the embedded JSON and in the accompanying table either way.
    """
    if len(points) < CHART_MIN_POINTS:
        return ""
    coordinates = chart_coordinates(points)
    if not coordinates:
        return ""
    line = " ".join("%.2f,%.2f" % pair for pair in coordinates)
    dots = "".join("<circle cx=\"%.2f\" cy=\"%.2f\" r=\"3\"></circle>" % pair
                   for pair in coordinates)
    return (
        "<svg class=\"chart-plot\" id=\"chart-plot-%s\" data-field=\"%s\" "
        "viewBox=\"0 0 %d %d\" width=\"100%%\" height=\"%d\" "
        "role=\"img\" aria-label=\"%s over time\" "
        "preserveAspectRatio=\"none\">"
        "<polyline fill=\"none\" stroke=\"#2b6cb0\" stroke-width=\"2\" "
        "points=\"%s\"></polyline>"
        "<g fill=\"#2b6cb0\">%s</g></svg>"
        % (html.escape(field), html.escape(field), CHART_WIDTH, CHART_HEIGHT,
           CHART_HEIGHT, html.escape(field), line, dots)
    )


def render_point_value(value):
    """Render one history value for the readable points table."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def render_chart_section(field, points):
    """One chart section: the SVG when there is one, plus every point."""
    if not points:
        return (
            "<section class=\"chart empty\" id=\"chart-%s\" data-field=\"%s\">"
            "<h2>%s</h2><p class=\"empty\">No %s recorded.</p></section>"
            % (html.escape(field), html.escape(field),
               html.escape(field.capitalize()), html.escape(field))
        )
    rows = "".join(
        "<tr><td class=\"timestamp\">%s</td><td class=\"value\">%s</td></tr>"
        % (html.escape(str(point["timestamp"])),
           html.escape(render_point_value(point["value"])))
        for point in points
    )
    return (
        "<section class=\"chart\" id=\"chart-%s\" data-field=\"%s\" "
        "data-points=\"%d\">\n<h2>%s</h2>\n%s\n"
        "<table class=\"points\"><thead><tr><th>Timestamp</th><th>%s</th>"
        "</tr></thead><tbody>%s</tbody></table>\n</section>"
        % (html.escape(field), html.escape(field), len(points),
           html.escape(field.capitalize()), render_chart(field, points),
           html.escape(field.capitalize()), rows)
    )


def render_dimension(value):
    return str(value) if is_int(value) else ""


def render_media_section(name, entry_id, media_names):
    """Playback for the downloaded media file, or a note that there is none."""
    filename = entry_media_filename(entry_id, media_names)
    if filename is None:
        return (
            "<section class=\"media\" id=\"entry-media\" data-downloaded=\"false\">"
            "<h2>Media</h2>\n<p class=\"empty\" id=\"media-missing\">"
            "No media file has been downloaded for this entry.</p></section>"
        )
    url = media_asset_url(name, filename)
    escaped = html.escape(url)
    return (
        "<section class=\"media\" id=\"entry-media\" data-downloaded=\"true\" "
        "data-file=\"%s\">\n<h2>Media</h2>\n"
        "<video class=\"media-player\" id=\"media-player\" controls preload=\"none\" "
        "src=\"%s\"><source src=\"%s\" type=\"%s\">"
        "<a href=\"%s\">Download media</a></video>\n"
        "<p><a class=\"media-link\" id=\"media-link\" href=\"%s\">%s</a></p>"
        "</section>"
        % (html.escape(filename), escaped, escaped,
           html.escape(media_content_type(filename)), escaped, escaped,
           html.escape(filename))
    )


def render_entry(name, version, category, entry, media_names, source):
    """Detail page for one entry, normalized across catalog versions."""
    entry_id = entry.get("id")
    entry_id = entry_id if isinstance(entry_id, str) else ""
    title = digest_title(entry, version)
    description = current_tracked(entry, "description", version)
    description = description if isinstance(description, str) else ""
    published = entry.get("published")
    published = published if isinstance(published, str) else ""
    width = render_dimension(entry.get("width"))
    height = render_dimension(entry.get("height"))
    removed = viewer_removed(entry, version)
    listing = vault_path(name, category)
    charts = entry_chart_data(entry, version)
    link = entry_source_url(source, entry_id)

    parts = [
        "<p class=\"breadcrumb\"><a class=\"back\" href=\"%s\">&larr; Back to %s</a>"
        " &middot; <a href=\"/\">All vaults</a></p>"
        % (html.escape(listing), html.escape(category)),
        "<h1 class=\"title\" id=\"entry-title\">%s</h1>" % html.escape(title),
        "<p class=\"meta\">%s &middot; catalog version %d &middot; category "
        "<strong>%s</strong> &middot; id <code class=\"entry-id\">%s</code>%s</p>"
        % (html.escape(name), version, html.escape(category), html.escape(entry_id),
           "<span class=\"badge badge-removed\">Removed</span>" if removed else ""),
        "<p class=\"description\" id=\"entry-description\">%s</p>"
        % html.escape(description),
    ]

    preview = preview_filename(name, entry_id)
    if preview is not None:
        parts.append(
            "<p class=\"preview\"><img class=\"preview-image\" id=\"entry-preview\" "
            "src=\"%s\" alt=\"Preview image for %s\"></p>"
            % (html.escape(preview_asset_url(name, entry_id)), html.escape(title))
        )

    details = [
        "<dt>Published</dt><dd class=\"published\" id=\"entry-published\">%s</dd>"
        % html.escape(published),
        "<dt>Dimensions</dt><dd class=\"dimensions\" id=\"entry-dimensions\" "
        "data-width=\"%s\" data-height=\"%s\">"
        "<span class=\"width\">%s</span> \u00d7 <span class=\"height\">%s</span> "
        "<span class=\"dims\">(%sx%s)</span></dd>"
        % (html.escape(width), html.escape(height), html.escape(width),
           html.escape(height), html.escape(width), html.escape(height)),
    ]
    if link:
        details.append(
            "<dt>Source</dt><dd><a class=\"source-link\" id=\"source-link\" "
            "href=\"%s\" rel=\"noreferrer noopener\">%s</a></dd>"
            % (html.escape(link), html.escape(link))
        )
    else:
        details.append(
            "<dt>Source</dt><dd class=\"empty\" id=\"source-link\">"
            "No source URL recorded for this vault.</dd>"
        )
    parts.append("<dl class=\"details\">\n%s\n</dl>" % "\n".join(details))

    parts.append(render_media_section(name, entry_id, media_names))
    parts.append(render_chart_data(name, category, entry_id, charts))
    for field in CHART_FIELDS:
        parts.append(render_chart_section(field, charts.get(field) or []))

    return html_page("%s - %s" % (name, title), "\n".join(parts))


def render_entry_missing(name, version, category, entry_id):
    """Page for an id that no entry in ``category`` carries."""
    listing = vault_path(name, category)
    body = "\n".join([
        "<p class=\"breadcrumb\"><a class=\"back\" href=\"%s\">&larr; Back to %s</a>"
        " &middot; <a href=\"/\">All vaults</a></p>"
        % (html.escape(listing), html.escape(category)),
        "<h1>404 Entry not found</h1>",
        "<p class=\"notice\" id=\"entry-not-found\" role=\"alert\">"
        "No entry &quot;%s&quot; in category &quot;%s&quot; of vault &quot;%s&quot;.</p>"
        % (html.escape(entry_id), html.escape(category), html.escape(name)),
        render_category_nav(name, version, category),
    ])
    return html_page("%s - entry not found" % name, body)


# -- HTTP ------------------------------------------------------------------

def split_path(path):
    """Decoded, non-empty path segments of a request path."""
    return [urllib.parse.unquote(part) for part in str(path).split("/") if part]


class ViewerServer(http.server.ThreadingHTTPServer):
    """Threaded viewer server carrying the vault-not-found notice."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler):
        http.server.ThreadingHTTPServer.__init__(self, address, handler)
        self._missing = None
        self._missing_lock = threading.Lock()

    def set_missing(self, name):
        with self._missing_lock:
            self._missing = name

    def take_missing(self):
        with self._missing_lock:
            value = self._missing
            self._missing = None
            return value


class ViewerHandler(http.server.BaseHTTPRequestHandler):
    """Routes ``/`` and ``/catalog/...`` over plain HTML."""

    server_version = "mvault-viewer/%d" % VERSION
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep the CLI output readable
        pass

    # -- responses
    def _respond(self, status, body, extra_headers=()):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for header, value in extra_headers:
            self.send_header(header, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def send_html(self, body, status=200, cookie=None):
        headers = [("Set-Cookie", cookie)] if cookie else []
        self._respond(status, body, headers)

    def send_redirect(self, location, status=302, cookie=None):
        body = html_page(
            "Redirecting",
            "<p>Redirecting to <a href=\"%s\">%s</a></p>"
            % (html.escape(location), html.escape(location)),
        )
        headers = [("Location", location)]
        if cookie:
            headers.append(("Set-Cookie", cookie))
        self._respond(status, body, headers)

    def send_file(self, path, content_type):
        """Stream a file from disk with ``content_type``."""
        try:
            size = os.path.getsize(path)
            handle = open(path, "rb")
        except OSError:
            self.send_error_page(404, "Not found")
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD":
                shutil.copyfileobj(handle, self.wfile, FILE_CHUNK_BYTES)
        finally:
            handle.close()

    def send_error_page(self, status, message):
        body = html_page(
            "mvault viewer - %d" % status,
            "<h1>%d %s</h1>\n<p><a href=\"/\">Back to the vault list</a></p>"
            % (status, html.escape(message)),
        )
        self._respond(status, body)

    # -- entry points
    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        try:
            if method == "POST":
                self.route_post()
            else:
                self.route_get()
        except Exception:
            # Never let a traceback reach the client or the terminal.
            try:
                self.send_error_page(500, "Internal server error")
            except Exception:
                pass

    # -- routing
    def route_get(self):
        segments = split_path(urllib.parse.urlsplit(self.path).path)
        if not segments:
            self.page_landing()
            return
        if segments[0] == VAULT_ROUTE:
            self.route_static(segments[1:])
            return
        if segments[0] != "catalog":
            self.send_error_page(404, "Not found")
            return
        if len(segments) == 1:
            self.send_redirect("/")
        elif len(segments) == 2:
            self.route_vault(segments[1])
        elif len(segments) == 3:
            self.route_category(segments[1], segments[2])
        elif len(segments) == 4:
            self.route_entry(segments[1], segments[2], segments[3])
        else:
            self.send_error_page(404, "Not found")

    def route_post(self):
        segments = split_path(urllib.parse.urlsplit(self.path).path)
        if segments:
            self.send_error_page(404, "Not found")
            return
        fields = self.read_form()
        value = ""
        for candidate in fields.get("catalog") or []:
            if isinstance(candidate, str) and candidate.strip():
                value = candidate.strip()
                break
        if not value:
            self.send_redirect("/", status=303)
            return
        self.send_redirect(vault_path(value), status=303)

    def page_landing(self):
        missing = self.server.take_missing()
        names = merge_recent(parse_recent_cookie(self.headers.get("Cookie")),
                             load_recent_state())
        recent = []
        for name in names:
            if not valid_vault_name(name):
                continue
            if not os.path.isdir(catalog_paths(name)[0]):
                continue
            recent.append((name, resolved_default_path(name)))
        self.send_html(render_landing(recent, missing))

    def route_vault(self, name):
        loaded = self.open_vault(name)
        if loaded is None:
            return
        version = loaded[0]
        self.send_redirect(vault_path(name, viewer_default_category(version)),
                           cookie=self.remember(name))

    def route_category(self, name, category):
        loaded = self.open_vault(name)
        if loaded is None:
            return
        version, groups = loaded[0], loaded[1]
        cookie = self.remember(name)
        if category not in viewer_categories(version):
            self.send_redirect(vault_path(name, viewer_default_category(version)),
                               cookie=cookie)
            return
        body = render_catalog(name, version, category, groups.get(category) or [],
                              media_filenames(name))
        self.send_html(body, cookie=cookie)

    def route_entry(self, name, category, entry_id):
        """Detail page for one entry of one category."""
        loaded = self.open_vault(name)
        if loaded is None:
            return
        version, groups, source = loaded
        cookie = self.remember(name)
        if category not in viewer_categories(version):
            # An unknown category is handled exactly like the listing route.
            self.send_redirect(vault_path(name, viewer_default_category(version)),
                               cookie=cookie)
            return
        # The lookup stays inside this category, so the same id under another
        # category never answers for it.  Removed entries stay reachable.
        entry = find_entry(groups.get(category) or [], entry_id)
        if entry is None:
            self.send_html(render_entry_missing(name, version, category, entry_id),
                           status=404, cookie=cookie)
            return
        body = render_entry(name, version, category, entry,
                            media_filenames(name), source)
        self.send_html(body, cookie=cookie)

    # -- static assets
    def route_static(self, segments):
        """Serve ``/vault/<name>/media/<file>`` and ``/vault/<name>/preview/<id>``."""
        if len(segments) < 3:
            self.send_error_page(404, "Not found")
            return
        name, kind, remainder = segments[0], segments[1], segments[2:]
        if kind not in (MEDIA_ROUTE, PREVIEW_ROUTE):
            self.send_error_page(404, "Not found")
            return
        if safe_asset_name(name) is None or not valid_vault_name(name):
            # A traversal attempt in the vault name never reaches the disk.
            self.send_error_page(403, "Forbidden")
            return
        if self.open_vault(name) is None:
            return
        # Extra segments mean the request tried to walk out of the directory.
        if len(remainder) != 1:
            self.send_error_page(403, "Forbidden")
            return
        if kind == MEDIA_ROUTE:
            self.serve_media(name, remainder[0])
        else:
            self.serve_preview(name, remainder[0])

    def serve_media(self, name, filename):
        # The media route names a file directly, so the name has to be one
        # that cannot reach outside <vault>/media/.
        path = vault_asset_path(name, MEDIA_DIR, filename)
        if path is None:
            self.send_error_page(403, "Forbidden")
            return
        if not os.path.isfile(path):
            self.send_error_page(404, "Not found")
            return
        self.send_file(path, media_content_type(filename))

    def serve_preview(self, name, entry_id):
        # The preview route names an entry id, not a file: the filename comes
        # from listing <vault>/previews/, so an id carrying a separator simply
        # matches nothing rather than reaching outside the directory.  A bare
        # directory reference is refused outright.
        if traversal_component(entry_id):
            self.send_error_page(403, "Forbidden")
            return
        filename = preview_filename(name, entry_id)
        if filename is None:
            self.send_error_page(404, "Not found")
            return
        path = vault_asset_path(name, PREVIEW_DIR, filename)
        if path is None or not os.path.isfile(path):
            self.send_error_page(404, "Not found")
            return
        self.send_file(path, image_content_type(filename))

    def open_vault(self, name):
        """Load a vault, or send the not-found redirect and return ``None``."""
        try:
            return viewer_load(name)
        except VaultNotAvailable:
            self.server.set_missing(name)
            self.send_redirect("/")
            return None

    # -- helpers
    def remember(self, name):
        """Record a vault visit; returns the ``Set-Cookie`` value to send."""
        names = [item for item in parse_recent_cookie(self.headers.get("Cookie"))
                 if item != name]
        names.insert(0, name)
        remember_on_disk(name)
        return recent_cookie_header(names)

    def read_form(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        length = max(0, min(length, MAX_BODY_BYTES))
        raw = self.rfile.read(length) if length else b""
        return urllib.parse.parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)


def open_browser(url):
    """Open ``url`` in the user's browser without blocking the server.

    The call runs on a worker thread so a browser that refuses to detach can
    never stop the server from accepting requests; the short join keeps the
    common case (the browser launches immediately) effectively synchronous.
    """
    if os.environ.get("MVAULT_NO_BROWSER"):
        return False

    def opener():
        try:
            webbrowser.open(url)
        except Exception:
            pass

    worker = threading.Thread(target=opener, daemon=True)
    worker.start()
    worker.join(BROWSER_OPEN_TIMEOUT)
    return True


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
    skip_metadata = getattr(args, "skip_metadata", False)
    skip_download = getattr(args, "skip_download", False)

    if skip_metadata:
        # No metadata is persisted, but the download phase still needs the
        # migrated (v3) view of a legacy vault to work from.
        if version != VERSION:
            apply_migration_stamp(catalog, migration_timestamp())
    else:
        source = fetch_source(catalog["source"])
        stamp = format_dt(sync_timestamp(catalog))
        if version != VERSION:
            apply_migration_stamp(catalog, stamp)
        counts = apply_source(catalog, source, stamp)
        # Legacy catalogs are migrated in memory above; the write below backs up
        # the original catalog and persists the v3 result.  It happens before the
        # download phase so metadata survives any download failure.
        write_catalog(name, catalog)

        total = sum(len(catalog[category]) for category in CATEGORIES)
        if version != VERSION:
            print("Migrated vault '%s' from catalog version %d to version %d"
                  % (name, version, VERSION))
        print("Synced vault '%s' at %s (%d entries)" % (name, stamp, total))
        print("Changes: %d added, %d removed, %d updated"
              % (counts["added"], counts["removed"], counts["updated"]))
        for line in sync_change_lines(catalog, stamp, name,
                                      getattr(args, "host", None),
                                      getattr(args, "port", None)):
            print(line)

    if not skip_download:
        limits = {
            "episodes": getattr(args, "episodes", None),
            "streams": getattr(args, "streams", None),
            "clips": getattr(args, "clips", None),
        }
        run_download_phase(name, catalog, limits, getattr(args, "format", None))
    return 0


def cmd_digest(args):
    name = args.name
    version, source, groups = digest_load(name)
    lines, total = digest_lines(version, groups, name,
                                getattr(args, "host", None),
                                getattr(args, "port", None))

    if lines:
        for line in lines:
            print(line)
        print("")
    else:
        print("No notable changes found.")
    print("Digest for vault '%s': catalog version %d, %d notable change%s, source %s"
          % (name, version, total, "" if total == 1 else "s", source))
    return 0


def cmd_serve(args):
    name = getattr(args, "name", None)
    host = getattr(args, "host", None) or DEFAULT_HOST
    port = getattr(args, "port", None)
    port = DEFAULT_PORT if port is None else port

    try:
        server = ViewerServer((host, port), ViewerHandler)
    except OSError as exc:
        raise MvaultError("could not serve on %s:%s (%s)" % (host, port, exc))

    # A port of 0 means "pick one"; the URL has to name the port actually bound.
    bound_port = server.server_address[1] if port == 0 else port
    base = viewer_base_url(host, bound_port)
    target = base + (resolved_default_path(name) if name else "/")

    print("Serving vault viewer at %s/" % base)
    print("Opening %s" % target)
    sys.stdout.flush()
    open_browser(target)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("")
    finally:
        server.server_close()
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

def nonneg_int(text):
    """``argparse`` type for the per-category download limits."""
    candidate = str(text).strip()
    if not re.match(r"^[0-9]+$", candidate):
        raise argparse.ArgumentTypeError(
            "invalid non-negative integer value: %s" % json.dumps(str(text))
        )
    try:
        return int(candidate)
    except ValueError:  # pragma: no cover - guarded by the regex above
        raise argparse.ArgumentTypeError(
            "invalid non-negative integer value: %s" % json.dumps(str(text))
        )


def port_number(text):
    """``argparse`` type for ``--port``."""
    candidate = str(text).strip()
    if not re.match(r"^[0-9]+$", candidate) or int(candidate) > 65535:
        raise argparse.ArgumentTypeError(
            "invalid port number: %s" % json.dumps(str(text))
        )
    return int(candidate)


def add_viewer_link_options(parser):
    """``--host`` / ``--port`` used to build viewer links."""
    parser.add_argument(
        "--host", default=None, metavar="<host>",
        help="host used in viewer links (default %s)" % DEFAULT_HOST,
    )
    parser.add_argument(
        "--port", type=port_number, default=None, metavar="<port>",
        help="port used in viewer links (default %d)" % DEFAULT_PORT,
    )


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
        "sync", help="fetch the source, update the vault catalog and download media"
    )
    sync_parser.add_argument("name", help="vault directory name")
    for category in CATEGORIES:
        sync_parser.add_argument(
            "--%s" % category, type=nonneg_int, default=None, metavar="<n>",
            help="maximum number of %s media downloads" % category,
        )
    sync_parser.add_argument(
        "--skip-metadata", dest="skip_metadata", action="store_true",
        help="skip the source fetch and metadata update; download only",
    )
    sync_parser.add_argument(
        "--skip-download", dest="skip_download", action="store_true",
        help="fetch and persist metadata only; skip the download phase",
    )
    sync_parser.add_argument(
        "--format", dest="format", default=None, metavar="<str>",
        help="override the media download format and output extension",
    )
    add_viewer_link_options(sync_parser)
    sync_parser.set_defaults(func=cmd_sync)

    digest_parser = subparsers.add_parser(
        "digest", help="summarise notable changes recorded in a vault"
    )
    digest_parser.add_argument("name", help="vault directory name")
    add_viewer_link_options(digest_parser)
    digest_parser.set_defaults(func=cmd_digest)

    serve_parser = subparsers.add_parser(
        "serve", help="serve the local vault viewer and open a browser"
    )
    serve_parser.add_argument(
        "name", nargs="?", default=None,
        help="vault to open in the browser (omit to open the landing page)",
    )
    serve_parser.add_argument(
        "--host", default=None, metavar="<host>",
        help="bind host, also used in the browser URL (default %s)" % DEFAULT_HOST,
    )
    serve_parser.add_argument(
        "--port", type=port_number, default=None, metavar="<port>",
        help="bind port (default %d)" % DEFAULT_PORT,
    )
    serve_parser.set_defaults(func=cmd_serve)

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
