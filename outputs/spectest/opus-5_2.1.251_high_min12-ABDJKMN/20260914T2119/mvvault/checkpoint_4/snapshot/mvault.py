#!/usr/bin/env python3
"""mvault -- local vaults for media-platform metadata.

Creates local vaults holding a media platform's metadata and records the
history of every tracked field, keyed by sync timestamp.

    python mvault.py init <name> <url>
    python mvault.py sync <name> [--episodes=N] [--streams=N] [--clips=N]
                                 [--skip-metadata] [--skip-download]
                                 [--format=EXT]
    python mvault.py migrate <name>
    python mvault.py digest <name>
    python mvault.py serve [<name>] [--host=<host>] [--port=<port>]

`sync` runs a metadata phase (fetch the source, append tracked-field history,
persist the catalog) followed by a download phase that retrieves media and
preview files for entries that have no media file yet.

Catalogs written by older releases (version 1 and version 2) are loaded
transparently: every command that reads a vault migrates the catalog to the
native version 3 shape in memory, and only commands that write the catalog
persist the migration. `digest` is the exception -- it reads each catalog in
its own format, so it never migrates, in memory or on disk.

`serve` runs a local browser viewer over the same read-only path: it renders a
vault of any supported version in its own format and never writes to it. The
human-facing change reports (`digest` and the post-sync summary) append a
viewer link to every changed-entry line.
"""
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

CATALOG_VERSION = 3
SUPPORTED_VERSIONS = (1, 2, 3)
# Version 1 catalogs store only a short platform identifier; the full source
# URL is derived from it deterministically.
V1_SOURCE_PREFIX = "https://media.example.com/channel/"
CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"

CATEGORIES = ("episodes", "streams", "clips")
CATEGORY_LABELS = {"episodes": "Episodes", "streams": "Streams",
                   "clips": "Clips"}
# Version 1 keeps every entry in one flat list, so its digest has one group.
V1_GROUP_LABEL = "Entries"

# Download phase layout.
MEDIA_DIR = "media"
PREVIEW_DIR = "previews"
MEDIA_REMOTE = "media"
PREVIEW_REMOTE = "preview"
PARTIAL_SUFFIX = ".part"
DOWNLOAD_ATTEMPTS = 3
DEFAULT_EXTENSION = "bin"

# Content-Type -> file extension. Pinned for the types a media vault actually
# sees so filenames do not drift with the platform's mime database.
CONTENT_TYPE_EXTENSIONS = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
    "video/x-matroska": "mkv",
    "video/mpeg": "mpeg",
    "video/x-msvideo": "avi",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/flac": "flac",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/avif": "avif",
    "image/svg+xml": "svg",
    "application/json": "json",
    "application/octet-stream": "bin",
    "text/plain": "txt",
}

# HTTP statuses worth retrying; every other 4xx is permanent.
RETRYABLE_STATUSES = (408, 425, 429)

# Tracked fields sourced from the remote payload, in stored order.
SOURCE_TRACKED = ("title", "description", "views", "likes", "preview")
# `removed` is local-only: the source never provides it.
TRACKED = SOURCE_TRACKED + ("removed",)
STATIC = ("id", "published", "width", "height")

# Viewer defaults. The bind address and the host/port baked into the viewer
# links printed by `digest` and the post-sync summary share these values.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8840
DEFAULT_SCHEME = "http"
# Version 1 keeps one flat list, so the viewer exposes it under a single route.
V1_CATEGORY = "entries"
VIEWER_CATEGORIES = {1: (V1_CATEGORY,), 2: CATEGORIES, 3: CATEGORIES}
VIEWER_DEFAULT_CATEGORY = {1: V1_CATEGORY, 2: "episodes", 3: "episodes"}
# Recently visited vaults live beside the vaults themselves, so the list
# survives a server restart and stays scoped to one working directory.
RECENT_NAME = ".mvault-recent.json"
RECENT_LIMIT = 50

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
    """Apply a validated source payload to the catalog in place.

    Returns `(counts, changes)`. Each entry falls into at most one bucket, with
    removals taking precedence over field updates; `changes` maps
    `(category, id)` to `(bucket, changed field labels)` so the post-sync
    summary can name the entries behind the counts.
    """
    counts = {"added": 0, "removed": 0, "updated": 0}
    changes = {}
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
                counts["added"] += 1
                changes[(category, entry_id)] = ("added", [])
                continue
            fields = [field for field in SOURCE_TRACKED
                      if record(entry, field, source_entry[field], stamp)]
            restored = record(entry, "removed", False, stamp)
            if fields or restored:
                counts["updated"] += 1
                labels = ([REAPPEARED_LABEL] if restored else []) + fields
                changes[(category, entry_id)] = ("updated", labels)

        for entry_id, entry in by_id.items():
            if entry_id not in seen and record(entry, "removed", True, stamp):
                counts["removed"] += 1
                changes[(category, entry_id)] = ("removed", [])

        catalog[category] = sort_entries(entries)
    return counts, changes


# ---------------------------------------------------------------------------
# download phase
# ---------------------------------------------------------------------------
class DownloadError(Exception):
    """A failed asset download, classified as transient or permanent."""

    def __init__(self, message, transient):
        Exception.__init__(self, message)
        self.transient = transient


def warn(message):
    sys.stderr.write("mvault: warning: %s\n" % message)


def extension_for(content_type):
    """File extension implied by an HTTP `Content-Type` header."""
    if not content_type:
        return DEFAULT_EXTENSION
    kind = content_type.split(";")[0].strip().lower()
    if not kind:
        return DEFAULT_EXTENSION
    if kind in CONTENT_TYPE_EXTENSIONS:
        return CONTENT_TYPE_EXTENSIONS[kind]
    guess = mimetypes.guess_extension(kind)
    if guess:
        return guess.lstrip(".")
    return DEFAULT_EXTENSION


def asset_url(source, kind, entry_id, extension=None):
    """`<source>/<kind>/<entry_id>[.<extension>]`."""
    name = entry_id if extension is None else "%s.%s" % (entry_id, extension)
    return "%s/%s/%s" % (source.rstrip("/"), kind, name)


def http_download(url):
    """GET `url`, returning `(body, content_type)` or raising DownloadError."""
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read(), response.headers.get("Content-Type")
    except urllib.error.HTTPError as exc:
        try:
            exc.read()
        except Exception:
            pass
        transient = exc.code >= 500 or exc.code in RETRYABLE_STATUSES
        raise DownloadError("HTTP %s" % exc.code, transient)
    except urllib.error.URLError as exc:
        raise DownloadError(str(exc.reason), True)
    except Exception as exc:  # timeouts, truncated responses, ...
        raise DownloadError(str(exc), True)


def download_with_retries(url):
    """Retry transient failures; permanent ones are raised on first sight."""
    last = None
    for _ in range(DOWNLOAD_ATTEMPTS):
        try:
            return http_download(url)
        except DownloadError as exc:
            if not exc.transient:
                raise
            last = exc
    raise last


def store_asset(directory, filename, body):
    """Write `body` through a `.part` file so no partial ever looks finished."""
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        raise MvaultError("could not create %s: %s" % (directory, exc))
    final = os.path.join(directory, filename)
    partial = final + PARTIAL_SUFFIX
    try:
        with open(partial, "wb") as handle:
            handle.write(body)
        os.replace(partial, final)
    except OSError as exc:
        if os.path.exists(partial):
            try:
                os.remove(partial)
            except OSError:
                pass
        raise MvaultError("could not write %s: %s" % (final, exc))
    return final


def finished_media_names(directory):
    """Names of finished (non-`.part`) files already in `<vault>/media/`."""
    try:
        listing = os.listdir(directory)
    except OSError:
        return set()
    return {name for name in listing if not name.endswith(PARTIAL_SUFFIX)}


def has_media(names, entry_id):
    """Is there already a media file for `entry_id`, whatever its extension?"""
    prefix = entry_id + "."
    return any(name == entry_id or name.startswith(prefix) for name in names)


def fetch_asset(source, kind, entry_id, directory, override=None):
    """Download one asset; warn and return None when it cannot be retrieved."""
    url = asset_url(source, kind, entry_id, override)
    try:
        body, content_type = download_with_retries(url)
    except DownloadError as exc:
        warn("skipped %s for entry %s: %s (%s)" % (kind, entry_id, exc, url))
        return None
    extension = override if override else extension_for(content_type)
    return store_asset(directory, "%s.%s" % (entry_id, extension), body)


def download_phase(name, catalog, limits, override):
    """Retrieve media and preview files for the catalog's candidate entries."""
    source = catalog["source"]
    media_directory = os.path.join(name, MEDIA_DIR)
    preview_directory = os.path.join(name, PREVIEW_DIR)
    present = finished_media_names(media_directory)

    for category in CATEGORIES:
        limit = limits.get(category)
        taken = 0
        for entry in catalog.get(category, []):
            if limit is not None and taken >= limit:
                break
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id")
            if not is_str(entry_id) or has_media(present, entry_id):
                continue
            taken += 1
            stored = fetch_asset(source, MEDIA_REMOTE, entry_id,
                                 media_directory, override)
            if stored is not None:
                present.add(os.path.basename(stored))
            fetch_asset(source, PREVIEW_REMOTE, entry_id, preview_directory)


# ---------------------------------------------------------------------------
# digest
# ---------------------------------------------------------------------------
# Digest groups, in the spec's precedence order; an entry lands in exactly one.
DIGEST_GROUPS = ("removed", "added", "updated")
DIGEST_GROUP_LABELS = {"removed": "Removed", "added": "Added",
                       "updated": "Updated"}
REAPPEARED_LABEL = "reappeared"


def digest_tracked(version):
    """Tracked fields available in a catalog of `version`."""
    return TRACKED if version == CATALOG_VERSION else SOURCE_TRACKED


def epoch_sort_key(key):
    """Numeric ordering for version 1 keys, tolerating an unparseable one.

    The loader already rejects a v1 catalog whose keys are not epoch strings,
    so the fallback only ever matters to callers that skip validation.
    """
    try:
        return (0, int(key), "")
    except (TypeError, ValueError):
        return (1, 0, str(key))


def digest_keys(history, version, count=2):
    """The newest `count` history keys, newest first.

    Version 1 keys are UNIX-epoch strings and compare numerically; version 2
    and 3 keys are ISO 8601 strings and compare lexicographically.
    """
    if not isinstance(history, dict) or not history:
        return []
    keys = list(history)
    keys.sort(key=epoch_sort_key if version == 1 else str)
    keys.reverse()
    return keys[:count]


def digest_current(history, version):
    """Value at the newest key, or `_MISSING` for an empty history."""
    keys = digest_keys(history, version, count=1)
    if not keys:
        return _MISSING
    return history[keys[0]]


def viewer_link(name, category, entry_id, host=None, port=None):
    """The viewer URL for one entry: the link format the reports append."""
    return "%s://%s:%d/catalog/%s/%s/%s" % (
        DEFAULT_SCHEME,
        DEFAULT_HOST if host is None else host,
        DEFAULT_PORT if port is None else port,
        name, category, entry_id)


def viewer_categories(version):
    """Valid category routes for a vault of `version`."""
    return VIEWER_CATEGORIES.get(version, CATEGORIES)


def viewer_default_category(version):
    """The category `/catalog/<name>` redirects to for a vault of `version`."""
    return VIEWER_DEFAULT_CATEGORY.get(version, "episodes")


def viewer_buckets(catalog, version):
    """`[(display label, category route, entries), ...]` for a loaded catalog.

    Version 1's flat `entries` list is one bucket; v2 and v3 keep their three
    category arrays. Nothing is migrated: each version is read as stored.
    """
    if version == 1:
        return [(V1_GROUP_LABEL, V1_CATEGORY, catalog.get("entries", []))]
    return [(CATEGORY_LABELS[category], category, catalog.get(category, []))
            for category in CATEGORIES]


def digest_history(entry, field):
    value = entry.get(field)
    return value if isinstance(value, dict) else {}


def digest_title(entry, version):
    """Entry text: the current title, falling back to the entry id."""
    value = digest_current(digest_history(entry, "title"), version)
    if value is _MISSING:
        return str(entry.get("id", ""))
    return value if is_str(value) else str(value)


def field_changed(entry, field, version):
    """Does `field` have two or more history entries with differing latest two?"""
    history = digest_history(entry, field)
    keys = digest_keys(history, version)
    if len(keys) < 2:
        return False
    return not same_value(history[keys[0]], history[keys[1]])


def removal_state(entry, version):
    """`(is_removal, is_reappearance)` from the `removed` history (v3 only)."""
    if version != CATALOG_VERSION:
        return False, False
    history = digest_history(entry, "removed")
    keys = digest_keys(history, version)
    if not keys:
        return False, False
    latest = history[keys[0]]
    prior = history[keys[1]] if len(keys) > 1 else _MISSING
    if latest is True:
        return prior is _MISSING or prior is False, False
    if latest is False and prior is True:
        return False, True
    return False, False


def classify_entry(entry, version):
    """Return `(group, changed_field_labels)`; group is None when unremarkable."""
    removal, reappearance = removal_state(entry, version)
    if removal:
        return "removed", []

    tracked = digest_tracked(version)
    if all(len(digest_history(entry, field)) <= 1 for field in tracked):
        return "added", []

    changed = [field for field in SOURCE_TRACKED
               if field_changed(entry, field, version)]
    if reappearance:
        return "updated", [REAPPEARED_LABEL] + changed
    if changed:
        return "updated", changed
    return None, []


def change_line(entry, version, fields, name, category, host, port):
    """One changed-entry line: current title, changed fields, viewer link.

    The link goes on the same line as the title, and names the category the
    entry actually resides in (`entries` for a version 1 vault).
    """
    text = digest_title(entry, version)
    if fields:
        text = "%s (%s)" % (text, ", ".join(fields))
    link = viewer_link(name, category, entry.get("id", ""), host, port)
    return "%s %s" % (text, link)


def digest_groups(entries, version, name, category, host, port):
    """Group an entry list into `{group: [rendered line, ...]}` in catalog order."""
    grouped = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        group, fields = classify_entry(entry, version)
        if group is None:
            continue
        grouped.setdefault(group, []).append(
            change_line(entry, version, fields, name, category, host, port))
    return grouped


def digest_sections(catalog, version, name, host=None, port=None):
    """`[(category label, {group: [line, ...]}), ...]` in display order."""
    sections = []
    for label, category, entries in viewer_buckets(catalog, version):
        grouped = digest_groups(entries, version, name, category, host, port)
        if grouped:
            sections.append((label, grouped))
    return sections


def digest_source_url(catalog, version):
    """The source URL as resolved for the loaded catalog version."""
    if version == 1:
        return v1_source_url(catalog["source_id"])
    return catalog["source"]


def render_sections(sections):
    """Render `[(label, {group: [line, ...]})]` as the indented report body."""
    lines = []
    for label, grouped in sections:
        lines.append("%s:" % label)
        for group in DIGEST_GROUPS:
            if group not in grouped:
                continue
            lines.append("  %s:" % DIGEST_GROUP_LABELS[group])
            for text in grouped[group]:
                lines.append("    - %s" % text)
    return lines


def sync_sections(catalog, changes, name, host=None, port=None):
    """Post-sync change lines, grouped like the digest.

    The catalog has already been migrated to version 3 in memory, so every
    entry sits in one of the three native categories -- which is why a version
    1 vault reports its migrated entries under `episodes`.
    """
    sections = []
    for category in CATEGORIES:
        grouped = {}
        for entry in catalog.get(category, []):
            if not isinstance(entry, dict):
                continue
            change = changes.get((category, entry.get("id")))
            if change is None:
                continue
            group, fields = change
            grouped.setdefault(group, []).append(
                change_line(entry, CATALOG_VERSION, fields, name, category,
                            host, port))
        if grouped:
            sections.append((CATEGORY_LABELS[category], grouped))
    return sections


def render_digest(name, catalog, version, host=None, port=None):
    """The full digest output, trailing metadata line included."""
    lines = []
    sections = digest_sections(catalog, version, name, host, port)
    if not sections:
        lines.append("No notable changes found.")
    lines.extend(render_sections(sections))
    lines.append("digest of vault %s: catalog version %d, source %s, "
                 "generated %s" % (name, version,
                                   digest_source_url(catalog, version),
                                   format_ts(datetime.now())))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# viewer (`serve`)
# ---------------------------------------------------------------------------
def valid_vault_name(name):
    """Is `name` a single, safe path segment naming a vault directory?"""
    if not name or name in (os.curdir, os.pardir):
        return False
    if "\x00" in name:
        return False
    if "/" in name or "\\" in name:
        return False
    return not os.path.isabs(name)


def viewer_load(name):
    """`(catalog, version)` for a viewer request, or None when unusable.

    Reads the catalog in its own format -- no migration, no write -- so the
    viewer works on v1, v2 and v3 vaults alike. Anything that cannot be read
    or does not validate is reported as a missing vault rather than an error.
    """
    if not valid_vault_name(name):
        return None
    try:
        return read_catalog_file(name)
    except MvaultError:
        return None
    except Exception:
        return None


def viewer_route(name, version=None):
    """The default-category route `/catalog/<name>` resolves to."""
    if version is None:
        loaded = viewer_load(name)
        if loaded is None:
            return "/catalog/%s" % urllib.parse.quote(name, safe="")
        version = loaded[1]
    return "/catalog/%s/%s" % (urllib.parse.quote(name, safe=""),
                               viewer_default_category(version))


def media_names(name):
    """Every filename currently sitting in `<vault>/media/`."""
    try:
        return os.listdir(os.path.join(name, MEDIA_DIR))
    except OSError:
        return []


def is_downloaded(names, entry_id):
    """An entry is downloaded when a media filename contains its `id`."""
    if not entry_id:
        return False
    return any(entry_id in filename for filename in names)


def is_removed(entry, version):
    """Latest `removed` value, which only version 3 catalogs carry."""
    if version != CATALOG_VERSION:
        return False
    return digest_current(digest_history(entry, "removed"), version) is True


# ---- recently visited vaults ----------------------------------------------
def recent_path():
    """The recent-vault store, kept beside the vaults in the working directory."""
    return os.path.join(os.getcwd(), RECENT_NAME)


def read_recent():
    """Visited vault names, most recently visited first."""
    try:
        with open(recent_path(), "r", encoding="utf-8") as handle:
            stored = json.load(handle)
    except Exception:
        return []
    if not isinstance(stored, list):
        return []
    return [item for item in stored if isinstance(item, str) and item]


def record_recent(name):
    """Move `name` to the front of the recent list and persist it."""
    names = [item for item in read_recent() if item != name]
    names.insert(0, name)
    del names[RECENT_LIMIT:]
    try:
        with open(recent_path(), "w", encoding="utf-8") as handle:
            json.dump(names, handle)
    except OSError:
        pass  # a read-only working directory costs history, not the request


# ---- HTML -----------------------------------------------------------------
STYLE = """
body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 60rem;
       color: #1b1b1b; }
a { color: #0b5bd3; }
nav.categories a { margin-right: 1rem; }
nav.categories a.current { font-weight: bold; text-decoration: none; }
ul.entries, ul.recent { list-style: none; padding: 0; }
li.entry { padding: .4rem .6rem; border-left: 4px solid #c9c9c9;
           margin-bottom: .3rem; }
li.entry.downloaded { border-left-color: #1a7f37; background: #f2f9f4; }
li.entry.not-downloaded { border-left-color: #c9c9c9; background: #fafafa; }
li.entry.removed { text-decoration: line-through; opacity: .65; }
li.entry.highlighted { outline: 2px solid #0b5bd3; }
span.state { font-size: .8rem; margin-left: .5rem; color: #555; }
span.state.removed-state { color: #a40e26; }
p.not-found { background: #fdeaea; border-left: 4px solid #a40e26;
              padding: .6rem; }
"""


def esc(value):
    return html.escape(str(value), quote=True)


def page(title, body):
    """Wrap a rendered body in a complete, well-formed HTML document."""
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, "
            "initial-scale=1\">\n"
            "<title>%s</title>\n<style>%s</style>\n</head>\n<body>\n%s\n"
            "</body>\n</html>\n" % (esc(title), STYLE, body))


def render_landing(recent, missing=None):
    """The `/` page: a vault-name form plus the recent-vault area."""
    parts = ["<h1>mvault viewer</h1>"]
    if missing:
        parts.append('<p class="not-found">Vault %s not found.</p>'
                     % esc(missing))
    parts.append(
        '<form method="post" action="/">\n'
        '<label for="catalog">Vault name</label>\n'
        '<input type="text" id="catalog" name="catalog" value="" '
        'placeholder="vault" autofocus>\n'
        '<button type="submit">Open</button>\n'
        '</form>')
    if recent:
        parts.append("<h2>Recent vaults</h2>")
        items = ['<li><a href="%s">%s</a></li>' % (esc(route), esc(vault))
                 for vault, route in recent]
        parts.append('<ul class="recent">\n%s\n</ul>' % "\n".join(items))
    return page("mvault viewer", "\n".join(parts))


def render_entry_item(name, category, entry, version, names, highlight):
    """One listing row: link, downloaded state and (v3) removed state."""
    entry_id = entry.get("id") if isinstance(entry, dict) else None
    entry_id = entry_id if is_str(entry_id) else ""
    title = digest_title(entry, version) if isinstance(entry, dict) else ""
    downloaded = is_downloaded(names, entry_id)
    removed = is_removed(entry, version) if isinstance(entry, dict) else False

    classes = ["entry", "downloaded" if downloaded else "not-downloaded"]
    if removed:
        classes.append("removed")
    if highlight is not None and entry_id == highlight:
        classes.append("highlighted")

    href = "/catalog/%s/%s/%s" % (urllib.parse.quote(name, safe=""),
                                  urllib.parse.quote(category, safe=""),
                                  urllib.parse.quote(entry_id, safe=""))
    states = ['<span class="state download-state">%s</span>'
              % ("downloaded" if downloaded else "not downloaded")]
    if removed:
        states.append('<span class="state removed-state">removed</span>')
    return '<li class="%s" id="entry-%s"><a href="%s">%s</a> %s</li>' % (
        " ".join(classes), esc(entry_id), esc(href),
        esc(title or entry_id), "".join(states))


def render_category(name, catalog, version, category, highlight=None):
    """The `/catalog/<name>/<category>` listing, in catalog-array order."""
    buckets = dict((route, entries)
                   for _, route, entries in viewer_buckets(catalog, version))
    entries = buckets.get(category, [])
    names = media_names(name)

    nav = []
    for route in viewer_categories(version):
        css = ' class="current"' if route == category else ""
        nav.append('<a href="/catalog/%s/%s"%s>%s</a>'
                   % (urllib.parse.quote(name, safe=""),
                      urllib.parse.quote(route, safe=""), css, esc(route)))

    parts = ['<h1><a href="/">mvault</a> / %s</h1>' % esc(name),
             '<p class="meta">catalog version %s</p>' % esc(version),
             '<nav class="categories">%s</nav>' % "\n".join(nav)]
    if highlight is not None:
        parts.append('<p class="selected">Entry %s</p>' % esc(highlight))
    rows = [render_entry_item(name, category, entry, version, names, highlight)
            for entry in entries if isinstance(entry, dict)]
    if rows:
        parts.append('<ul class="entries">\n%s\n</ul>' % "\n".join(rows))
    else:
        parts.append('<p class="empty">No entries in %s.</p>' % esc(category))
    return page("%s / %s" % (name, category), "\n".join(parts))


def render_error(status, message):
    return page("mvault viewer -- %d" % status,
                "<h1>%d</h1>\n<p>%s</p>\n<p><a href=\"/\">Back to mvault"
                "</a></p>" % (status, esc(message)))


# ---- request handling -----------------------------------------------------
class ViewerHandler(BaseHTTPRequestHandler):
    """Routes `/` and `/catalog/...`; never leaks an exception to the client."""

    server_version = "mvault"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # ---- plumbing -------------------------------------------------------
    def log_message(self, *args):
        pass  # the CLI owns stdout; request logging would only be noise

    def respond(self, status, body, content_type="text/html; charset=utf-8"):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def redirect(self, location):
        """A `302` redirect carrying a small body for non-following clients."""
        body = page("Redirecting",
                    '<p><a href="%s">Continue</a></p>' % esc(location))
        payload = body.encode("utf-8")
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def fail(self, status, message):
        self.respond(status, render_error(status, message))

    def segments(self):
        """Decoded path segments; `%2F` never becomes a separator."""
        raw = urllib.parse.urlsplit(self.path).path
        return [urllib.parse.unquote(part) for part in raw.split("/") if part]

    # ---- verbs ----------------------------------------------------------
    def do_GET(self):
        self.dispatch(self.route_get)

    def do_HEAD(self):
        self.dispatch(self.route_get)

    def do_POST(self):
        self.dispatch(self.route_post)

    def dispatch(self, route):
        """Run a route, turning any unexpected failure into a clean page."""
        try:
            route()
        except (BrokenPipeError, ConnectionResetError):
            raise
        except Exception:
            try:
                self.fail(500, "The viewer could not complete this request.")
            except Exception:
                pass

    # ---- routes ---------------------------------------------------------
    def route_get(self):
        parts = self.segments()
        if not parts:
            return self.landing()
        if parts[0] != "catalog":
            return self.fail(404, "No such page.")
        if len(parts) == 1:
            return self.redirect("/")
        return self.catalog(parts[1], parts[2:])

    def route_post(self):
        parts = self.segments()
        if parts:
            return self.fail(404, "No such page.")
        length = self.headers.get("Content-Length")
        try:
            size = max(0, int(length))
        except (TypeError, ValueError):
            size = 0
        raw = self.rfile.read(size).decode("utf-8", "replace") if size else ""
        fields = urllib.parse.parse_qs(raw, keep_blank_values=True)
        values = fields.get("catalog") or []
        wanted = values[0].strip() if values else ""
        if not wanted:
            return self.redirect("/")
        return self.redirect("/catalog/%s"
                             % urllib.parse.quote(wanted, safe=""))

    def landing(self):
        missing = self.server.take_missing()
        recent = [(vault, viewer_route(vault))
                  for vault in read_recent()]
        self.respond(200, render_landing(recent, missing))

    def catalog(self, name, rest):
        loaded = viewer_load(name)
        if loaded is None:
            # A vault that cannot be read is reported on the landing page.
            self.server.set_missing(name)
            return self.redirect("/")
        catalog, version = loaded
        record_recent(name)
        if not rest:
            return self.redirect(viewer_route(name, version))
        category = rest[0]
        if category not in viewer_categories(version):
            return self.redirect(viewer_route(name, version))
        highlight = rest[1] if len(rest) > 1 else None
        if len(rest) > 2:
            return self.fail(404, "No such page.")
        self.respond(200, render_category(name, catalog, version, category,
                                          highlight))


class ViewerServer(ThreadingHTTPServer):
    """Threading HTTP server plus the pending vault-not-found notice."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler=ViewerHandler):
        ThreadingHTTPServer.__init__(self, address, handler)
        self._missing = None
        self._lock = threading.Lock()

    def set_missing(self, name):
        with self._lock:
            self._missing = name

    def take_missing(self):
        """Read and clear the pending notice, so it shows exactly once."""
        with self._lock:
            missing, self._missing = self._missing, None
        return missing


def link_host(host):
    """The host a browser should use to reach a server bound to `host`."""
    if host in ("", "0.0.0.0", "::", "*"):
        return DEFAULT_HOST
    return host


def open_browser(url):
    """Open `url` in a browser without ever blocking or failing the server."""
    def target():
        try:
            webbrowser.open(url)
        except Exception:
            pass

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


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
    """Metadata phase, then download phase; either can be skipped."""
    name = args.name
    catalog, version = load_catalog(name)

    counts = None
    changes = {}
    stamp = None
    if not args.skip_metadata:
        payload = fetch_source(catalog["source"])
        stamp = format_ts(sync_timestamp(catalog))
        counts, changes = apply_sync(catalog, payload, stamp)
        # Persist before downloading: a download failure must never cost the
        # metadata this run collected.
        write_catalog(name, catalog)

    if not args.skip_download:
        limits = {category: getattr(args, category)
                  for category in CATEGORIES}
        download_phase(name, catalog, limits, args.format)

    if counts is None:
        return 0

    total = sum(len(catalog[category]) for category in CATEGORIES)
    if version != CATALOG_VERSION:
        print("migrated vault %s from version %d to version %d"
              % (name, version, CATALOG_VERSION))
    print("synced vault %s at %s (%d entries)" % (name, stamp, total))
    print("changes: %d added, %d removed, %d updated"
          % (counts["added"], counts["removed"], counts["updated"]))
    for line in render_sections(sync_sections(catalog, changes, name,
                                              args.host, args.port)):
        print(line)
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
    """Read-only summary of notable changes; never writes to the vault.

    The catalog is read in its own format -- v1, v2 and v3 are each classified
    against the tracked fields and history key ordering they actually use, so
    no migration (in memory or on disk) is involved.
    """
    name = args.name
    catalog, version = read_catalog_file(name)
    print(render_digest(name, catalog, version, args.host, args.port))
    return 0


def cmd_serve(args):
    """Run the local browser viewer until interrupted."""
    host = args.host if args.host is not None else DEFAULT_HOST
    port = args.port if args.port is not None else DEFAULT_PORT
    try:
        httpd = ViewerServer((host, port))
    except OSError as exc:
        raise MvaultError("could not bind %s:%d: %s" % (host, port, exc))

    origin = "%s://%s:%d" % (DEFAULT_SCHEME, link_host(host), port)
    target = origin + (viewer_route(args.name) if args.name else "/")
    # The socket is already listening, so the browser cannot outrun the server.
    open_browser(target)
    print("serving mvault viewer on %s" % target)
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def port_number(text):
    """argparse type for `--port`."""
    if not re.match(r"^\d+$", text.strip()):
        raise argparse.ArgumentTypeError("%r is not a port number" % text)
    value = int(text)
    if not 0 <= value <= 65535:
        raise argparse.ArgumentTypeError("%r is not a port number" % text)
    return value


def add_viewer_link_options(parser):
    """`--host` / `--port` overrides for the viewer links a report prints."""
    parser.add_argument(
        "--host", metavar="HOST", default=None,
        help="viewer host used in printed links (default %s)" % DEFAULT_HOST)
    parser.add_argument(
        "--port", metavar="PORT", type=port_number, default=None,
        help="viewer port used in printed links (default %d)" % DEFAULT_PORT)


def non_negative_int(text):
    """argparse type for `--episodes` / `--streams` / `--clips`."""
    if not re.match(r"^\d+$", text.strip()):
        raise argparse.ArgumentTypeError(
            "%r is not a non-negative integer" % text)
    return int(text)


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
    for category in CATEGORIES:
        sync_parser.add_argument(
            "--%s" % category, metavar="N", type=non_negative_int, default=None,
            help="maximum number of %s media downloads" % category[:-1])
    sync_parser.add_argument(
        "--skip-metadata", action="store_true",
        help="skip the source fetch and metadata update")
    sync_parser.add_argument(
        "--skip-download", action="store_true",
        help="skip the download phase")
    sync_parser.add_argument(
        "--format", metavar="EXT", default=None,
        help="override the media download format and output extension")
    add_viewer_link_options(sync_parser)
    sync_parser.set_defaults(func=cmd_sync)

    migrate_parser = subparsers.add_parser(
        "migrate", help="convert a legacy catalog to the native version 3 format")
    migrate_parser.add_argument("name", help="existing vault directory")
    migrate_parser.set_defaults(func=cmd_migrate)

    digest_parser = subparsers.add_parser(
        "digest", help="print a read-only summary of a vault")
    digest_parser.add_argument("name", help="existing vault directory")
    add_viewer_link_options(digest_parser)
    digest_parser.set_defaults(func=cmd_digest)

    serve_parser = subparsers.add_parser(
        "serve", help="run the local browser viewer for vaults")
    serve_parser.add_argument(
        "name", nargs="?", default=None,
        help="vault to open in the browser (default: the landing page)")
    serve_parser.add_argument(
        "--host", metavar="HOST", default=None,
        help="bind host (default %s)" % DEFAULT_HOST)
    serve_parser.add_argument(
        "--port", metavar="PORT", type=port_number, default=None,
        help="bind port (default %d)" % DEFAULT_PORT)
    serve_parser.set_defaults(func=cmd_serve)

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
