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
vault of any supported version in its own format and never writes to it. Each
entry has a detail page carrying its current metadata, a source-platform link
and machine-readable `views`/`likes` chart data normalized to ISO 8601
timestamps whatever the vault version, plus `/vault/<name>/media/<file>` and
`/vault/<name>/preview/<id>` endpoints that serve downloaded assets. The
human-facing change reports (`digest` and the post-sync summary) append a
viewer link to every changed-entry line.

Entry detail pages are also the one part of the viewer that writes: `POST`,
`PATCH` and `DELETE` on `/catalog/<name>/<category>/<id>` manage a list of
user annotations stored on the entry. Annotations are a version 3 field, so a
mutation against a v1 or v2 vault migrates the whole catalog first and
persists the migration together with the annotation -- leaving `catalog.bak`
holding the state from before both.
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
import uuid
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

# File extension -> Content-Type, for the viewer's static file endpoints. The
# first mapping wins, so the canonical type of a shared extension is the one
# listed first above.
EXTENSION_TYPES = {}
for _type, _ext in CONTENT_TYPE_EXTENSIONS.items():
    EXTENSION_TYPES.setdefault(_ext, _type)
del _type, _ext

# Served when a preview file carries an extension nothing recognises: the
# preview endpoint is documented to hand back an image.
FALLBACK_IMAGE_TYPE = "image/jpeg"
FALLBACK_MEDIA_TYPE = "application/octet-stream"

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

# User-managed annotations. They live on the entry object of a version 3
# catalog, so writing one to a v1/v2 vault migrates it first.
ANNOTATION_FIELD = "annotations"
ANNOTATION_METHODS = ("POST", "PATCH", "DELETE")
TIMECODE_QUERY = "timecode"
# `SS`, `MM:SS` or `HH:MM:SS`; components are non-negative integers with any
# number of leading zeros and no conventional clock bounds.
TIMECODE_RE = re.compile(r"^\d+(?::\d+){0,2}$")
ANNOTATION_ID_LENGTH = 12

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


def asset_names(name, directory):
    """Every filename currently sitting in `<vault>/<directory>/`."""
    try:
        return os.listdir(os.path.join(name, directory))
    except OSError:
        return []


def media_names(name):
    """Every filename currently sitting in `<vault>/media/`."""
    return asset_names(name, MEDIA_DIR)


def preview_names(name):
    """Every filename currently sitting in `<vault>/previews/`."""
    return asset_names(name, PREVIEW_DIR)


def is_downloaded(names, entry_id):
    """An entry is downloaded when a media filename contains its `id`."""
    if not entry_id:
        return False
    return any(entry_id in filename for filename in names)


def asset_match(names, entry_id):
    """The saved filename an entry's asset is served from, or None.

    Containment is the spec's own matching rule. When several names contain
    the id, a finished file beats an in-progress `.part` artifact and the rest
    is settled alphabetically, so the chosen name never depends on the order
    the filesystem happened to list the directory in.
    """
    if not entry_id:
        return None
    matches = [filename for filename in names if entry_id in filename]
    if not matches:
        return None
    matches.sort(key=lambda item: (item.endswith(PARTIAL_SUFFIX), item))
    return matches[0]


def content_type_for(filename, fallback):
    """Content-Type for a saved asset, decided by its file extension."""
    extension = os.path.splitext(filename)[1].lstrip(".").lower()
    if extension in EXTENSION_TYPES:
        return EXTENSION_TYPES[extension]
    guess = mimetypes.guess_type(filename)[0]
    return guess or fallback


def safe_child(directory, parts):
    """`directory/<parts...>`, or None when the parts escape the directory.

    Every segment is checked before it is joined -- a segment holding a
    separator, a `..`, or an absolute path is refused outright -- and the
    resolved path is then confirmed to still live under `directory`, so a
    symlink cannot smuggle the request out either.
    """
    if not parts:
        return None
    for part in parts:
        if not part or part in (os.curdir, os.pardir):
            return None
        if "/" in part or "\\" in part or "\x00" in part:
            return None
        if os.path.isabs(part):
            return None
    target = os.path.join(directory, *parts)
    base = os.path.realpath(directory)
    resolved = os.path.realpath(target)
    if resolved != base and not resolved.startswith(base + os.sep):
        return None
    return target


def is_removed(entry, version):
    """Latest `removed` value, which only version 3 catalogs carry."""
    if version != CATALOG_VERSION:
        return False
    return digest_current(digest_history(entry, "removed"), version) is True


# ---- annotations ----------------------------------------------------------
class AnnotationError(Exception):
    """A request-level annotation failure carrying its HTTP status."""

    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status
        self.message = message


# One writer at a time: the viewer is threaded, and every annotation is a
# read-modify-write of the whole catalog file.
ANNOTATION_LOCK = threading.Lock()


def parse_timecode(value):
    """`SS`, `MM:SS` or `HH:MM:SS` text as whole seconds.

    Components are non-negative integers; leading zeros are allowed and
    conventional clock bounds are not enforced, so `"90:00"` is 5400 seconds.
    A JSON integer is already whole seconds and is taken as given.
    """
    if is_int(value):
        if value < 0:
            raise AnnotationError(400, "invalid timecode %r: a timecode must "
                                       "not be negative" % value)
        return value
    if not is_str(value) or not TIMECODE_RE.match(value):
        raise AnnotationError(
            400, "invalid timecode format %r: expected SS, MM:SS or HH:MM:SS "
                 "with non-negative integer components" % value)
    seconds = 0
    for part in value.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


def format_timecode(seconds):
    """Whole seconds as clock text: `M:SS`, or `H:MM:SS` past an hour."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, secs)
    return "%d:%02d" % (minutes, secs)


def entry_annotations(entry):
    """The entry's stored annotation list -- `[]` when it has none."""
    value = entry.get(ANNOTATION_FIELD) if isinstance(entry, dict) else None
    return value if isinstance(value, list) else []


def annotation_list(entry):
    """The entry's annotation list, created in place when it is missing."""
    value = entry.get(ANNOTATION_FIELD)
    if not isinstance(value, list):
        value = []
        entry[ANNOTATION_FIELD] = value
    return value


def new_annotation_id(annotations):
    """An id no annotation of this entry already carries."""
    taken = set(item.get("id") for item in annotations
                if isinstance(item, dict))
    while True:
        candidate = uuid.uuid4().hex[:ANNOTATION_ID_LENGTH]
        if candidate not in taken:
            return candidate


def require_fields(data, fields):
    """Every named field must be present and hold a string."""
    missing = [field for field in fields
               if field not in data or data[field] is None]
    if missing:
        raise AnnotationError(
            400, "missing required field%s: %s"
                 % ("" if len(missing) == 1 else "s",
                    ", ".join(repr(field) for field in missing)))
    for field in fields:
        if field == TIMECODE_QUERY:
            continue
        if not is_str(data[field]):
            raise AnnotationError(400, "field %r must be a string" % field)


def optional_text(data, field):
    """An optional string-or-null field, or `_MISSING` when it is absent."""
    if field not in data:
        return _MISSING
    value = data[field]
    if value is None or is_str(value):
        return value
    raise AnnotationError(400,
                          "field %r must be a string or null" % field)


def find_annotation(entry, data):
    """The annotation named by `id`, which must exist inside this entry."""
    require_fields(data, ("id",))
    wanted = data["id"]
    for item in entry_annotations(entry):
        if isinstance(item, dict) and item.get("id") == wanted:
            return item
    raise AnnotationError(404, "no annotation %s on entry %s"
                          % (wanted, entry.get("id")))


def annotation_create(entry, data):
    """Append a new annotation; returns its timecode in whole seconds."""
    require_fields(data, ("title", TIMECODE_QUERY))
    seconds = parse_timecode(data[TIMECODE_QUERY])
    body = optional_text(data, "body")
    annotations = annotation_list(entry)
    annotations.append({
        "id": new_annotation_id(annotations),
        TIMECODE_QUERY: seconds,
        "title": data["title"],
        "body": None if body is _MISSING else body,
    })
    return seconds


def annotation_update(entry, data):
    """Replace the `title` and/or `body` of one existing annotation."""
    require_fields(data, ("id",))
    title = optional_text(data, "title")
    body = optional_text(data, "body")
    if title is _MISSING and body is _MISSING:
        raise AnnotationError(400, "an update requires at least one of "
                                   "'title' or 'body'")
    if title is None:
        raise AnnotationError(400, "field 'title' must be a string")
    target = find_annotation(entry, data)
    if title is not _MISSING:
        target["title"] = title
    if body is not _MISSING:
        target["body"] = body
    return None


def annotation_delete(entry, data):
    """Drop one existing annotation, keeping the order of the rest."""
    target = find_annotation(entry, data)
    entry[ANNOTATION_FIELD] = [item for item in entry_annotations(entry)
                               if item is not target]
    return None


ANNOTATION_ACTIONS = {
    "POST": annotation_create,
    "PATCH": annotation_update,
    "DELETE": annotation_delete,
}


def annotation_category(category, version):
    """The category the entry lives in once the catalog is at version 3.

    A v1 vault is addressed through its own `entries` route, but migration
    moves every v1 entry into `episodes`, so that is where the annotation --
    and the redirect that follows it -- ends up.
    """
    return "episodes" if version == 1 else category


def annotate(name, category, entry_id, method, data):
    """Apply one annotation mutation to a vault and persist the result.

    A v1/v2 catalog is migrated to version 3 in memory first, because the
    `annotations` field does not exist in the legacy shapes; the migration and
    the annotation are then persisted by a single write, so `catalog.bak`
    holds the state from before both changes. Nothing is written unless the
    mutation itself succeeds.
    """
    with ANNOTATION_LOCK:
        catalog, version = read_catalog_file(name)
        migrated = migrate_catalog(catalog, version)
        target = annotation_category(category, version)
        entry = viewer_find_entry(migrated, CATALOG_VERSION, target, entry_id)
        if entry is None:
            raise AnnotationError(404, "No entry %s in %s."
                                  % (entry_id, category))
        seconds = ANNOTATION_ACTIONS[method](entry, data)
        write_catalog(name, migrated)
        return target, seconds


# ---- entry detail ---------------------------------------------------------
CHART_FIELDS = ("views", "likes")


def viewer_find_entry(catalog, version, category, entry_id):
    """The entry carrying `entry_id` inside `category` -- and only there.

    The lookup never falls back to another category, so the same id appearing
    in two categories keeps two separate detail pages.
    """
    buckets = dict((route, entries)
                   for _, route, entries in viewer_buckets(catalog, version))
    for entry in buckets.get(category, []):
        if isinstance(entry, dict) and entry.get("id") == entry_id:
            return entry
    return None


def chart_timestamp(key, version):
    """One history key in the chart's uniform ISO 8601 output format.

    Version 1 stores UNIX-epoch strings, which are converted to UTC; v2 and v3
    already store ISO 8601 and pass through untouched.
    """
    if version == 1 and is_str(key) and EPOCH_KEY_RE.match(key):
        try:
            return epoch_to_iso(key)
        except (ValueError, OverflowError, OSError):
            return key
    return key


def chart_points(history, version):
    """Chart points for one tracked field, oldest first.

    Nothing is filtered or replaced: a `null` stays a `null`, and repeated
    values stay repeated. Only the key format and the ordering rule differ by
    version.
    """
    if not isinstance(history, dict):
        return []
    keys = sorted(history, key=epoch_sort_key if version == 1 else str)
    return [{"timestamp": chart_timestamp(key, version), "value": history[key]}
            for key in keys]


def chart_payload(entry, version):
    """The machine-readable `views`/`likes` payload embedded in a detail page."""
    return dict((field, chart_points(digest_history(entry, field), version))
                for field in CHART_FIELDS)


def entry_source_link(catalog, version, entry_id):
    """The source-platform URL for one entry, derived per catalog version."""
    if version == 1:
        base = v1_source_url(catalog.get("source_id") or "")
    else:
        base = catalog.get("source")
        base = base if is_str(base) else ""
    return "%s/entry/%s" % (base.rstrip("/"), entry_id)


def media_static_url(name, filename):
    """The `/vault/<name>/media/<file>` URL a saved media file is served from."""
    return "/vault/%s/media/%s" % (urllib.parse.quote(name, safe=""),
                                   urllib.parse.quote(filename, safe=""))


def preview_static_url(name, entry_id):
    """The `/vault/<name>/preview/<id>` URL an entry's preview is served from."""
    return "/vault/%s/preview/%s" % (urllib.parse.quote(name, safe=""),
                                     urllib.parse.quote(entry_id, safe=""))


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
span.state { font-size: .8rem; margin-left: .5rem; color: #555; }
span.state.removed-state { color: #a40e26; }
p.not-found { background: #fdeaea; border-left: 4px solid #a40e26;
              padding: .6rem; }
dl.metadata { display: grid; grid-template-columns: max-content 1fr;
              gap: .2rem 1rem; }
dl.metadata dt { color: #555; }
dl.metadata dd { margin: 0; }
p.removed-notice { background: #fdeaea; border-left: 4px solid #a40e26;
                   padding: .6rem; }
figure.chart { margin: 1rem 0; }
figure.chart figcaption { color: #555; font-size: .9rem; }
svg.chart line.axis { stroke: #c9c9c9; stroke-width: 1; }
svg.chart polyline.series { fill: none; stroke: #0b5bd3; stroke-width: 2; }
svg.chart circle.point { fill: #0b5bd3; }
video.media, img.preview { max-width: 100%; }
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


def render_entry_item(name, category, entry, version, names):
    """One listing row: link, downloaded state and (v3) removed state."""
    entry_id = entry.get("id") if isinstance(entry, dict) else None
    entry_id = entry_id if is_str(entry_id) else ""
    title = digest_title(entry, version) if isinstance(entry, dict) else ""
    downloaded = is_downloaded(names, entry_id)
    removed = is_removed(entry, version) if isinstance(entry, dict) else False

    classes = ["entry", "downloaded" if downloaded else "not-downloaded"]
    if removed:
        classes.append("removed")

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


def render_category(name, catalog, version, category):
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
    rows = [render_entry_item(name, category, entry, version, names)
            for entry in entries if isinstance(entry, dict)]
    if rows:
        parts.append('<ul class="entries">\n%s\n</ul>' % "\n".join(rows))
    else:
        parts.append('<p class="empty">No entries in %s.</p>' % esc(category))
    return page("%s / %s" % (name, category), "\n".join(parts))


def embed_json(payload):
    """JSON safe to drop straight into a `<script>` element.

    Escaping the three markup characters keeps a catalog string that happens to
    contain `</script>` from ending the element early; a JSON reader decodes
    the escapes back to the original text.
    """
    text = json.dumps(payload)
    for char, escape in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e")):
        text = text.replace(char, escape)
    return text


CHART_WIDTH = 640
CHART_HEIGHT = 160
CHART_PAD = 24


def chart_numbers(points):
    """`[(index, value), ...]` for the points that can actually be plotted."""
    plottable = []
    for index, point in enumerate(points):
        value = point["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        plottable.append((index, float(value)))
    return plottable


def render_chart(field, points):
    """A small inline line chart, or "" when there is nothing to draw.

    A single-point history has no line to draw, so its chart is omitted; the
    machine-readable payload still carries the point either way.
    """
    plottable = chart_numbers(points)
    if len(points) < 2 or len(plottable) < 2:
        return ""
    low = min(value for _, value in plottable)
    high = max(value for _, value in plottable)
    span = (high - low) or 1.0
    width = CHART_WIDTH - 2 * CHART_PAD
    height = CHART_HEIGHT - 2 * CHART_PAD
    last = len(points) - 1

    coords = []
    for index, value in plottable:
        x = CHART_PAD + width * (index / last)
        y = CHART_PAD + height * (1 - (value - low) / span)
        coords.append((x, y))

    line = " ".join("%.2f,%.2f" % point for point in coords)
    dots = "".join('<circle class="point" cx="%.2f" cy="%.2f" r="2.5"></circle>'
                   % point for point in coords)
    label = "%s from %s to %s" % (field, points[0]["timestamp"],
                                  points[-1]["timestamp"])
    return (
        '<figure class="chart" id="chart-%s">\n'
        '<svg class="chart" viewBox="0 0 %d %d" role="img" '
        'aria-label="%s" preserveAspectRatio="none">\n'
        '<line class="axis" x1="%d" y1="%d" x2="%d" y2="%d"></line>\n'
        '<polyline class="series" points="%s"></polyline>\n%s\n</svg>\n'
        '<figcaption>%s over time (%s to %s)</figcaption>\n</figure>'
        % (esc(field), CHART_WIDTH, CHART_HEIGHT, esc(label),
           CHART_PAD, CHART_HEIGHT - CHART_PAD,
           CHART_WIDTH - CHART_PAD, CHART_HEIGHT - CHART_PAD,
           line, dots, esc(field), esc(points[0]["timestamp"]),
           esc(points[-1]["timestamp"])))


def render_annotations(entry, entry_path):
    """The entry's annotation list, in the order it is stored in.

    Each annotation links back to this page carrying its own `?timecode=`, so
    following it seeks playback to that position.
    """
    items = []
    for note in entry_annotations(entry):
        if not isinstance(note, dict):
            continue
        seconds = note.get(TIMECODE_QUERY)
        note_id = note.get("id")
        note_id = note_id if is_str(note_id) else ""
        title = note.get("title")
        body = note.get("body")
        parts = []
        if is_int(seconds):
            parts.append('<a class="annotation-seek" href="%s?%s=%d">%s</a> '
                         '<span class="annotation-seconds">%d s</span>'
                         % (esc(entry_path), TIMECODE_QUERY, seconds,
                            esc(format_timecode(seconds)), seconds))
        elif seconds is not None:
            parts.append('<span class="annotation-seconds">%s</span>'
                         % esc(seconds))
        parts.append('<span class="annotation-title">%s</span>'
                     % esc("" if title is None else title))
        if body is not None:
            parts.append('<p class="annotation-body">%s</p>' % esc(body))
        items.append('<li class="annotation" id="annotation-%s" '
                     'data-annotation-id="%s"%s>%s</li>'
                     % (esc(note_id), esc(note_id),
                        ' data-timecode="%d"' % seconds if is_int(seconds)
                        else "", "\n".join(parts)))
    heading = '<h2>Annotations</h2>'
    if not items:
        inner = '<p class="empty annotations-empty">No annotations.</p>'
    else:
        inner = '<ol class="annotation-list">\n%s\n</ol>' % "\n".join(items)
    return ('<section class="annotations" id="annotations">\n%s\n%s\n'
            '</section>' % (heading, inner))


def render_entry(name, catalog, version, category, entry, seek=None):
    """The `/catalog/<name>/<category>/<id>` detail page."""
    entry_id = entry.get("id")
    entry_id = entry_id if is_str(entry_id) else str(entry_id or "")
    title = digest_title(entry, version)
    description = digest_current(digest_history(entry, "description"), version)
    if description is _MISSING:
        description = ""
    listing = "/catalog/%s/%s" % (urllib.parse.quote(name, safe=""),
                                  urllib.parse.quote(category, safe=""))
    source_link = entry_source_link(catalog, version, entry_id)

    parts = ['<h1><a href="/">mvault</a> / <a href="%s">%s</a> / %s</h1>'
             % (esc(listing), esc(name), esc(title))]
    if is_removed(entry, version):
        parts.append('<p class="removed-notice">This entry has been removed '
                     'at the source.</p>')
    parts.append('<p class="description">%s</p>' % esc(description))

    media = asset_match(media_names(name), entry_id)
    if media:
        url = media_static_url(name, media)
        # A media fragment makes the browser start at the requested second
        # without any scripting; the attribute states the same position for
        # anything reading the markup.
        src = url if seek is None else "%s#t=%d" % (url, seek)
        extra = "" if seek is None else ' data-timecode="%d"' % seek
        parts.append('<video class="media" controls preload="none" src="%s"%s>'
                     '<a class="media-link" href="%s">%s</a></video>'
                     % (esc(src), extra, esc(src), esc(media)))
    if seek is not None:
        parts.append('<p class="seek" data-timecode="%d">Playback starts at '
                     '<span class="seek-timecode">%s</span> '
                     '(<span class="seek-seconds">%d s</span>).</p>'
                     % (seek, esc(format_timecode(seek)), seek))
    if asset_match(preview_names(name), entry_id):
        parts.append('<img class="preview" alt="Preview image for %s" src="%s">'
                     % (esc(title), esc(preview_static_url(name, entry_id))))

    rows = [("Published", esc(entry.get("published", ""))),
            ("Dimensions", '<span class="width">%s</span> &#215; '
                           '<span class="height">%s</span>'
                           % (esc(entry.get("width", "")),
                              esc(entry.get("height", "")))),
            ("Source", '<a class="source-link" href="%s">%s</a>'
                       % (esc(source_link), esc(source_link)))]
    if media:
        rows.append(("Media file", esc(media)))
    parts.append('<dl class="metadata">\n%s\n</dl>'
                 % "\n".join("<dt>%s</dt><dd>%s</dd>" % row for row in rows))

    payload = chart_payload(entry, version)
    parts.append('<script id="chart-data" type="application/json">%s</script>'
                 % embed_json(payload))
    for field in CHART_FIELDS:
        figure = render_chart(field, payload[field])
        if figure:
            parts.append(figure)

    entry_path = "/catalog/%s/%s/%s" % (urllib.parse.quote(name, safe=""),
                                        urllib.parse.quote(category, safe=""),
                                        urllib.parse.quote(entry_id, safe=""))
    parts.append(render_annotations(entry, entry_path))

    parts.append('<p class="back"><a class="back-link" href="%s">Back to %s'
                 '</a></p>' % (esc(listing), esc(category)))
    return page("%s / %s" % (name, title), "\n".join(parts))


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

    def respond_bytes(self, status, payload, content_type):
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

    def do_PATCH(self):
        self.dispatch(lambda: self.route_annotation("PATCH"))

    def do_DELETE(self):
        self.dispatch(lambda: self.route_annotation("DELETE"))

    def read_body(self):
        """The request body, read whole so the connection stays usable."""
        length = self.headers.get("Content-Length")
        try:
            size = max(0, int(length))
        except (TypeError, ValueError):
            size = 0
        return self.rfile.read(size) if size else b""

    def query_value(self, key):
        """One query-string value of this request, or None."""
        query = urllib.parse.urlsplit(self.path).query
        values = urllib.parse.parse_qs(query).get(key)
        return values[0] if values else None

    def seek_position(self):
        """The `?timecode=` position to start playback at, or None.

        A value that is not a timecode is ignored rather than refused: the
        query parameter only decorates a page that renders either way.
        """
        raw = self.query_value(TIMECODE_QUERY)
        if raw is None:
            return None
        try:
            return parse_timecode(raw)
        except AnnotationError:
            return None

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
        if parts[0] == "vault":
            return self.static_asset(parts[1:])
        if parts[0] != "catalog":
            return self.fail(404, "No such page.")
        if len(parts) == 1:
            return self.redirect("/")
        return self.catalog(parts[1], parts[2:])

    def route_post(self):
        parts = self.segments()
        raw = self.read_body()
        if parts:
            # `POST /catalog/<name>/<category>/<id>` creates an annotation.
            return self.route_annotation("POST", parts, raw)
        fields = urllib.parse.parse_qs(raw.decode("utf-8", "replace"),
                                       keep_blank_values=True)
        values = fields.get("catalog") or []
        wanted = values[0].strip() if values else ""
        if not wanted:
            return self.redirect("/")
        return self.redirect("/catalog/%s"
                             % urllib.parse.quote(wanted, safe=""))

    # ---- annotations ----------------------------------------------------
    def route_annotation(self, method, parts=None, raw=None):
        """`POST`/`PATCH`/`DELETE` on an entry detail route."""
        if parts is None:
            parts = self.segments()
        if raw is None:
            raw = self.read_body()
        if len(parts) != 4 or parts[0] != "catalog":
            return self.fail(404, "No such page.")
        name, category, entry_id = parts[1], parts[2], parts[3]

        loaded = viewer_load(name)
        if loaded is None:
            # Same treatment as a GET: an unreadable vault is reported on the
            # landing page rather than as an error here.
            self.server.set_missing(name)
            return self.redirect("/")
        version = loaded[1]
        if category not in viewer_categories(version):
            return self.redirect(viewer_route(name, version))

        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return self.fail(400, "Request body must be a JSON object.")
        if not isinstance(data, dict):
            return self.fail(400, "Request body must be a JSON object.")

        try:
            target, seconds = annotate(name, category, entry_id, method, data)
        except AnnotationError as exc:
            return self.fail(exc.status, exc.message)
        except MvaultError as exc:
            # Migration or persistence failed; the catalog on disk is the one
            # that was there before the request.
            return self.fail(500, "Could not update vault %s: %s"
                             % (name, exc))

        location = "/catalog/%s/%s/%s" % (
            urllib.parse.quote(name, safe=""),
            urllib.parse.quote(target, safe=""),
            urllib.parse.quote(entry_id, safe=""))
        if seconds is not None:
            location += "?%s=%d" % (TIMECODE_QUERY, seconds)
        return self.redirect(location)

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
        if len(rest) > 2:
            return self.fail(404, "No such page.")
        if len(rest) == 2:
            entry = viewer_find_entry(catalog, version, category, rest[1])
            if entry is None:
                return self.fail(404, "No entry %s in %s."
                                 % (rest[1], category))
            return self.respond(200, render_entry(name, catalog, version,
                                                  category, entry,
                                                  self.seek_position()))
        self.respond(200, render_category(name, catalog, version, category))

    # ---- static assets --------------------------------------------------
    def static_asset(self, rest):
        """`/vault/<name>/media/<file>` and `/vault/<name>/preview/<id>`."""
        if len(rest) < 2:
            return self.fail(404, "No such page.")
        name, kind, tail = rest[0], rest[1], rest[2:]
        if not valid_vault_name(name):
            # A name that is itself a traversal attempt never reaches the disk.
            return self.fail(403, "Refused.")
        if viewer_load(name) is None:
            self.server.set_missing(name)
            return self.redirect("/")
        if kind == MEDIA_DIR:
            return self.serve_media(name, tail)
        if kind == PREVIEW_REMOTE:
            return self.serve_preview(name, tail)
        return self.fail(404, "No such page.")

    def serve_media(self, name, tail):
        """Serve `<vault>/media/<file>` by its exact saved filename."""
        target = safe_child(os.path.join(name, MEDIA_DIR), tail)
        if target is None:
            return self.fail(403, "Refused.")
        return self.send_asset(target, FALLBACK_MEDIA_TYPE)

    def serve_preview(self, name, tail):
        """Serve the `<vault>/previews/` file whose name contains `<id>`."""
        if len(tail) != 1:
            return self.fail(404, "No such file.")
        entry_id = tail[0]
        if not valid_vault_name(entry_id):
            return self.fail(403, "Refused.")
        match = asset_match(preview_names(name), entry_id)
        if match is None:
            return self.fail(404, "No preview for %s." % entry_id)
        target = safe_child(os.path.join(name, PREVIEW_DIR), [match])
        if target is None:
            return self.fail(403, "Refused.")
        return self.send_asset(target, FALLBACK_IMAGE_TYPE)

    def send_asset(self, target, fallback_type):
        """Hand back a saved asset, or a clean `404` when it is not there."""
        if not os.path.isfile(target):
            return self.fail(404, "No such file.")
        try:
            with open(target, "rb") as handle:
                payload = handle.read()
        except OSError:
            return self.fail(404, "No such file.")
        return self.respond_bytes(200, payload,
                                  content_type_for(target, fallback_type))


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
