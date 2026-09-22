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
import json
import mimetypes
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
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

    Returns ``(version, source_url, [(label, entries), ...])``.
    """
    raw = read_catalog_file(name)
    version = catalog_version(raw, name)
    if version == 1:
        source_id = raw.get(V1_SOURCE_FIELD)
        source = v1_source_url(source_id) if isinstance(source_id, str) else "(unknown)"
        entries = raw.get(V1_ENTRIES_FIELD)
        groups = [(V1_GROUP_LABEL, entries if isinstance(entries, list) else [])]
        return version, source, groups

    source = raw.get("source")
    if not isinstance(source, str) or not source:
        source = "(unknown)"
    groups = []
    for category in CATEGORIES:
        entries = raw.get(category)
        groups.append((category.capitalize(), entries if isinstance(entries, list) else []))
    return version, source, groups


def digest_lines(version, groups):
    """Build the grouped digest body; returns ``(lines, change_count)``."""
    lines = []
    total = 0
    for label, entries in groups:
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
    lines, total = digest_lines(version, groups)

    if lines:
        for line in lines:
            print(line)
        print("")
    else:
        print("No notable changes found.")
    print("Digest for vault '%s': catalog version %d, %d notable change%s, source %s"
          % (name, version, total, "" if total == 1 else "s", source))
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
    sync_parser.set_defaults(func=cmd_sync)

    digest_parser = subparsers.add_parser(
        "digest", help="summarise notable changes recorded in a vault"
    )
    digest_parser.add_argument("name", help="vault directory name")
    digest_parser.set_defaults(func=cmd_digest)

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
