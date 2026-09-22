#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata with tracked-field history."""

import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"
CATALOG_VERSION = 3
SUPPORTED_VERSIONS = (1, 2, 3)
LEGACY_VERSIONS = (1, 2)
CATEGORIES = ("episodes", "streams", "clips")

STATIC_FIELDS = ("id", "published", "width", "height")
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)
ANNOTATIONS_FIELD = "annotations"

DT_FORMAT = "%Y-%m-%dT%H:%M:%S"

# Version 1 vaults only store a short platform identifier; the full source URL
# is derived from it deterministically.
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/%s"


class MVaultError(Exception):
    """Base error for user-facing failures."""


class SourceError(MVaultError):
    """Source metadata fetch failure."""


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


# --------------------------------------------------------------------------
# datetime helpers (locale independent)
# --------------------------------------------------------------------------

_DATE_ONLY_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$")
_DATETIME_RE = re.compile(
    r"^\s*(\d{4})-(\d{2})-(\d{2})"          # date
    r"[Tt ]"                                 # separator
    r"(\d{2}):(\d{2})"                       # hh:mm
    r"(?::(\d{2}))?"                         # optional :ss
    r"(?:[.,](\d+))?"                        # optional fractional seconds
    r"\s*(Z|z|[+-]\d{2}:?\d{2})?\s*$"        # optional timezone
)
_EPOCH_RE = re.compile(r"^\s*[+-]?\d+\s*$")


def format_dt(dt):
    """Render a datetime as YYYY-MM-DDTHH:MM:SS with no timezone suffix."""
    return "%04d-%02d-%02dT%02d:%02d:%02d" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second
    )


def parse_dt(text):
    """Parse ISO 8601 datetime / date-only text into a naive datetime.

    Timezone suffixes are dropped (wall-clock components are kept).
    Returns None when the text cannot be understood.
    """
    if not isinstance(text, str):
        return None
    m = _DATE_ONLY_RE.match(text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _DATETIME_RE.match(text)
    if m:
        year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
        second = int(m.group(6) or 0)
        try:
            return datetime(year, month, day, hour, minute, second)
        except ValueError:
            return None
    return None


def normalize_published(text):
    """Normalize a published value to YYYY-MM-DDTHH:MM:SS when possible."""
    dt = parse_dt(text)
    if dt is None:
        return text
    return format_dt(dt)


def epoch_key_to_iso(key):
    """Convert a UNIX-epoch-seconds string key to YYYY-MM-DDTHH:MM:SS in UTC.

    Returns None when the key is not a valid epoch-seconds string.
    """
    if not isinstance(key, str) or not _EPOCH_RE.match(key):
        return None
    try:
        seconds = int(key.strip())
    except ValueError:
        return None
    try:
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return format_dt(dt.replace(tzinfo=None))


def now_stamp():
    """Current wall-clock time as an ISO 8601 history key."""
    return format_dt(datetime.now().replace(microsecond=0))


# --------------------------------------------------------------------------
# vault helpers
# --------------------------------------------------------------------------

def catalog_path(name):
    return os.path.join(name, CATALOG_NAME)


def backup_path(name):
    return os.path.join(name, BACKUP_NAME)


def write_catalog(name, catalog):
    """Write the catalog, backing up any pre-existing catalog byte-for-byte."""
    path = catalog_path(name)
    if os.path.isfile(path):
        try:
            shutil.copyfile(path, backup_path(name))
        except OSError as exc:
            # The original catalog is left untouched: nothing has been written.
            raise MVaultError("vault %r: failed to write backup %s (%s)"
                              % (name, BACKUP_NAME, exc))
    data = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(data)


def read_catalog_file(name):
    """Read the raw catalog JSON for a vault without interpreting its version."""
    if not os.path.isdir(name):
        raise MVaultError("vault %r does not exist" % name)
    path = catalog_path(name)
    if not os.path.isfile(path):
        raise MVaultError("vault %r is invalid: missing %s" % (name, CATALOG_NAME))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            catalog = json.load(handle)
    except (OSError, ValueError) as exc:
        raise MVaultError("vault %r is invalid: unreadable %s (%s)"
                          % (name, CATALOG_NAME, exc))
    if not isinstance(catalog, dict):
        raise MVaultError("vault %r is invalid: catalog root must be an object" % name)
    return catalog


def detect_version(name, catalog):
    """Return the declared catalog version, rejecting unusable declarations."""
    if "version" not in catalog:
        raise MVaultError("vault %r is invalid: %s is missing the 'version' field"
                          % (name, CATALOG_NAME))
    version = catalog["version"]
    if not _is_int(version):
        raise MVaultError("vault %r is invalid: catalog 'version' must be an "
                          "integer (got %r)" % (name, version))
    if version > CATALOG_VERSION:
        raise MVaultError("vault %r has unsupported catalog version %d: this build "
                          "supports catalog versions %s"
                          % (name, version,
                             ", ".join(str(v) for v in SUPPORTED_VERSIONS)))
    if version not in SUPPORTED_VERSIONS:
        raise MVaultError("vault %r has unsupported catalog version %d: this build "
                          "supports catalog versions %s"
                          % (name, version,
                             ", ".join(str(v) for v in SUPPORTED_VERSIONS)))
    return version


def validate_native_catalog(name, catalog):
    """Validate the shape of a native (version 3) catalog."""
    if not isinstance(catalog.get("source"), str):
        raise MVaultError("vault %r is invalid: missing source URL" % name)
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise MVaultError("vault %r is invalid: missing %r array" % (name, category))
    return catalog


# --------------------------------------------------------------------------
# legacy catalog migration (version 1 / version 2 -> version 3)
# --------------------------------------------------------------------------

_HISTORY_VALUE_KINDS = {
    "title": "string",
    "description": "string",
    "views": "integer",
    "likes": "integer or null",
    "preview": "string",
}


def _bad_entry(name, version, label, index, message):
    raise MVaultError("vault %r is invalid: version %d entry %s[%d] %s"
                      % (name, version, label, index, message))


def _value_ok(field, value):
    kind = _HISTORY_VALUE_KINDS[field]
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return _is_int(value)
    return value is None or _is_int(value)


def _migrate_history(name, version, label, index, field, history):
    """Validate a legacy history object and return it with ISO 8601 keys."""
    if not isinstance(history, dict):
        _bad_entry(name, version, label, index,
                   "field %r must be a history object" % field)
    converted = []
    for key, value in history.items():
        if not isinstance(key, str):
            _bad_entry(name, version, label, index,
                       "field %r has a non-string history key %r" % (field, key))
        if version == 1:
            iso = epoch_key_to_iso(key)
            if iso is None:
                _bad_entry(name, version, label, index,
                           "field %r has an invalid UNIX-epoch history key %r"
                           % (field, key))
            order = int(key.strip())
        else:
            parsed = parse_dt(key)
            if parsed is None:
                _bad_entry(name, version, label, index,
                           "field %r has an invalid ISO 8601 history key %r"
                           % (field, key))
            iso = key
            order = None
        if not _value_ok(field, value):
            _bad_entry(name, version, label, index,
                       "field %r has a history value %r that is not %s"
                       % (field, value, _HISTORY_VALUE_KINDS[field]))
        converted.append((order, iso, value))
    if version == 1:
        converted.sort(key=lambda item: item[0])
    return {iso: value for _, iso, value in converted}


def migrate_entry(name, version, label, index, entry, stamp):
    """Return a version 3 entry built from a validated legacy entry."""
    if not isinstance(entry, dict):
        _bad_entry(name, version, label, index, "is not an object")
    if not isinstance(entry.get("id"), str):
        _bad_entry(name, version, label, index, "is missing a string 'id'")
    if not isinstance(entry.get("published"), str):
        _bad_entry(name, version, label, index, "is missing a string 'published'")
    for field in ("width", "height"):
        if not _is_int(entry.get(field)):
            _bad_entry(name, version, label, index,
                       "is missing an integer %r" % field)
    for field in SOURCE_TRACKED_FIELDS:
        if field not in entry:
            _bad_entry(name, version, label, index, "is missing %r" % field)

    migrated = {
        "id": entry["id"],
        "published": entry["published"],
        "width": entry["width"],
        "height": entry["height"],
    }
    for field in SOURCE_TRACKED_FIELDS:
        migrated[field] = _migrate_history(
            name, version, label, index, field, entry[field])

    removed = entry.get("removed")
    if isinstance(removed, dict) and removed:
        migrated["removed"] = _migrate_removed(name, version, label, index, removed)
    else:
        migrated["removed"] = {stamp: False}

    annotations = entry.get(ANNOTATIONS_FIELD)
    migrated[ANNOTATIONS_FIELD] = annotations if isinstance(annotations, list) else []

    known = set(migrated)
    for key, value in entry.items():
        if key not in known:
            migrated[key] = value
    return migrated


def _migrate_removed(name, version, label, index, history):
    """Carry over a stray legacy 'removed' history, converting v1 keys."""
    converted = {}
    for key, value in history.items():
        if not isinstance(key, str):
            _bad_entry(name, version, label, index,
                       "field 'removed' has a non-string history key %r" % (key,))
        if version == 1:
            iso = epoch_key_to_iso(key)
            if iso is None:
                _bad_entry(name, version, label, index,
                           "field 'removed' has an invalid UNIX-epoch history "
                           "key %r" % (key,))
        else:
            if parse_dt(key) is None:
                _bad_entry(name, version, label, index,
                           "field 'removed' has an invalid ISO 8601 history "
                           "key %r" % (key,))
            iso = key
        if not isinstance(value, bool):
            _bad_entry(name, version, label, index,
                       "field 'removed' has a history value %r that is not a "
                       "boolean" % (value,))
        converted[iso] = value
    return converted


def migrate_catalog(name, catalog, version, stamp=None):
    """Build a version 3 catalog from a validated version 1 or 2 catalog."""
    if version not in LEGACY_VERSIONS:
        raise MVaultError("vault %r: nothing to migrate from catalog version %d"
                          % (name, version))
    if stamp is None:
        stamp = now_stamp()

    if version == 1:
        source_id = catalog.get("source_id")
        if not isinstance(source_id, str):
            raise MVaultError("vault %r is invalid: version 1 catalog is missing "
                              "'source_id'" % name)
        entries = catalog.get("entries")
        if not isinstance(entries, list):
            raise MVaultError("vault %r is invalid: version 1 catalog is missing "
                              "the 'entries' array" % name)
        source = V1_SOURCE_TEMPLATE % source_id
        groups = [("episodes", "entries", entries),
                  ("streams", "streams", []),
                  ("clips", "clips", [])]
    else:
        source = catalog.get("source")
        if not isinstance(source, str):
            raise MVaultError("vault %r is invalid: missing source URL" % name)
        groups = []
        for category in CATEGORIES:
            items = catalog.get(category)
            if not isinstance(items, list):
                raise MVaultError("vault %r is invalid: missing %r array"
                                  % (name, category))
            groups.append((category, category, items))

    migrated = {"version": CATALOG_VERSION, "source": source}
    for category, label, items in groups:
        migrated[category] = [
            migrate_entry(name, version, label, index, entry, stamp)
            for index, entry in enumerate(items)
        ]

    reserved = {"version", "source", "source_id", "entries"} | set(CATEGORIES)
    for key, value in catalog.items():
        if key not in reserved:
            migrated[key] = value
    return migrated


def load_catalog(name):
    """Load a vault catalog of any supported version as a version 3 catalog.

    Returns ``(catalog, version)`` where ``version`` is the version declared on
    disk. Legacy catalogs are migrated in memory only; nothing is written here.
    """
    raw = read_catalog_file(name)
    version = detect_version(name, raw)
    if version == CATALOG_VERSION:
        return validate_native_catalog(name, raw), version
    return migrate_catalog(name, raw, version), version


# --------------------------------------------------------------------------
# source fetching / validation
# --------------------------------------------------------------------------

def _fetch_with_requests(url):
    import requests  # noqa: F401  (optional dependency)

    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def _fetch_with_urllib(url):
    import urllib.request

    with urllib.request.urlopen(url, timeout=60) as response:
        raw = response.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def fetch_source(url):
    """GET the source URL and return the decoded JSON payload."""
    errors = []
    for fetcher in (_fetch_with_requests, _fetch_with_urllib):
        try:
            return fetcher(url)
        except Exception as exc:  # noqa: BLE001 - any failure falls through
            errors.append("%s: %s" % (type(exc).__name__, exc))
    raise SourceError("failed to fetch source metadata from %s (%s)"
                      % (url, "; ".join(errors)))


def validate_source(payload, url):
    """Validate the source payload shape and every entry's nine fields."""
    if not isinstance(payload, dict):
        raise SourceError("source metadata from %s is not a JSON object" % url)
    categorized = {}
    for category in CATEGORIES:
        items = payload.get(category)
        if not isinstance(items, list):
            raise SourceError("source metadata from %s is missing the %r array"
                              % (url, category))
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise SourceError("source metadata from %s: %s[%d] is not an object"
                                  % (url, category, index))
            for field in ("id", "published", "title", "description", "preview"):
                if field not in item:
                    raise SourceError("source metadata from %s: %s[%d] is missing %r"
                                      % (url, category, index, field))
                if not isinstance(item[field], str):
                    raise SourceError("source metadata from %s: %s[%d] field %r must "
                                      "be a string" % (url, category, index, field))
            for field in ("width", "height", "views"):
                if field not in item:
                    raise SourceError("source metadata from %s: %s[%d] is missing %r"
                                      % (url, category, index, field))
                if not _is_int(item[field]):
                    raise SourceError("source metadata from %s: %s[%d] field %r must "
                                      "be an integer" % (url, category, index, field))
            if "likes" not in item:
                raise SourceError("source metadata from %s: %s[%d] is missing 'likes'"
                                  % (url, category, index))
            if item["likes"] is not None and not _is_int(item["likes"]):
                raise SourceError("source metadata from %s: %s[%d] field 'likes' must "
                                  "be an integer or null" % (url, category, index))
        categorized[category] = items
    return categorized


# --------------------------------------------------------------------------
# history helpers
# --------------------------------------------------------------------------

def history_current(history):
    """Return the value stored at the latest timestamp key, chronologically."""
    if not isinstance(history, dict) or not history:
        return None, False
    best_key = None
    best_dt = None
    for key in history:
        dt = parse_dt(key)
        if dt is None:
            continue
        if best_dt is None or dt > best_dt or (dt == best_dt and key > best_key):
            best_dt, best_key = dt, key
    if best_key is None:
        best_key = max(history)
    return history[best_key], True


def latest_history_dt(catalog):
    """Newest timestamp key present anywhere in the catalog."""
    newest = None
    for category in CATEGORIES:
        for entry in catalog.get(category, []):
            if not isinstance(entry, dict):
                continue
            for field in TRACKED_FIELDS:
                history = entry.get(field)
                if not isinstance(history, dict):
                    continue
                for key in history:
                    dt = parse_dt(key)
                    if dt is not None and (newest is None or dt > newest):
                        newest = dt
    return newest


def values_equal(left, right):
    """Compare tracked values, keeping null distinct from numbers/strings."""
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if type(left) is not type(right) and not (
        _is_int(left) and _is_int(right)
    ):
        return False
    return left == right


def record(entry, field, value, stamp):
    """Append a history entry for `field` when the value actually changed."""
    history = entry.get(field)
    if not isinstance(history, dict):
        history = {}
        entry[field] = history
    current, present = history_current(history)
    if present and values_equal(current, value):
        return False
    history[stamp] = value
    return True


def sort_entries(entries):
    """Newest published first; lexicographically smaller id first on ties."""
    def published_key(entry):
        value = entry.get("published")
        dt = parse_dt(value) if isinstance(value, str) else None
        if dt is not None:
            return (1, format_dt(dt))
        return (0, value if isinstance(value, str) else "")

    ordered = sorted(entries, key=lambda e: e.get("id") or "")
    ordered.sort(key=published_key, reverse=True)
    return ordered


def new_entry(item):
    return {
        "id": item["id"],
        "published": normalize_published(item["published"]),
        "width": item["width"],
        "height": item["height"],
    }


# --------------------------------------------------------------------------
# download phase
# --------------------------------------------------------------------------

# Files left behind by an interrupted transfer must never be mistaken for a
# finished asset, otherwise a stale artifact would block a later download.
PARTIAL_SUFFIXES = (".part", ".partial", ".tmp", ".temp", ".download",
                    ".crdownload")

DOWNLOAD_ATTEMPTS = 3          # total tries for a transient failure
RETRY_BASE_DELAY = 0.2         # seconds; grows linearly per retry

# Status codes that describe a temporary condition rather than missing content.
TRANSIENT_STATUS = (408, 425, 429)

DEFAULT_EXTENSION = "bin"

CONTENT_TYPE_EXTENSIONS = {
    "video/mp4": "mp4",
    "video/mpeg": "mpeg",
    "video/webm": "webm",
    "video/ogg": "ogv",
    "video/quicktime": "mov",
    "video/x-matroska": "mkv",
    "video/x-msvideo": "avi",
    "video/x-flv": "flv",
    "video/3gpp": "3gp",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "weba",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/avif": "avif",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
    "image/svg+xml": "svg",
    "application/octet-stream": "bin",
    "application/json": "json",
    "application/pdf": "pdf",
    "application/zip": "zip",
    "application/x-mpegurl": "m3u8",
    "application/vnd.apple.mpegurl": "m3u8",
    "text/plain": "txt",
    "text/html": "html",
}

_EXT_SAFE_RE = re.compile(r"[^A-Za-z0-9]+")


class DownloadError(MVaultError):
    """A single asset could not be downloaded."""

    def __init__(self, message, permanent=False):
        MVaultError.__init__(self, message)
        self.permanent = permanent


def warn(message):
    print("mvault: warning: %s" % message, file=sys.stderr)


def normalize_format(value):
    """Normalize a --format override into a bare extension string."""
    if value is None:
        return None
    text = value.strip().lstrip(".").strip()
    if not text:
        raise MVaultError("--format requires a non-empty format string")
    return text


def extension_from_content_type(content_type):
    """Derive a file extension from an HTTP Content-Type header value."""
    if not isinstance(content_type, str):
        return DEFAULT_EXTENSION
    mime = content_type.split(";", 1)[0].strip().lower()
    if not mime:
        return DEFAULT_EXTENSION
    known = CONTENT_TYPE_EXTENSIONS.get(mime)
    if known:
        return known
    import mimetypes

    guess = mimetypes.guess_extension(mime)
    if guess:
        guess = guess.lstrip(".")
        if guess:
            return guess
    subtype = mime.split("/", 1)[-1]
    if subtype.startswith("x-"):
        subtype = subtype[2:]
    subtype = _EXT_SAFE_RE.sub("", subtype)
    return subtype or DEFAULT_EXTENSION


def _classify_status(status):
    """True when a status code means the content is permanently unavailable."""
    return 400 <= status < 500 and status not in TRANSIENT_STATUS


def _get_with_requests(url):
    import requests

    try:
        response = requests.get(url, timeout=60)
    except Exception as exc:  # noqa: BLE001 - transport problems are transient
        raise DownloadError("%s: %s" % (type(exc).__name__, exc), permanent=False)
    status = response.status_code
    if status >= 400:
        raise DownloadError("HTTP %d" % status, permanent=_classify_status(status))
    return response.content, response.headers.get("Content-Type")


def _get_with_urllib(url):
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
            content_type = response.headers.get("Content-Type")
        return data, content_type
    except urllib.error.HTTPError as exc:
        try:
            exc.read()
        except Exception:  # noqa: BLE001 - draining the body is best effort
            pass
        raise DownloadError("HTTP %d" % exc.code,
                            permanent=_classify_status(exc.code))
    except DownloadError:
        raise
    except Exception as exc:  # noqa: BLE001 - transport problems are transient
        raise DownloadError("%s: %s" % (type(exc).__name__, exc), permanent=False)


def http_get(url):
    """GET a URL, returning ``(body_bytes, content_type)``."""
    try:
        import requests  # noqa: F401  (optional dependency)
    except ImportError:
        return _get_with_urllib(url)
    return _get_with_requests(url)


def fetch_asset(url, directory, entry_id, extension=None):
    """Download one asset, retrying transient failures, and return its path.

    The body is written to a partial file first and moved into place only after
    a complete transfer, so an interrupted download never leaves behind a file
    that would be mistaken for the finished asset.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            data, content_type = http_get(url)
            break
        except DownloadError as exc:
            if exc.permanent or attempt >= DOWNLOAD_ATTEMPTS:
                raise
            time.sleep(RETRY_BASE_DELAY * attempt)

    ext = extension if extension else extension_from_content_type(content_type)
    filename = "%s.%s" % (entry_id, ext) if ext else entry_id
    final = os.path.join(directory, filename)
    partial = final + ".part"
    try:
        os.makedirs(directory, exist_ok=True)
        with open(partial, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, final)
    except OSError as exc:
        try:
            os.remove(partial)
        except OSError:
            pass
        raise DownloadError("cannot store %s (%s)" % (filename, exc),
                            permanent=True)
    return final


def _is_partial_name(filename):
    lowered = filename.lower()
    return any(lowered.endswith(suffix) for suffix in PARTIAL_SUFFIXES)


def list_asset_names(directory):
    """Existing finished asset filenames in a directory (partials ignored)."""
    try:
        names = os.listdir(directory)
    except OSError:
        return set()
    return {n for n in names if not _is_partial_name(n)}


def has_asset(names, entry_id):
    """True when a finished asset file for `entry_id` is already present."""
    prefix = entry_id + "."
    for filename in names:
        if filename == entry_id or filename.startswith(prefix):
            return True
    return False


def download_candidates(catalog, category, media_names, limit):
    """Entry ids to download for a category, in catalog order."""
    if limit == 0:
        return []
    candidates = []
    for entry in catalog.get(category, []):
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            continue
        if has_asset(media_names, entry_id):
            continue
        candidates.append(entry_id)
    if limit is not None:
        candidates = candidates[:limit]
    return candidates


def run_download_phase(name, catalog, limits, fmt):
    """Fetch missing media (and their previews) for every category."""
    source = catalog.get("source")
    if not isinstance(source, str) or not source:
        raise MVaultError("vault %r is invalid: missing source URL" % name)
    base = source.rstrip("/")
    media_dir = os.path.join(name, "media")
    preview_dir = os.path.join(name, "previews")
    media_names = list_asset_names(media_dir)
    preview_names = list_asset_names(preview_dir)

    media_done = preview_done = failed = 0
    for category in CATEGORIES:
        for entry_id in download_candidates(catalog, category, media_names,
                                            limits.get(category)):
            if fmt:
                url = "%s/media/%s.%s" % (base, entry_id, fmt)
            else:
                url = "%s/media/%s" % (base, entry_id)
            try:
                path = fetch_asset(url, media_dir, entry_id, fmt)
            except DownloadError as exc:
                failed += 1
                warn("%s %s: media download failed: %s" % (category, entry_id, exc))
                continue
            media_done += 1
            media_names.add(os.path.basename(path))

            if has_asset(preview_names, entry_id):
                continue
            try:
                path = fetch_asset("%s/preview/%s" % (base, entry_id),
                                   preview_dir, entry_id)
            except DownloadError as exc:
                failed += 1
                warn("%s %s: preview download failed: %s"
                     % (category, entry_id, exc))
                continue
            preview_done += 1
            preview_names.add(os.path.basename(path))
    return media_done, preview_done, failed


# --------------------------------------------------------------------------
# digest
# --------------------------------------------------------------------------

# Digest reads a vault in whatever version it is stored in; the layout below
# describes the per-version differences it has to honour.
DIGEST_V1_GROUPS = (("entries", "Entries"),)
DIGEST_GROUPS = (("episodes", "Episodes"), ("streams", "Streams"),
                 ("clips", "Clips"))

GROUP_REMOVALS = "Removals"
GROUP_ADDITIONS = "Additions"
GROUP_UPDATES = "Field updates"
# Precedence order; every entry is reported in at most one of these.
DIGEST_GROUP_ORDER = (GROUP_REMOVALS, GROUP_ADDITIONS, GROUP_UPDATES)


def digest_categories(version):
    return DIGEST_V1_GROUPS if version == 1 else DIGEST_GROUPS


def digest_tracked_fields(version):
    """Tracked fields a catalog of this version can actually carry."""
    if version == CATALOG_VERSION:
        return TRACKED_FIELDS
    return SOURCE_TRACKED_FIELDS


def ordered_history_keys(history, version):
    """History keys oldest-first, ordered the way this version stores them."""
    if not isinstance(history, dict) or not history:
        return []
    keys = [key for key in history if isinstance(key, str)]
    if version == 1:
        # Version 1 keys are UNIX-epoch strings: "900" is newer than "1000"
        # lexicographically, so they must be compared numerically.
        def sort_key(key):
            text = key.strip()
            try:
                return (0, int(text), key)
            except ValueError:
                return (1, 0, key)

        return sorted(keys, key=sort_key)
    return sorted(keys)


def history_tail(history, version):
    """Return ``(latest, prior, count)`` for a history object."""
    keys = ordered_history_keys(history, version)
    if not keys:
        return None, None, 0
    latest = history[keys[-1]]
    prior = history[keys[-2]] if len(keys) > 1 else None
    return latest, prior, len(keys)


def digest_source_url(name, catalog, version):
    """Resolve the source URL the way this catalog version records it."""
    if version == 1:
        source_id = catalog.get("source_id")
        if not isinstance(source_id, str):
            raise MVaultError("vault %r is invalid: version 1 catalog is missing "
                              "'source_id'" % name)
        return V1_SOURCE_TEMPLATE % source_id
    source = catalog.get("source")
    if not isinstance(source, str):
        raise MVaultError("vault %r is invalid: missing source URL" % name)
    return source


def entry_title(entry, version):
    """Current title of an entry, falling back to its id."""
    latest, _prior, count = history_tail(entry.get("title"), version)
    if count and isinstance(latest, str):
        return latest
    entry_id = entry.get("id")
    return entry_id if isinstance(entry_id, str) and entry_id else "<untitled>"


def classify_entry(entry, version):
    """Return ``(group, changed_fields, reappeared)`` or ``(None, ..)``.

    Group precedence is removals, then additions, then field updates, so an
    entry is never reported twice.
    """
    fields = digest_tracked_fields(version)
    histories = {field: entry.get(field) for field in fields}

    if version == CATALOG_VERSION:
        latest, prior, count = history_tail(histories.get("removed"), version)
        if count and latest is True and (count < 2 or prior is False):
            return GROUP_REMOVALS, [], False

    counts = {}
    for field in fields:
        history = histories.get(field)
        counts[field] = len(ordered_history_keys(history, version))
    if all(count < 2 for count in counts.values()):
        return GROUP_ADDITIONS, [], False

    changed = []
    reappeared = False
    for field in fields:
        if counts[field] < 2:
            continue
        latest, prior, _count = history_tail(histories[field], version)
        if values_equal(latest, prior):
            continue
        if field == "removed":
            if latest is False and prior is True:
                reappeared = True
            continue
        changed.append(field)
    if changed or reappeared:
        return GROUP_UPDATES, changed, reappeared
    return None, [], False


def build_digest(name, catalog, version):
    """Group notable per-entry changes by category and change type."""
    sections = []
    for key, label in digest_categories(version):
        items = catalog.get(key)
        if not isinstance(items, list):
            items = []
        groups = {group: [] for group in DIGEST_GROUP_ORDER}
        for entry in items:
            if not isinstance(entry, dict):
                continue
            group, changed, reappeared = classify_entry(entry, version)
            if group is None:
                continue
            groups[group].append({
                "title": entry_title(entry, version),
                "fields": changed,
                "reappeared": reappeared,
            })
        if any(groups[group] for group in DIGEST_GROUP_ORDER):
            sections.append((label, groups))
    return sections


def format_change(item):
    """One reported entry: title plus the detail suffix, when there is one."""
    details = []
    if item["reappeared"]:
        details.append("reappeared")
    details.extend(item["fields"])
    if details:
        return "%s (%s)" % (item["title"], ", ".join(details))
    return item["title"]


def cmd_digest(name):
    # Read-only: the catalog is never migrated, rewritten, or backed up here.
    raw = read_catalog_file(name)
    version = detect_version(name, raw)
    source = digest_source_url(name, raw, version)
    sections = build_digest(name, raw, version)

    lines = []
    for label, groups in sections:
        lines.append("%s:" % label)
        for group in DIGEST_GROUP_ORDER:
            items = groups[group]
            if not items:
                continue
            lines.append("  %s:" % group)
            for item in items:
                lines.append("    - %s" % format_change(item))
    if not lines:
        lines.append("No notable changes found.")
    lines.append("Digest of vault %s (catalog version %d), source %s, generated "
                 "at %s" % (name, version, source, now_stamp()))
    print("\n".join(lines))
    return 0


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_init(name, url):
    if os.path.exists(name):
        raise MVaultError("vault %r already exists" % name)
    catalog = {
        "version": CATALOG_VERSION,
        "source": url,
        "episodes": [],
        "streams": [],
        "clips": [],
    }
    os.makedirs(name)
    write_catalog(name, catalog)
    print("Initialized vault %s from %s" % (name, url))
    return 0


def cmd_migrate(name):
    raw = read_catalog_file(name)
    version = detect_version(name, raw)
    if version == CATALOG_VERSION:
        validate_native_catalog(name, raw)
        print("Vault %s already uses catalog version %d; nothing to migrate"
              % (name, CATALOG_VERSION))
        return 0
    migrated = migrate_catalog(name, raw, version)
    write_catalog(name, migrated)
    print("Migrated %s from catalog version %d to version %d"
          % (name, version, CATALOG_VERSION))
    return 0


def sync_metadata_phase(name, catalog, version):
    """Fetch the source, fold it into the catalog, and persist the result."""
    url = catalog["source"]
    payload = fetch_source(url)
    source = validate_source(payload, url)

    stamp_dt = datetime.now().replace(microsecond=0)
    newest = latest_history_dt(catalog)
    if newest is not None and stamp_dt <= newest:
        stamp_dt = newest.replace(microsecond=0) + timedelta(seconds=1)
    stamp = format_dt(stamp_dt)

    added = updated = removed = restored = 0

    for category in CATEGORIES:
        entries = [e for e in catalog.get(category, []) if isinstance(e, dict)]
        by_id = {}
        for entry in entries:
            by_id.setdefault(entry.get("id"), entry)

        seen = set()
        for item in source[category]:
            item_id = item["id"]
            seen.add(item_id)
            entry = by_id.get(item_id)
            if entry is None:
                entry = new_entry(item)
                entries.append(entry)
                by_id[item_id] = entry
                for field in SOURCE_TRACKED_FIELDS:
                    entry[field] = {stamp: item[field]}
                entry["removed"] = {stamp: False}
                added += 1
                continue

            entry["published"] = normalize_published(item["published"])
            entry["width"] = item["width"]
            entry["height"] = item["height"]

            changed = False
            for field in SOURCE_TRACKED_FIELDS:
                if record(entry, field, item[field], stamp):
                    changed = True
            was_removed, present = history_current(entry.get("removed"))
            if record(entry, "removed", False, stamp):
                if present and was_removed is True:
                    restored += 1
                changed = True
            if changed:
                updated += 1

        for entry in entries:
            if entry.get("id") in seen:
                continue
            if record(entry, "removed", True, stamp):
                removed += 1

        catalog[category] = sort_entries(entries)

    catalog["version"] = CATALOG_VERSION
    # Metadata is durably on disk before the download phase runs, so download
    # failures can never cost us the catalog update.
    write_catalog(name, catalog)
    if version != CATALOG_VERSION:
        print("Migrated %s from catalog version %d to version %d"
              % (name, version, CATALOG_VERSION))
    return stamp, added, removed, updated, restored


def cmd_sync(name, limits=None, skip_metadata=False, skip_download=False,
             fmt=None):
    limits = limits or {}
    fmt = normalize_format(fmt)
    catalog, version = load_catalog(name)

    summary = None
    if not skip_metadata:
        summary = sync_metadata_phase(name, catalog, version)

    if not skip_download:
        media, previews, failed = run_download_phase(name, catalog, limits, fmt)
        if media or previews or failed:
            print("Downloaded %d media file%s and %d preview%s (%d failed)"
                  % (media, "" if media == 1 else "s",
                     previews, "" if previews == 1 else "s", failed))

    if summary is not None:
        stamp, added, removed, updated, restored = summary
        print("Synced %s at %s: %d added, %d removed, %d updated (%d restored)"
              % (name, stamp, added, removed, updated, restored))
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

COMMANDS = ("init", "sync", "migrate", "digest")

_NON_NEGATIVE_RE = re.compile(r"^\d+$")


def limit_value(text):
    """argparse type for a non-negative integer category limit."""
    if not _NON_NEGATIVE_RE.match(text.strip()):
        raise argparse.ArgumentTypeError(
            "%r is not a non-negative integer" % text)
    return int(text.strip())


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mvault",
        description="Create local vaults for media-platform metadata, record "
                    "tracked-field history by sync timestamp, download media "
                    "and previews, and summarize notable changes.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<subcommand>")

    init_parser = subparsers.add_parser(
        "init", help="create a new vault directory with an empty catalog")
    init_parser.add_argument("name", help="vault directory name")
    init_parser.add_argument("url", help="source metadata URL")

    sync_parser = subparsers.add_parser(
        "sync", help="update the vault catalog and download missing media")
    sync_parser.add_argument("name", help="vault directory name")
    for category in CATEGORIES:
        sync_parser.add_argument(
            "--%s" % category, type=limit_value, default=None, metavar="N",
            help="maximum number of %s media downloads" % category)
    sync_parser.add_argument(
        "--skip-metadata", action="store_true",
        help="skip the source fetch and metadata update; download only")
    sync_parser.add_argument(
        "--skip-download", action="store_true",
        help="skip the download phase; fetch and persist metadata only")
    sync_parser.add_argument(
        "--format", dest="format", default=None, metavar="EXT",
        help="override the media download format and output extension")

    migrate_parser = subparsers.add_parser(
        "migrate", help="convert a legacy vault catalog to the native format")
    migrate_parser.add_argument("name", help="vault directory name")

    digest_parser = subparsers.add_parser(
        "digest", help="summarize notable changes recorded in a vault")
    digest_parser.add_argument("name", help="vault directory name")

    return parser


def _usage_error(parser):
    parser.print_usage(sys.stderr)
    print("mvault: error: a subcommand is required (available: %s)"
          % ", ".join(COMMANDS), file=sys.stderr)
    return 2


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        return _usage_error(parser)
    args = parser.parse_args(argv)
    if not args.command:
        return _usage_error(parser)
    try:
        if args.command == "init":
            return cmd_init(args.name, args.url)
        if args.command == "sync":
            limits = {category: getattr(args, category)
                      for category in CATEGORIES}
            return cmd_sync(args.name, limits=limits,
                            skip_metadata=args.skip_metadata,
                            skip_download=args.skip_download,
                            fmt=args.format)
        if args.command == "migrate":
            return cmd_migrate(args.name)
        if args.command == "digest":
            return cmd_digest(args.name)
    except MVaultError as exc:
        print("mvault: error: %s" % exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print("mvault: error: %s" % exc, file=sys.stderr)
        return 1
    return _usage_error(parser)


if __name__ == "__main__":
    sys.exit(main())
