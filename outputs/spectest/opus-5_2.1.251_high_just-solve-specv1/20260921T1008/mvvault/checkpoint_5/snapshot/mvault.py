#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Creates a vault directory holding a ``catalog.json`` and records the history of
tracked entry fields keyed by sync timestamp.
"""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"

CATALOG_VERSION = 3
SUPPORTED_VERSIONS = (1, 2, 3)
CATEGORIES = ("episodes", "streams", "clips")

# Version 1 catalogs only record a short platform identifier; the full source
# URL is derived from it deterministically.
V1_SOURCE_PREFIX = "https://media.example.com/channel/"

STATIC_FIELDS = ("id", "published", "width", "height")
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)
ANNOTATIONS_FIELD = "annotations"

DT_FORMAT = "%Y-%m-%dT%H:%M:%S"
DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

FETCH_FAILURE = "Source metadata fetch failure"

CATEGORY_LABELS = {
    "episodes": "Episodes",
    "streams": "Streams",
    "clips": "Clips",
}
V1_CATEGORY_LABEL = "Entries"

# Version 1 keeps every entry in a single flat ``entries`` array; v2 and v3
# split them across the three named categories.
V1_CATEGORY = "entries"
V1_CATEGORIES = (V1_CATEGORY,)
DEFAULT_CATEGORY = "episodes"

# Viewer -------------------------------------------------------------------
DEFAULT_VIEWER_SCHEME = "http"
DEFAULT_VIEWER_HOST = "127.0.0.1"
DEFAULT_VIEWER_PORT = 8840

VIEWER_STATE_NAME = "viewer.json"
RECENT_COOKIE = "mvault_recent"
MISSING_COOKIE = "mvault_missing"
RECENT_LIMIT = 24
RECENT_COOKIE_AGE = 60 * 60 * 24 * 365
MISSING_COOKIE_AGE = 60
MISSING_TTL_SECONDS = 300.0

# Static assets of a vault are served under their own route prefix so an entry
# detail page can point a <video>/<img> element straight at the stored file.
VAULT_ROUTE = "vault"
MEDIA_ROUTE_SEGMENT = "media"
PREVIEW_ROUTE_SEGMENT = "preview"

# Fields charted on an entry detail page, in display order.
CHART_FIELDS = ("views", "likes")
CHART_DATA_ELEMENT_ID = "mvault-chart-data"

ASSET_CHUNK_SIZE = 64 * 1024
DEFAULT_ASSET_MIME = "application/octet-stream"
DEFAULT_PREVIEW_MIME = "image/jpeg"
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav",
                    ".flac", ".weba")

# Download phase -----------------------------------------------------------
MEDIA_DIRNAME = "media"
PREVIEW_DIRNAME = "previews"
MEDIA_REMOTE_SEGMENT = "media"
PREVIEW_REMOTE_SEGMENT = "preview"

# Artifacts left behind by an interrupted download.  They never count as a
# stored asset, so a stale one can not block a later successful download.
PARTIAL_SUFFIX = ".part"
PARTIAL_SUFFIXES = (".part", ".partial", ".tmp", ".download", ".crdownload")

DEFAULT_EXTENSION = ".bin"
DOWNLOAD_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 0.0

# Status codes worth another attempt; everything else in the 4xx range is a
# permanent answer and is reported straight away.
TRANSIENT_STATUS = frozenset((408, 409, 423, 425, 429, 500, 502, 503, 504, 507, 509))

CONTENT_TYPE_EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/mpeg": ".mpeg",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "video/x-msvideo": ".avi",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/octet-stream": ".bin",
}


class MVaultError(Exception):
    """An error that should be reported to stderr with a non-zero exit."""


class SourceFetchError(MVaultError):
    """The source metadata could not be fetched or was malformed."""

    def __init__(self, detail: str = "") -> None:
        message = FETCH_FAILURE
        if detail:
            message = "{0}: {1}".format(FETCH_FAILURE, detail)
        super().__init__(message)


# ---------------------------------------------------------------------------
# datetime helpers
# ---------------------------------------------------------------------------


def format_dt(moment: datetime) -> str:
    """Render a datetime as ``YYYY-MM-DDTHH:MM:SS`` (no timezone suffix)."""
    return moment.replace(microsecond=0, tzinfo=None).strftime(DT_FORMAT)


def parse_dt(text: str):
    """Parse an ISO 8601 datetime string, returning ``None`` when impossible."""
    if not isinstance(text, str):
        return None
    value = text.strip()
    if not value:
        return None
    if value.endswith(("Z", "z")):
        value = value[:-1]
    value = value.replace(" ", "T", 1) if " " in value and "T" not in value else value
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        for fmt in (DT_FORMAT, "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed.replace(microsecond=0, tzinfo=None)


def normalize_published(text: str) -> str:
    """Normalize a published value to ``YYYY-MM-DDTHH:MM:SS``.

    Date-only values gain a ``00:00:00`` time component.  Values that cannot be
    parsed are returned unchanged so no information is lost.
    """
    if DATE_ONLY_RE.match(text.strip()):
        return text.strip() + "T00:00:00"
    parsed = parse_dt(text)
    if parsed is None:
        return text
    return format_dt(parsed)


# ---------------------------------------------------------------------------
# history helpers
# ---------------------------------------------------------------------------


def history_sort_key(stamp: str):
    """Sort key placing history keys in chronological order."""
    parsed = parse_dt(stamp)
    if parsed is None:
        return (1, datetime.min, stamp)
    return (0, parsed, stamp)


def latest_stamp(history):
    """Return the newest key of a history object, or ``None`` when empty."""
    if not isinstance(history, dict) or not history:
        return None
    return max(history, key=history_sort_key)


def current_value(history):
    """Current value of a tracked field = value at the latest datetime key."""
    stamp = latest_stamp(history)
    if stamp is None:
        return None, False
    return history[stamp], True


def max_history_moment(catalog):
    """Newest datetime used anywhere in the catalog's tracked histories."""
    newest = None
    for category in CATEGORIES:
        for entry in catalog.get(category) or []:
            if not isinstance(entry, dict):
                continue
            for field in TRACKED_FIELDS:
                history = entry.get(field)
                if not isinstance(history, dict):
                    continue
                for stamp in history:
                    moment = parse_dt(stamp)
                    if moment is not None and (newest is None or moment > newest):
                        newest = moment
    return newest


def sync_timestamp(catalog) -> str:
    """Timestamp for this sync: now, advanced past every recorded second."""
    moment = datetime.now().replace(microsecond=0)
    newest = max_history_moment(catalog)
    if newest is not None and moment <= newest:
        moment = newest + timedelta(seconds=1)
    return format_dt(moment)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_source_entry(entry) -> None:
    """Raise :class:`SourceFetchError` when a source entry is malformed."""
    if not isinstance(entry, dict):
        raise SourceFetchError("source entry is not an object")

    checks = (
        ("id", lambda v: isinstance(v, str), "string"),
        ("published", lambda v: isinstance(v, str), "string"),
        ("width", is_int, "integer"),
        ("height", is_int, "integer"),
        ("title", lambda v: isinstance(v, str), "string"),
        ("description", lambda v: isinstance(v, str), "string"),
        ("views", is_int, "integer"),
        ("likes", lambda v: v is None or is_int(v), "integer or null"),
        ("preview", lambda v: isinstance(v, str), "string"),
    )
    for field, check, expected in checks:
        if field not in entry:
            raise SourceFetchError(
                "source entry is missing required field '{0}'".format(field)
            )
        if not check(entry[field]):
            raise SourceFetchError(
                "source entry field '{0}' must be {1}".format(field, expected)
            )


def validate_source_payload(payload):
    """Validate the decoded source document and return it by category."""
    if not isinstance(payload, dict):
        raise SourceFetchError("source response is not a JSON object")

    by_category = {}
    for category in CATEGORIES:
        if category not in payload:
            raise SourceFetchError(
                "source response is missing '{0}'".format(category)
            )
        entries = payload[category]
        if not isinstance(entries, list):
            raise SourceFetchError(
                "source response field '{0}' is not an array".format(category)
            )
        for entry in entries:
            validate_source_entry(entry)
        by_category[category] = entries
    return by_category


def invalid_vault(name: str, detail: str) -> MVaultError:
    """Build the standard ``invalid vault`` error for a catalog problem."""
    return MVaultError(
        "invalid vault '{0}': {1} {2}".format(name, CATALOG_NAME, detail)
    )


def validate_catalog(catalog, name: str):
    """Raise :class:`MVaultError` when a loaded v3 catalog is not a valid vault."""
    if not isinstance(catalog, dict):
        raise invalid_vault(name, "is not a JSON object")
    if not is_int(catalog.get("version")) or catalog.get("version") != CATALOG_VERSION:
        raise invalid_vault(
            name, "version must be {0}".format(CATALOG_VERSION)
        )
    if not isinstance(catalog.get("source"), str):
        raise invalid_vault(name, "has no source URL")
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise invalid_vault(
                name, "is missing the '{0}' array".format(category)
            )
    return catalog


# ---------------------------------------------------------------------------
# legacy catalogs (version 1 and version 2)
# ---------------------------------------------------------------------------

# Value type expected at every point of a tracked field's history.  Legacy and
# native catalogs share these rules; only the key format differs.
HISTORY_VALUE_CHECKS = (
    ("title", lambda v: isinstance(v, str), "string"),
    ("description", lambda v: isinstance(v, str), "string"),
    ("views", is_int, "integer"),
    ("likes", lambda v: v is None or is_int(v), "integer or null"),
    ("preview", lambda v: isinstance(v, str), "string"),
)

STATIC_FIELD_CHECKS = (
    ("id", lambda v: isinstance(v, str), "string"),
    ("published", lambda v: isinstance(v, str), "string"),
    ("width", is_int, "integer"),
    ("height", is_int, "integer"),
)

EPOCH_KEY_RE = re.compile(r"^[+-]?\d+$")


def derive_v1_source(source_id: str) -> str:
    """Full source URL of a version 1 vault, derived from its ``source_id``."""
    return V1_SOURCE_PREFIX + source_id


def epoch_key_to_iso(stamp: str) -> str:
    """Convert a UNIX-epoch-seconds history key to an ISO 8601 UTC key."""
    moment = datetime.fromtimestamp(int(stamp.strip()), tz=timezone.utc)
    return format_dt(moment)


def entry_label(entry, index: int) -> str:
    identifier = entry.get("id") if isinstance(entry, dict) else None
    if isinstance(identifier, str) and identifier:
        return "entry '{0}'".format(identifier)
    return "entry #{0}".format(index)


def validate_legacy_entry(entry, index: int, name: str, epoch_keys: bool) -> None:
    """Raise :class:`MVaultError` when a v1/v2 entry is malformed."""
    if not isinstance(entry, dict):
        raise invalid_vault(
            name, "{0} is not an object".format(entry_label(entry, index))
        )
    label = entry_label(entry, index)

    for field, check, expected in STATIC_FIELD_CHECKS:
        if field not in entry:
            raise invalid_vault(
                name, "{0} is missing required field '{1}'".format(label, field)
            )
        if not check(entry[field]):
            raise invalid_vault(
                name, "{0} field '{1}' must be {2}".format(label, field, expected)
            )

    for field, check, expected in HISTORY_VALUE_CHECKS:
        if field not in entry:
            raise invalid_vault(
                name, "{0} is missing required field '{1}'".format(label, field)
            )
        history = entry[field]
        if not isinstance(history, dict):
            raise invalid_vault(
                name,
                "{0} field '{1}' must be a history object".format(label, field),
            )
        for stamp, value in history.items():
            if not isinstance(stamp, str) or not stamp.strip():
                raise invalid_vault(
                    name,
                    "{0} field '{1}' has an empty history key".format(label, field),
                )
            if epoch_keys:
                if not EPOCH_KEY_RE.match(stamp.strip()):
                    raise invalid_vault(
                        name,
                        "{0} field '{1}' history key '{2}' is not UNIX epoch "
                        "seconds".format(label, field, stamp),
                    )
            elif parse_dt(stamp) is None:
                raise invalid_vault(
                    name,
                    "{0} field '{1}' history key '{2}' is not an ISO 8601 "
                    "datetime".format(label, field, stamp),
                )
            if not check(value):
                raise invalid_vault(
                    name,
                    "{0} field '{1}' history value at '{2}' must be {3}".format(
                        label, field, stamp, expected
                    ),
                )


def convert_legacy_entry(entry, epoch_keys: bool):
    """Return the v3 shape of a validated v1/v2 entry (without ``removed``)."""
    converted = {field: entry[field] for field, _check, _e in STATIC_FIELD_CHECKS}
    for field, _check, _expected in HISTORY_VALUE_CHECKS:
        history = entry[field]
        if epoch_keys:
            converted[field] = {
                epoch_key_to_iso(stamp): value for stamp, value in history.items()
            }
        else:
            converted[field] = dict(history)
    # Keep any additional fields a legacy catalog happens to carry.
    for key, value in entry.items():
        if key not in converted and key not in ("removed", ANNOTATIONS_FIELD):
            converted[key] = value
    return converted


def legacy_category(raw, category: str, name: str):
    """Read a legacy category array, treating an absent one as empty."""
    entries = raw.get(category)
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise invalid_vault(name, "field '{0}' is not an array".format(category))
    return entries


def finalize_migration(catalog):
    """Stamp every migrated entry with ``removed`` and empty ``annotations``."""
    stamp = sync_timestamp(catalog)
    for category in CATEGORIES:
        for entry in catalog[category]:
            entry["removed"] = {stamp: False}
            entry[ANNOTATIONS_FIELD] = []
    return catalog


def migrate_v1(raw, name: str):
    """Convert a version 1 catalog document into the native v3 shape."""
    source_id = raw.get("source_id")
    if not isinstance(source_id, str) or not source_id:
        raise invalid_vault(name, "has no 'source_id'")

    entries = legacy_category(raw, "entries", name)
    for index, entry in enumerate(entries):
        validate_legacy_entry(entry, index, name, True)

    catalog = {
        "version": CATALOG_VERSION,
        "source": derive_v1_source(source_id),
        # Every version 1 entry lives in a single flat list; they all become
        # episodes, and the remaining categories start out empty.
        "episodes": [convert_legacy_entry(entry, True) for entry in entries],
        "streams": [],
        "clips": [],
    }
    return finalize_migration(catalog)


def migrate_v2(raw, name: str):
    """Convert a version 2 catalog document into the native v3 shape."""
    source = raw.get("source")
    if not isinstance(source, str):
        raise invalid_vault(name, "has no source URL")

    by_category = {}
    for category in CATEGORIES:
        entries = legacy_category(raw, category, name)
        for index, entry in enumerate(entries):
            validate_legacy_entry(entry, index, name, False)
        by_category[category] = entries

    catalog = {"version": CATALOG_VERSION, "source": source}
    for category in CATEGORIES:
        catalog[category] = [
            convert_legacy_entry(entry, False) for entry in by_category[category]
        ]
    for key, value in raw.items():
        if key not in catalog:
            catalog[key] = value
    return finalize_migration(catalog)


def interpret_catalog(raw, name: str):
    """Return ``(catalog, migrated, version)`` for a decoded catalog document.

    The returned catalog is always in the native v3 in-memory shape, whatever
    the on-disk version was.  ``migrated`` tells the caller whether the result
    differs from what is on disk and therefore needs saving.
    """
    if not isinstance(raw, dict):
        raise invalid_vault(name, "is not a JSON object")
    if "version" not in raw:
        raise invalid_vault(name, "has no 'version' field")

    version = raw["version"]
    if not is_int(version):
        raise invalid_vault(name, "version must be an integer")
    if version not in SUPPORTED_VERSIONS:
        raise invalid_vault(
            name,
            "version {0} is not supported (supported versions: {1})".format(
                version, ", ".join(str(v) for v in SUPPORTED_VERSIONS)
            ),
        )

    if version == CATALOG_VERSION:
        return validate_catalog(raw, name), False, version
    if version == 1:
        return migrate_v1(raw, name), True, version
    return migrate_v2(raw, name), True, version


# ---------------------------------------------------------------------------
# catalog i/o
# ---------------------------------------------------------------------------


def catalog_path(name: str) -> str:
    return os.path.join(name, CATALOG_NAME)


def backup_path(name: str) -> str:
    return os.path.join(name, BACKUP_NAME)


def load_vault(name: str):
    """Load a vault of any supported version as ``(catalog, migrated, version)``.

    Reading never touches the vault on disk: a legacy catalog is migrated in
    memory only, and it is up to the caller to persist the result.
    """
    path = catalog_path(name)
    if not os.path.isdir(name):
        raise MVaultError("vault '{0}' does not exist".format(name))
    if not os.path.isfile(path):
        raise invalid_vault(name, "not found")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError) as exc:
        raise MVaultError(
            "invalid vault '{0}': cannot read {1} ({2})".format(name, CATALOG_NAME, exc)
        )
    return interpret_catalog(raw, name)


def load_catalog(name: str):
    """Load a vault for read-only use, transparently upgrading legacy shapes."""
    catalog, _migrated, _version = load_vault(name)
    return catalog


def dump_catalog(catalog) -> str:
    ordered = {
        "version": CATALOG_VERSION,
        "source": catalog.get("source", ""),
    }
    for category in CATEGORIES:
        ordered[category] = [order_entry(e) for e in catalog.get(category, [])]
    for key, value in catalog.items():
        if key not in ordered:
            ordered[key] = value
    return json.dumps(ordered, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def order_entry(entry):
    """Render an entry with a stable, readable key order."""
    if not isinstance(entry, dict):
        return entry
    ordered = {}
    for field in STATIC_FIELDS:
        if field in entry:
            ordered[field] = entry[field]
    for field in TRACKED_FIELDS:
        if field in entry:
            ordered[field] = order_history(entry[field])
    if ANNOTATIONS_FIELD in entry:
        ordered[ANNOTATIONS_FIELD] = entry[ANNOTATIONS_FIELD]
    for key, value in entry.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def order_history(history):
    if not isinstance(history, dict):
        return history
    return {stamp: history[stamp] for stamp in sorted(history, key=history_sort_key)}


def write_catalog(name: str, catalog) -> None:
    """Write the catalog, backing up any pre-existing catalog byte-for-byte.

    The backup is written first, so a failure there aborts the write and leaves
    the original ``catalog.json`` untouched.
    """
    path = catalog_path(name)
    if os.path.isfile(path):
        try:
            with open(path, "rb") as handle:
                previous = handle.read()
            with open(backup_path(name), "wb") as handle:
                handle.write(previous)
        except OSError as exc:
            raise MVaultError(
                "cannot write {0} for vault '{1}': {2}".format(
                    BACKUP_NAME, name, exc
                )
            )
    payload = dump_catalog(catalog)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload)
    except OSError as exc:
        raise MVaultError(
            "cannot write {0} for vault '{1}': {2}".format(CATALOG_NAME, name, exc)
        )


def entry_sort_key(entry):
    """Newest ``published`` first, ties broken by lexicographically smaller id."""
    published = entry.get("published")
    published = published if isinstance(published, str) else ""
    identifier = entry.get("id")
    identifier = identifier if isinstance(identifier, str) else ""
    parsed = parse_dt(published)
    # Sorting is done with reverse=False, so invert the datetime ordering by
    # using its negated timestamp; ids keep their natural ascending order.
    if parsed is None:
        rank = (1, 0.0, published)
    else:
        rank = (0, -parsed.timestamp(), "")
    return (rank, identifier)


def sort_entries(entries):
    return sorted(entries, key=entry_sort_key)


# ---------------------------------------------------------------------------
# source fetching
# ---------------------------------------------------------------------------


def fetch_source(url: str):
    try:
        with urllib.request.urlopen(url) as response:
            raw = response.read()
    except MVaultError:
        raise
    except Exception as exc:  # network, protocol, url errors ...
        raise SourceFetchError(str(exc) or exc.__class__.__name__)

    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceFetchError(str(exc))
    else:
        text = raw

    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise SourceFetchError(str(exc))
    return validate_source_payload(payload)


# ---------------------------------------------------------------------------
# sync logic
# ---------------------------------------------------------------------------


def record(entry, field, value, stamp) -> bool:
    """Append ``value`` to a tracked field's history when it changed."""
    history = entry.get(field)
    if not isinstance(history, dict):
        history = {}
        entry[field] = history
    existing, has_value = current_value(history)
    if has_value and existing == value and type(existing) is type(value):
        return False
    history[stamp] = value
    return True


def make_entry(source_entry, stamp):
    entry = {
        "id": source_entry["id"],
        "published": normalize_published(source_entry["published"]),
        "width": source_entry["width"],
        "height": source_entry["height"],
    }
    for field in SOURCE_TRACKED_FIELDS:
        entry[field] = {stamp: source_entry[field]}
    entry["removed"] = {stamp: False}
    entry[ANNOTATIONS_FIELD] = []
    return entry


def update_entry(entry, source_entry, stamp):
    """Refresh an existing entry, returning the tracked fields that changed."""
    entry["published"] = normalize_published(source_entry["published"])
    entry["width"] = source_entry["width"]
    entry["height"] = source_entry["height"]
    changed = []
    for field in SOURCE_TRACKED_FIELDS:
        if record(entry, field, source_entry[field], stamp):
            changed.append(field)
    # A previously removed entry that shows up again is a change too.
    if record(entry, "removed", False, stamp):
        changed.append("removed")
    return changed


def sync_catalog(catalog, source_by_category, stamp):
    """Apply source metadata to the catalog.

    Returns ``(counts, changes)``.  ``changes`` maps a category to
    ``{entry id: (group, changed labels)}`` so the post-sync summary can list
    every touched entry with a viewer link.
    """
    counts = {"added": 0, "removed": 0, "updated": 0}
    changes = {category: {} for category in CATEGORIES}
    for category in CATEGORIES:
        recorded = changes[category]
        entries = [e for e in catalog.get(category, []) if isinstance(e, dict)]
        by_id = {}
        for entry in entries:
            identifier = entry.get("id")
            if isinstance(identifier, str) and identifier not in by_id:
                by_id[identifier] = entry

        seen = set()
        for source_entry in source_by_category[category]:
            identifier = source_entry["id"]
            seen.add(identifier)
            existing = by_id.get(identifier)
            if existing is None:
                new_entry = make_entry(source_entry, stamp)
                entries.append(new_entry)
                by_id[identifier] = new_entry
                counts["added"] += 1
                recorded[identifier] = (ADDED_GROUP, [])
            else:
                changed = update_entry(existing, source_entry, stamp)
                if changed:
                    counts["updated"] += 1
                    recorded[identifier] = (UPDATED_GROUP, change_labels(changed))

        for entry in entries:
            if entry.get("id") not in seen:
                if record(entry, "removed", True, stamp):
                    counts["removed"] += 1
                    identifier = entry.get("id")
                    if isinstance(identifier, str):
                        recorded[identifier] = (REMOVED_GROUP, [])

        catalog[category] = sort_entries(entries)
    return counts, changes


def change_labels(changed):
    """Field names as reported to a human; ``removed`` means it came back."""
    return [REAPPEARED_LABEL if f == "removed" else f for f in changed]


def build_sync_sections(catalog, changes, name, host=None, port=None):
    """Post-sync change sections, in catalog order, with viewer links.

    ``sync`` always leaves a native-version catalog behind, so the category an
    entry lives in is also the category its viewer link points at.  A migrated
    version 1 vault therefore reports its entries under ``episodes``.
    """
    sections = []
    for category in CATEGORIES:
        recorded = changes.get(category) or {}
        if not recorded:
            continue
        grouped = {group: [] for group in DIGEST_GROUPS}
        for entry in catalog.get(category) or []:
            if not isinstance(entry, dict):
                continue
            identifier = entry.get("id")
            found = recorded.get(identifier)
            if found is None:
                continue
            group, labels = found
            grouped[group].append(
                change_line(
                    digest_title(entry, False),
                    labels,
                    name,
                    category,
                    identifier,
                    host,
                    port,
                )
            )
        if any(grouped[group] for group in DIGEST_GROUPS):
            sections.append((CATEGORY_LABELS[category], grouped))
    return sections


# ---------------------------------------------------------------------------
# download phase
# ---------------------------------------------------------------------------


class DownloadError(Exception):
    """A single asset could not be retrieved."""

    def __init__(self, detail: str, permanent: bool) -> None:
        super().__init__(detail)
        self.detail = detail
        self.permanent = permanent


def warn(message: str) -> None:
    sys.stderr.write("mvault: warning: {0}\n".format(message))


def url_join(base: str, *parts) -> str:
    """Join a source URL with path segments, tolerating trailing slashes."""
    url = (base or "").rstrip("/")
    for part in parts:
        url = "{0}/{1}".format(url, str(part).lstrip("/"))
    return url


def is_partial_artifact(filename: str) -> bool:
    lowered = filename.lower()
    return any(lowered.endswith(suffix) for suffix in PARTIAL_SUFFIXES)


def stored_names(directory: str):
    """Names of finished (non-partial) files already stored in a directory."""
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    return [
        name
        for name in names
        if not is_partial_artifact(name)
        and os.path.isfile(os.path.join(directory, name))
    ]


def has_asset(names, identifier: str) -> bool:
    """An entry is served by any finished file whose name contains its id."""
    return any(identifier in name for name in names)


def normalize_format(fmt):
    """Normalize a ``--format`` override to a bare extension string."""
    if fmt is None:
        return None
    value = str(fmt).strip().lstrip(".")
    return value or None


def extension_for(content_type, override=None) -> str:
    """Pick the stored file extension for a downloaded asset."""
    if override:
        return "." + override
    if not content_type:
        return DEFAULT_EXTENSION
    base = str(content_type).split(";")[0].strip().lower()
    if not base:
        return DEFAULT_EXTENSION
    if base in CONTENT_TYPE_EXTENSIONS:
        return CONTENT_TYPE_EXTENSIONS[base]
    guessed = mimetypes.guess_extension(base)
    if guessed:
        # ``guess_extension`` prefers some rarely used spellings.
        return {".jpe": ".jpg", ".htm": ".html"}.get(guessed, guessed)
    return DEFAULT_EXTENSION


def http_download(url: str, attempts: int = DOWNLOAD_ATTEMPTS):
    """Fetch a URL, retrying transient failures; returns ``(data, content_type)``."""
    detail = "unknown error"
    for attempt in range(1, max(1, attempts) + 1):
        try:
            with urllib.request.urlopen(url) as response:
                data = response.read()
                headers = getattr(response, "headers", None)
                content_type = headers.get("Content-Type") if headers else None
            return data, content_type
        except urllib.error.HTTPError as exc:
            detail = "HTTP {0}".format(exc.code)
            reason = getattr(exc, "reason", None)
            if reason:
                detail = "{0} {1}".format(detail, reason)
            if exc.code not in TRANSIENT_STATUS and exc.code < 500:
                raise DownloadError(detail, permanent=True)
        except Exception as exc:  # network / protocol / timeout failures
            detail = str(exc) or exc.__class__.__name__
        if attempt < max(1, attempts) and RETRY_DELAY_SECONDS:
            time.sleep(RETRY_DELAY_SECONDS)
    raise DownloadError(detail, permanent=False)


def store_asset(directory: str, identifier: str, extension: str, data) -> str:
    """Write data through a partial file, then atomically put it in place."""
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        raise DownloadError("cannot create {0} ({1})".format(directory, exc), True)

    final_path = os.path.join(directory, identifier + extension)
    partial_path = final_path + PARTIAL_SUFFIX
    try:
        with open(partial_path, "wb") as handle:
            handle.write(data)
        os.replace(partial_path, final_path)
    except OSError as exc:
        try:
            os.remove(partial_path)
        except OSError:
            pass
        raise DownloadError("cannot write {0} ({1})".format(final_path, exc), True)
    return final_path


def download_asset(url, directory, identifier, label, override=None):
    """Download one asset, warning on failure.  Returns the path or ``None``."""
    try:
        data, content_type = http_download(url)
    except DownloadError as exc:
        kind = "unavailable" if exc.permanent else "failed after retries"
        warn(
            "{0} for entry '{1}' {2}: {3} ({4})".format(
                label, identifier, kind, exc.detail, url
            )
        )
        return None
    try:
        return store_asset(
            directory, identifier, extension_for(content_type, override), data
        )
    except DownloadError as exc:
        warn("{0} for entry '{1}' failed: {2}".format(label, identifier, exc.detail))
        return None


def download_candidates(catalog, category, media_names, limit):
    """Entries of a category still missing media, in catalog order."""
    candidates = []
    for entry in catalog.get(category) or []:
        if limit is not None and len(candidates) >= limit:
            break
        if not isinstance(entry, dict):
            continue
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not identifier:
            continue
        if has_asset(media_names, identifier):
            continue
        candidates.append(entry)
    return candidates


def download_phase(name: str, catalog, limits=None, fmt=None):
    """Retrieve media and preview files for entries missing their media."""
    limits = limits or {}
    override = normalize_format(fmt)
    source = catalog.get("source")
    source = source if isinstance(source, str) else ""

    media_dir = os.path.join(name, MEDIA_DIRNAME)
    preview_dir = os.path.join(name, PREVIEW_DIRNAME)
    media_names = stored_names(media_dir)
    preview_names = stored_names(preview_dir)

    stats = {"media": 0, "previews": 0, "failed": 0}
    for category in CATEGORIES:
        limit = limits.get(category)
        for entry in download_candidates(catalog, category, media_names, limit):
            identifier = entry["id"]

            remote = url_join(source, MEDIA_REMOTE_SEGMENT, identifier)
            if override:
                remote = "{0}.{1}".format(remote, override)
            stored = download_asset(remote, media_dir, identifier, "media", override)
            if stored is None:
                stats["failed"] += 1
            else:
                stats["media"] += 1
                media_names.append(os.path.basename(stored))

            if has_asset(preview_names, identifier):
                continue
            preview_url = url_join(source, PREVIEW_REMOTE_SEGMENT, identifier)
            stored = download_asset(
                preview_url, preview_dir, identifier, "preview"
            )
            if stored is None:
                stats["failed"] += 1
            else:
                stats["previews"] += 1
                preview_names.append(os.path.basename(stored))
    return stats


# ---------------------------------------------------------------------------
# digest
# ---------------------------------------------------------------------------

# Digest reads a catalog exactly as it is stored: v1 and v2 vaults are
# summarised in place, never migrated, so the command never writes anything.

REMOVED_GROUP = "Removed"
ADDED_GROUP = "Added"
UPDATED_GROUP = "Updated"
# Listed in precedence order; an entry is reported in the first group it fits.
DIGEST_GROUPS = (REMOVED_GROUP, ADDED_GROUP, UPDATED_GROUP)

REAPPEARED_LABEL = "reappeared"
NO_CHANGES_TEXT = "No notable changes found."


def epoch_sort_key(stamp):
    """Order UNIX-epoch history keys numerically, as version 1 requires."""
    text = str(stamp).strip()
    try:
        return (0, int(text), text)
    except (TypeError, ValueError):
        return (1, 0, text)


def digest_history_keys(history, numeric: bool):
    """History keys oldest-first using the version's comparison rule."""
    if not isinstance(history, dict) or not history:
        return []
    if numeric:
        return sorted(history, key=epoch_sort_key)
    # v2 and v3 keys are ISO 8601 strings, compared lexicographically.
    return sorted(history, key=str)


def digest_latest(entry, field, numeric):
    """``(value, found)`` for the newest value of a tracked field."""
    history = entry.get(field)
    keys = digest_history_keys(history, numeric)
    if not keys:
        return None, False
    return history[keys[-1]], True


def digest_title(entry, numeric) -> str:
    value, found = digest_latest(entry, "title", numeric)
    if found:
        if isinstance(value, str) and value.strip():
            return value
        if value is not None:
            return str(value)
    identifier = entry.get("id")
    if isinstance(identifier, str) and identifier:
        return identifier
    return "(untitled)"


def classify_entry(entry, tracked, numeric, removals):
    """Classify an entry as removed / added / updated, or ``None``.

    Returns ``(group, changed_labels)``; ``changed_labels`` is only meaningful
    for the field-update group.
    """
    keys_by_field = {}
    for field in tracked:
        keys_by_field[field] = digest_history_keys(entry.get(field), numeric)

    if removals:
        removed_keys = keys_by_field.get("removed") or []
        if removed_keys:
            history = entry["removed"]
            latest = history[removed_keys[-1]]
            prior = history[removed_keys[-2]] if len(removed_keys) > 1 else None
            if latest is True and (len(removed_keys) < 2 or prior is False):
                return REMOVED_GROUP, []

    observed = [field for field, keys in keys_by_field.items() if keys]
    if observed and all(len(keys) < 2 for keys in keys_by_field.values()):
        return ADDED_GROUP, []

    changed = []
    for field in tracked:
        keys = keys_by_field[field]
        if len(keys) < 2:
            continue
        history = entry[field]
        if history[keys[-1]] == history[keys[-2]]:
            continue
        if field == "removed":
            # false again after a removal: the entry is back.
            if history[keys[-1]] is False:
                changed.append(REAPPEARED_LABEL)
            continue
        changed.append(field)

    if changed:
        return UPDATED_GROUP, changed
    return None


def as_entry_list(value):
    return value if isinstance(value, list) else []


def read_catalog_document(name: str):
    """Read ``catalog.json`` verbatim, without migrating or validating it."""
    path = catalog_path(name)
    if not os.path.isdir(name):
        raise MVaultError("vault '{0}' does not exist".format(name))
    if not os.path.isfile(path):
        raise invalid_vault(name, "not found")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise MVaultError(
            "invalid vault '{0}': cannot read {1} ({2})".format(
                name, CATALOG_NAME, exc
            )
        )


def digest_plan(raw, name: str):
    """Describe how to read a stored catalog of any supported version."""
    if not isinstance(raw, dict):
        raise invalid_vault(name, "is not a JSON object")
    if "version" not in raw:
        raise invalid_vault(name, "has no 'version' field")

    version = raw["version"]
    if not is_int(version) or version not in SUPPORTED_VERSIONS:
        raise MVaultError(
            "invalid vault '{0}': catalog version {1} is not supported "
            "(supported versions: {2})".format(
                name,
                json.dumps(version) if isinstance(version, str) else version,
                ", ".join(str(v) for v in SUPPORTED_VERSIONS),
            )
        )

    if version == 1:
        source_id = raw.get("source_id")
        source = derive_v1_source(source_id if isinstance(source_id, str) else "")
        categories = [
            (V1_CATEGORY, V1_CATEGORY_LABEL, as_entry_list(raw.get("entries")))
        ]
        return {
            "version": version,
            "source": source,
            "categories": categories,
            "tracked": SOURCE_TRACKED_FIELDS,
            "numeric": True,
            "removals": False,
        }

    source = raw.get("source")
    categories = [
        (category, CATEGORY_LABELS[category], as_entry_list(raw.get(category)))
        for category in CATEGORIES
    ]
    return {
        "version": version,
        "source": source if isinstance(source, str) else "",
        "categories": categories,
        "tracked": TRACKED_FIELDS if version == CATALOG_VERSION
        else SOURCE_TRACKED_FIELDS,
        "numeric": False,
        "removals": version == CATALOG_VERSION,
    }


def change_line(title, changed, name, category, identifier, host=None, port=None):
    """One reported entry: title, the fields that changed, and a viewer link."""
    text = title
    if changed:
        text = "{0} ({1})".format(text, ", ".join(changed))
    if isinstance(identifier, str) and identifier:
        text = "{0} {1}".format(
            text, viewer_link(name, category, identifier, host, port)
        )
    return text


def build_digest(plan, name, host=None, port=None):
    """Group notable changes by category and change type, in catalog order."""
    sections = []
    totals = {group: 0 for group in DIGEST_GROUPS}
    for route, label, entries in plan["categories"]:
        grouped = {group: [] for group in DIGEST_GROUPS}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            result = classify_entry(
                entry, plan["tracked"], plan["numeric"], plan["removals"]
            )
            if result is None:
                continue
            group, changed = result
            text = change_line(
                digest_title(entry, plan["numeric"]),
                changed,
                name,
                route,
                entry.get("id"),
                host,
                port,
            )
            grouped[group].append(text)
            totals[group] += 1
        if any(grouped[group] for group in DIGEST_GROUPS):
            sections.append((label, grouped))
    return sections, totals


def render_change_sections(sections):
    """Render grouped change sections; entry lines carry their viewer link."""
    lines = []
    for label, grouped in sections:
        lines.append("{0}:".format(label))
        for group in DIGEST_GROUPS:
            items = grouped[group]
            if not items:
                continue
            lines.append("  {0}:".format(group))
            for text in items:
                lines.append("    - {0}".format(text))
    return lines


def render_digest(name: str, plan, sections, totals):
    lines = ["Digest for vault '{0}' (catalog version {1})".format(
        name, plan["version"]
    ), ""]

    if not sections:
        lines.append(NO_CHANGES_TEXT)
    else:
        for index, section in enumerate(sections):
            if index:
                lines.append("")
            lines.extend(render_change_sections([section]))

    lines.append("")
    lines.append(
        "Digest generated at {0}: {1} added, {2} removed, {3} updated, "
        "source {4}".format(
            format_dt(datetime.now()),
            totals[ADDED_GROUP],
            totals[REMOVED_GROUP],
            totals[UPDATED_GROUP],
            plan["source"],
        )
    )
    return lines


# ---------------------------------------------------------------------------
# viewer: links
# ---------------------------------------------------------------------------

# The viewer reads a vault exactly as it is stored.  A v1 or v2 vault is never
# migrated on the way to the browser, so the stored version alone decides the
# valid categories, the default category and the history-key comparison rule.


def categories_for_version(version):
    """Categories a catalog of this version can be browsed by."""
    return V1_CATEGORIES if version == 1 else CATEGORIES


def default_category_for_version(version) -> str:
    """Category a bare ``/catalog/<name>`` request redirects to."""
    return V1_CATEGORY if version == 1 else DEFAULT_CATEGORY


def viewer_host_port(host=None, port=None):
    return (
        host if host else DEFAULT_VIEWER_HOST,
        DEFAULT_VIEWER_PORT if port is None or port == "" else port,
    )


def viewer_origin(host=None, port=None) -> str:
    resolved_host, resolved_port = viewer_host_port(host, port)
    return "{0}://{1}:{2}".format(
        DEFAULT_VIEWER_SCHEME, resolved_host, resolved_port
    )


def url_segment(text) -> str:
    return quote(str(text), safe="")


def catalog_url_path(name, category=None, identifier=None) -> str:
    """Viewer path for a vault, one of its categories, or a single entry."""
    path = "/catalog/" + url_segment(name)
    if category is not None:
        path = "{0}/{1}".format(path, url_segment(category))
    if identifier is not None:
        path = "{0}/{1}".format(path, url_segment(identifier))
    return path


def viewer_link(name, category, identifier, host=None, port=None) -> str:
    """Absolute viewer URL for one entry, as printed in change reports."""
    return viewer_origin(host, port) + catalog_url_path(name, category, identifier)


def vault_asset_path(name, segment, tail) -> str:
    """Viewer path of a stored asset: ``/vault/<name>/<segment>/<tail>``."""
    return "/{0}/{1}/{2}/{3}".format(
        VAULT_ROUTE, url_segment(name), segment, url_segment(tail)
    )


def media_asset_path(name, filename) -> str:
    """Static endpoint serving one stored media file by its saved name."""
    return vault_asset_path(name, MEDIA_ROUTE_SEGMENT, filename)


def preview_asset_path(name, identifier) -> str:
    """Static endpoint serving the preview image stored for an entry id."""
    return vault_asset_path(name, PREVIEW_ROUTE_SEGMENT, identifier)


def entry_source_link(source, identifier) -> str:
    """Source-platform URL of an entry: ``<source>/entry/<id>``.

    ``source`` is the vault's source URL as the viewer resolved it, which for a
    version 1 vault is derived from its ``source_id``; the result is therefore
    version aware without the caller having to know the version.
    """
    return url_join(source, "entry", identifier if identifier is not None else "")


# ---------------------------------------------------------------------------
# viewer: reading a vault for display
# ---------------------------------------------------------------------------


def safe_vault_name(name) -> bool:
    """Reject anything that is not a plain directory name in the vault root."""
    if not isinstance(name, str) or not name.strip():
        return False
    if name in (os.curdir, os.pardir) or "\x00" in name:
        return False
    if "/" in name or "\\" in name or os.path.isabs(name):
        return False
    return True


def safe_asset_name(filename) -> bool:
    """Reject any served file name that is not a plain name in the asset dir.

    A request may spell traversal in any number of ways - encoded separators,
    ``..`` segments, an absolute path - and every one of them is refused here
    before a path is ever built.
    """
    if not isinstance(filename, str) or not filename.strip():
        return False
    if "\x00" in filename:
        return False
    if "/" in filename or "\\" in filename or os.path.isabs(filename):
        return False
    if filename in (os.curdir, os.pardir):
        return False
    return os.path.basename(filename) == filename


def within_directory(directory, path) -> bool:
    """Last line of defence: the resolved path must stay inside the directory."""
    try:
        base = os.path.realpath(directory)
        target = os.path.realpath(path)
    except (OSError, ValueError):
        return False
    return target == base or target.startswith(base + os.sep)


def asset_mime(filename, image_only: bool) -> str:
    """MIME type served for a stored asset, guessed from its saved name."""
    guessed, _encoding = mimetypes.guess_type(filename)
    if image_only:
        return guessed if guessed and guessed.startswith("image/") else (
            DEFAULT_PREVIEW_MIME
        )
    if guessed and guessed.split("/")[0] in ("video", "audio", "image"):
        return guessed
    return guessed or DEFAULT_ASSET_MIME


def stored_asset_names(directory, dirname):
    """Every stored file name in one of a vault's asset directories."""
    asset_dir = os.path.join(directory, dirname)
    try:
        names = os.listdir(asset_dir)
    except OSError:
        return []
    return sorted(
        name for name in names if os.path.isfile(os.path.join(asset_dir, name))
    )


def viewer_media_names(directory):
    """Every stored file name in ``<vault>/media``."""
    return stored_asset_names(directory, MEDIA_DIRNAME)


def viewer_preview_names(directory):
    """Every stored file name in ``<vault>/previews``."""
    return stored_asset_names(directory, PREVIEW_DIRNAME)


def matching_asset(names, identifier):
    """The saved file name serving an entry id, or ``None``.

    A stored asset belongs to an entry when its saved name contains the entry
    id.  Several names can match; the choice is deterministic, preferring a
    finished file over an interrupted download's leftover artifact.
    """
    if not isinstance(identifier, str) or not identifier:
        return None
    matches = sorted(name for name in names if identifier in name)
    if not matches:
        return None
    finished = [name for name in matches if not is_partial_artifact(name)]
    return (finished or matches)[0]


def entry_is_downloaded(media_names, identifier) -> bool:
    """An entry is downloaded when a media file name contains its id."""
    if not isinstance(identifier, str) or not identifier:
        return False
    return any(identifier in filename for filename in media_names)


def entry_is_removed(entry, removals) -> bool:
    """Latest ``removed`` value of a v3 entry; v1/v2 have no such field."""
    if not removals:
        return False
    history = entry.get("removed")
    keys = digest_history_keys(history, False)
    if not keys:
        return False
    return history[keys[-1]] is True


def load_vault_view(base_dir, name):
    """Read a vault of any supported version for display.

    Nothing is migrated and nothing is written: the on-disk version decides how
    history keys compare and which categories exist.
    """
    if not safe_vault_name(name):
        raise MVaultError("vault '{0}' does not exist".format(name))
    directory = os.path.join(base_dir, name) if base_dir else name
    raw = read_catalog_document(directory)
    if not isinstance(raw, dict):
        raise invalid_vault(name, "is not a JSON object")

    version = raw.get("version")
    if not is_int(version) or version not in SUPPORTED_VERSIONS:
        raise invalid_vault(
            name,
            "version {0} is not supported".format(json.dumps(version)),
        )

    categories = [
        (route, CATEGORY_LABELS.get(route, V1_CATEGORY_LABEL),
         as_entry_list(raw.get(route)))
        for route in categories_for_version(version)
    ]
    return {
        "name": name,
        "directory": directory,
        "version": version,
        "numeric": version == 1,
        "removals": version == CATALOG_VERSION,
        "source": view_source(raw, version),
        "categories": categories,
        "default_category": default_category_for_version(version),
        "media": viewer_media_names(directory),
        "previews": viewer_preview_names(directory),
    }


def view_source(raw, version) -> str:
    """Source URL of a stored catalog, derived for version 1 vaults."""
    if version == 1:
        source_id = raw.get("source_id")
        return derive_v1_source(source_id if isinstance(source_id, str) else "")
    source = raw.get("source")
    return source if isinstance(source, str) else ""


def find_entry(entries, identifier):
    """The entry of a category array with this id, or ``None``.

    The search never leaves the category it was given, so the same id in
    another category can not satisfy it, and a removed entry still matches.
    """
    if not isinstance(identifier, str) or not identifier:
        return None
    for entry in entries:
        if isinstance(entry, dict) and entry.get("id") == identifier:
            return entry
    return None


def resolved_default_path(base_dir, name) -> str:
    """Path ``/catalog/<name>`` resolves to, or the bare route when unreadable."""
    try:
        view = load_vault_view(base_dir, name)
    except MVaultError:
        return catalog_url_path(name)
    return catalog_url_path(name, view["default_category"])


# ---------------------------------------------------------------------------
# viewer: chart data
# ---------------------------------------------------------------------------

# Charts read a vault exactly as it is stored, so the raw history keys differ
# per version: version 1 keys are UNIX-epoch seconds ordered numerically, while
# version 2 and 3 keys are ISO 8601 strings ordered lexicographically.  Whatever
# the stored format, a chart point always carries an ISO 8601 timestamp, so the
# embedded data looks the same for every version.


def chart_timestamp(stamp, numeric) -> str:
    """Normalize one history key to an ISO 8601 chart timestamp."""
    text = stamp if isinstance(stamp, str) else str(stamp)
    if not numeric:
        return text  # v2/v3 keys are already ISO 8601
    try:
        return epoch_key_to_iso(text)
    except (TypeError, ValueError, OverflowError, OSError):
        return text  # not epoch seconds after all; report it unchanged


def chart_points(entry, field, numeric):
    """Chart points for one tracked field, oldest first.

    Every recorded point is kept exactly as stored - nothing is filtered,
    deduplicated or substituted, so a ``null`` in a ``likes`` history stays a
    ``null`` point paired with its own timestamp.
    """
    history = entry.get(field)
    keys = digest_history_keys(history, numeric)
    return [
        {"timestamp": chart_timestamp(stamp, numeric), "value": history[stamp]}
        for stamp in keys
    ]


def entry_chart_data(entry, numeric):
    """The ``views``/``likes`` series embedded in an entry detail page."""
    return {field: chart_points(entry, field, numeric) for field in CHART_FIELDS}


def chart_json(payload) -> str:
    """Serialize chart data for embedding inside an HTML script element."""
    text = json.dumps(payload, ensure_ascii=False)
    # Escaping these three keeps the payload valid JSON while making it
    # impossible for entry text to close the script element early.
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


# ---------------------------------------------------------------------------
# viewer: html
# ---------------------------------------------------------------------------

VIEWER_STYLE = """
:root { color-scheme: light dark; }
body { font: 15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif;
       margin: 0 auto; max-width: 54rem; padding: 2rem 1rem 4rem; }
h1 { margin-bottom: .2rem; }
.meta { color: #6b7280; margin-top: 0; }
.notice { border-left: 4px solid #b91c1c; background: #fee2e2; color: #7f1d1d;
          padding: .6rem .8rem; border-radius: 4px; }
.notice.missing-entry { border-color: #b45309; background: #fef3c7;
                        color: #78350f; }
form.open-vault { display: flex; gap: .5rem; align-items: center;
                  flex-wrap: wrap; margin: 1rem 0 2rem; }
form.open-vault input { padding: .4rem .6rem; min-width: 16rem; }
form.open-vault button { padding: .4rem .9rem; }
nav.categories { display: flex; gap: .75rem; margin: .5rem 0 1.5rem; }
nav.categories a.current { font-weight: 700; text-decoration: none;
                           border-bottom: 2px solid currentColor; }
ul.recent { padding-left: 1.2rem; }
ol.entries { list-style: decimal; padding-left: 2rem; }
li.entry { margin: .35rem 0; padding: .25rem .4rem; border-radius: 4px; }
li.entry a.title { font-weight: 600; }
li.entry span.id { color: #6b7280; font-family: ui-monospace, monospace;
                   font-size: .85em; }
li.entry.undownloaded { opacity: .62; }
li.entry.undownloaded a.title { font-weight: 400; }
li.entry.removed a.title { text-decoration: line-through; }
li.entry.selected { background: #fef08a; outline: 2px solid #ca8a04; }
span.badge { display: inline-block; font-size: .75em; text-transform: uppercase;
             letter-spacing: .04em; padding: .1rem .4rem; border-radius: 999px;
             border: 1px solid currentColor; margin-left: .3rem; }
span.badge.downloaded { color: #15803d; }
span.badge.undownloaded { color: #6b7280; }
span.badge.removed { color: #b91c1c; }
p.back { margin: 0 0 .6rem; }
dl.entry-meta { display: grid; grid-template-columns: max-content 1fr;
                gap: .35rem 1.2rem; margin: 1rem 0 1.5rem; }
dl.entry-meta dt { color: #6b7280; }
dl.entry-meta dd { margin: 0; overflow-wrap: anywhere; }
p.description { white-space: pre-wrap; }
figure.media, figure.preview { margin: 1.5rem 0; }
figure.media video, figure.media audio, figure.preview img {
  width: 100%; max-width: 40rem; border-radius: 6px; }
figure.media figcaption, figure.preview figcaption { color: #6b7280;
  font-size: .85em; margin-top: .35rem; }
p.media.missing { color: #6b7280; }
/* charts: one measure per chart, single series, palette slots 1 and 2 */
.viz-root { color-scheme: light; --surface-1: #fcfcfb; --text-secondary: #52514e;
            --grid: #e6e5e1; --series-views: #2a78d6; --series-likes: #eb6834; }
@media (prefers-color-scheme: dark) {
  .viz-root { color-scheme: dark; --surface-1: #1a1a19;
              --text-secondary: #c3c2b7; --grid: #3a3a37;
              --series-views: #3987e5; --series-likes: #d95926; }
}
figure.chart { margin: 0 0 1.75rem; }
figure.chart figcaption { font-weight: 600; margin-bottom: .4rem; }
figure.chart svg { width: 100%; height: auto; background: var(--surface-1);
                   border-radius: 6px; }
figure.chart[data-field="views"] svg { --series: var(--series-views); }
figure.chart[data-field="likes"] svg { --series: var(--series-likes); }
.chart-grid line { stroke: var(--grid); stroke-width: 1; }
.chart-axis text { fill: var(--text-secondary); font-size: 11px; }
.chart-series { fill: none; stroke: var(--series); stroke-width: 2;
                stroke-linecap: round; stroke-linejoin: round; }
.chart-marker { fill: var(--series); stroke: var(--surface-1); stroke-width: 2; }
.chart-end-label { fill: var(--text-secondary); font-size: 12px;
                   font-weight: 600; }
details.chart-data { margin-top: .4rem; }
details.chart-data summary { color: #6b7280; cursor: pointer; font-size: .9em; }
table.chart-table { border-collapse: collapse; font-size: .9em;
                    margin: .5rem 0 0; }
table.chart-table th, table.chart-table td { text-align: left;
  padding: .15rem 1.2rem .15rem 0; border-bottom: 1px solid #d1d5db; }
"""


def esc(text) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def viewer_page(title, body) -> str:
    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>{0}</title>\n<style>{1}</style>\n</head>\n<body>\n{2}\n"
        "</body>\n</html>\n"
    ).format(esc(title), VIEWER_STYLE, body)


def render_landing(recent, missing=None) -> str:
    """Landing page: the vault-name form plus recently visited vaults."""
    parts = ["<h1>mvault viewer</h1>"]
    if missing:
        parts.append(
            "<p class=\"notice missing\" role=\"alert\">Vault &#39;{0}&#39; not "
            "found.</p>".format(esc(missing))
        )
    parts.append(
        "<form class=\"open-vault\" method=\"post\" action=\"/\">\n"
        "<label for=\"catalog\">Vault name</label>\n"
        "<input type=\"text\" id=\"catalog\" name=\"catalog\" value=\"\" "
        "placeholder=\"vault name\" autocomplete=\"off\" autofocus>\n"
        "<button type=\"submit\">Open vault</button>\n"
        "</form>"
    )
    parts.append("<h2>Recent vaults</h2>")
    if recent:
        items = "\n".join(
            "<li class=\"recent-vault\"><a href=\"{0}\">{1}</a></li>".format(
                esc(href), esc(vault_name)
            )
            for vault_name, href in recent
        )
        parts.append("<ul class=\"recent\">\n{0}\n</ul>".format(items))
    else:
        parts.append("<p class=\"recent empty\">No vaults visited yet.</p>")
    return viewer_page("mvault viewer", "\n".join(parts))


def render_entry(view, category, entry, selected) -> str:
    if not isinstance(entry, dict):
        return "<li class=\"entry invalid\">(invalid entry)</li>"

    identifier = entry.get("id")
    identifier = identifier if isinstance(identifier, str) else ""
    title = digest_title(entry, view["numeric"])
    downloaded = entry_is_downloaded(view["media"], identifier)
    removed = entry_is_removed(entry, view["removals"])

    classes = ["entry", "downloaded" if downloaded else "undownloaded"]
    if removed:
        classes.append("removed")
    is_selected = bool(identifier) and identifier == selected
    if is_selected:
        classes.append("selected")

    badges = [
        "<span class=\"badge {0}\">{1}</span>".format(
            "downloaded" if downloaded else "undownloaded",
            "Downloaded" if downloaded else "Not downloaded",
        )
    ]
    if removed:
        badges.append("<span class=\"badge removed\">Removed</span>")

    return (
        "<li class=\"{classes}\" id=\"entry-{ident}\" data-id=\"{ident}\""
        "{current}>"
        "<a class=\"title\" href=\"{href}\">{title}</a> "
        "<span class=\"id\">{ident}</span> {badges}</li>"
    ).format(
        classes=" ".join(classes),
        ident=esc(identifier),
        current=" aria-current=\"true\"" if is_selected else "",
        href=esc(catalog_url_path(view["name"], category, identifier)),
        title=esc(title),
        badges=" ".join(badges),
    )


def render_listing(view, category, entries, selected=None) -> str:
    """Category listing, in catalog order, optionally highlighting one entry."""
    name = view["name"]
    labels = {route: label for route, label, _entries in view["categories"]}
    label = labels.get(category, category)

    parts = [
        "<p><a href=\"/\">&#8592; All vaults</a></p>",
        "<h1>{0}</h1>".format(esc(name)),
        "<p class=\"meta\">catalog version {0}</p>".format(esc(view["version"])),
    ]

    nav = [
        "<a{0} href=\"{1}\">{2}</a>".format(
            " class=\"current\"" if route == category else "",
            esc(catalog_url_path(name, route)),
            esc(route_label),
        )
        for route, route_label, _entries in view["categories"]
    ]
    parts.append("<nav class=\"categories\">{0}</nav>".format("\n".join(nav)))
    parts.append("<h2>{0}</h2>".format(esc(label)))

    if selected is not None:
        known = any(
            isinstance(entry, dict) and entry.get("id") == selected
            for entry in entries
        )
        if known:
            parts.append(
                "<p class=\"selected-entry\">Showing entry <code>{0}</code>."
                "</p>".format(esc(selected))
            )
        else:
            parts.append(
                "<p class=\"notice missing-entry\">Entry &#39;{0}&#39; is not in "
                "{1}.</p>".format(esc(selected), esc(label))
            )

    if not entries:
        parts.append("<p class=\"empty\">No entries.</p>")
    else:
        rows = "\n".join(
            render_entry(view, category, entry, selected) for entry in entries
        )
        parts.append("<ol class=\"entries\">\n{0}\n</ol>".format(rows))

    return viewer_page("{0} - {1}".format(name, label), "\n".join(parts))


# Chart geometry.  The viewBox is fixed and the element scales to its column,
# so the same numbers describe every chart the viewer draws.
CHART_WIDTH = 720
CHART_HEIGHT = 200
CHART_LEFT = 54
CHART_RIGHT = 96
CHART_TOP = 16
CHART_BOTTOM = 34
CHART_MARKER_LIMIT = 24

CHART_LABELS = {"views": "Views", "likes": "Likes"}


def is_chart_number(value) -> bool:
    """Only real numbers can be plotted; ``null`` and text can not."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def chart_number(value) -> str:
    """Render a chart value for display, keeping ``null`` visible as null."""
    if value is None:
        return "null"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def axis_number(value) -> str:
    """Render an axis tick, dropping the decimals an integer range never needs."""
    if float(value).is_integer():
        return str(int(value))
    return "{0:.2f}".format(value).rstrip("0").rstrip(".")


def chart_positions(points):
    """Horizontal position of every point as a 0..1 fraction of the span.

    Points are placed on a real time axis whenever all of their timestamps
    parse, so uneven sync intervals read as uneven gaps; otherwise they fall
    back to even spacing.
    """
    total = len(points)
    if total < 2:
        return [0.0] * total
    moments = [parse_dt(point["timestamp"]) for point in points]
    if all(moment is not None for moment in moments):
        first, last = moments[0], moments[-1]
        span = (last - first).total_seconds()
        if span > 0:
            return [
                min(1.0, max(0.0, (moment - first).total_seconds() / span))
                for moment in moments
            ]
    return [index / (total - 1) for index in range(total)]


def chart_segments(points, positions):
    """Runs of plottable points; a ``null`` breaks the line rather than joining it."""
    segments = []
    run = []
    for index, point in enumerate(points):
        if is_chart_number(point["value"]):
            run.append((positions[index], float(point["value"]), point["timestamp"]))
        elif run:
            segments.append(run)
            run = []
    if run:
        segments.append(run)
    return segments


def render_chart_svg(field, points) -> str:
    """Inline SVG line chart for one field, or ``""`` when nothing is plottable."""
    positions = chart_positions(points)
    segments = chart_segments(points, positions)
    plotted = [point for segment in segments for point in segment]
    if len(plotted) < 2:
        return ""

    label = CHART_LABELS.get(field, field)
    values = [value for _x, value, _stamp in plotted]
    low, high = min(values), max(values)
    if high == low:  # a flat series still deserves a readable band
        low, high = low - 1.0, high + 1.0
    plot_width = CHART_WIDTH - CHART_LEFT - CHART_RIGHT
    plot_height = CHART_HEIGHT - CHART_TOP - CHART_BOTTOM

    def screen_x(fraction):
        return round(CHART_LEFT + fraction * plot_width, 2)

    def screen_y(value):
        return round(
            CHART_TOP + (high - value) / (high - low) * plot_height, 2
        )

    parts = [
        '<svg class="chart-plot" viewBox="0 0 {0} {1}" role="img" '
        'preserveAspectRatio="xMidYMid meet" '
        'aria-label="{2} over time">'.format(CHART_WIDTH, CHART_HEIGHT, esc(label)),
        "<title>{0} over time</title>".format(esc(label)),
    ]

    # Recessive gridlines with the value scale on the left.
    grid = ['<g class="chart-grid" aria-hidden="true">']
    ticks = ['<g class="chart-axis" aria-hidden="true">']
    for fraction in (0.0, 0.5, 1.0):
        value = low + (high - low) * fraction
        y = screen_y(value)
        grid.append(
            '<line x1="{0}" y1="{1}" x2="{2}" y2="{1}"/>'.format(
                CHART_LEFT, y, CHART_LEFT + plot_width
            )
        )
        ticks.append(
            '<text x="{0}" y="{1}" text-anchor="end">{2}</text>'.format(
                CHART_LEFT - 8, round(y + 4, 2), esc(axis_number(value))
            )
        )
    grid.append("</g>")

    baseline = CHART_HEIGHT - CHART_BOTTOM + 20
    ticks.append(
        '<text x="{0}" y="{1}">{2}</text>'.format(
            CHART_LEFT, baseline, esc(points[0]["timestamp"])
        )
    )
    if len(points) > 1:
        ticks.append(
            '<text x="{0}" y="{1}" text-anchor="end">{2}</text>'.format(
                CHART_LEFT + plot_width, baseline, esc(points[-1]["timestamp"])
            )
        )
    ticks.append("</g>")
    parts.extend(grid)
    parts.extend(ticks)

    for segment in segments:
        if len(segment) < 2:
            continue
        coordinates = " ".join(
            "{0},{1}".format(screen_x(fraction), screen_y(value))
            for fraction, value, _stamp in segment
        )
        parts.append(
            '<polyline class="chart-series" points="{0}"/>'.format(coordinates)
        )

    # Markers carry the per-point tooltip; a lone point between nulls is only
    # ever visible as its marker, so those are always drawn.
    show_all = len(plotted) <= CHART_MARKER_LIMIT
    for segment in segments:
        if not show_all and len(segment) > 1:
            continue
        for fraction, value, stamp in segment:
            parts.append(
                '<circle class="chart-marker" cx="{0}" cy="{1}" r="4">'
                "<title>{2}: {3}</title></circle>".format(
                    screen_x(fraction),
                    screen_y(value),
                    esc(stamp),
                    esc(axis_number(value)),
                )
            )

    last_x, last_value, _last_stamp = plotted[-1]
    parts.append(
        '<text class="chart-end-label" x="{0}" y="{1}">{2}</text>'.format(
            round(screen_x(last_x) + 10, 2),
            round(screen_y(last_value) + 4, 2),
            esc(axis_number(last_value)),
        )
    )
    parts.append("</svg>")
    return "\n".join(parts)


def render_chart_table(field, points) -> str:
    """The same series as a table, so the values never live in pixels alone."""
    label = CHART_LABELS.get(field, field)
    rows = "\n".join(
        '<tr><td class="stamp">{0}</td><td class="value">{1}</td></tr>'.format(
            esc(point["timestamp"]), esc(chart_number(point["value"]))
        )
        for point in points
    )
    return (
        '<details class="chart-data">\n'
        "<summary>{0} data table</summary>\n"
        '<table class="chart-table" data-field="{1}">\n'
        "<thead><tr><th>Timestamp</th><th>{0}</th></tr></thead>\n"
        "<tbody>\n{2}\n</tbody>\n</table>\n</details>"
    ).format(esc(label), esc(field), rows)


def render_chart(field, points) -> str:
    """One chart figure, or ``""`` when a single point makes a chart pointless."""
    if len(points) < 2:
        return ""
    svg = render_chart_svg(field, points)
    if not svg:
        return ""
    label = CHART_LABELS.get(field, field)
    return (
        '<figure class="chart" data-field="{0}" data-points="{1}">\n'
        "<figcaption>{2}</figcaption>\n{3}\n{4}\n</figure>"
    ).format(esc(field), len(points), esc(label), svg, render_chart_table(field, points))


def media_element(name, filename) -> str:
    """Playback element pointed at the media static endpoint."""
    href = media_asset_path(name, filename)
    tag = "audio" if filename.lower().endswith(AUDIO_EXTENSIONS) else "video"
    return (
        '<figure class="media" data-media="{file}">\n'
        '<{tag} class="media-player" controls preload="metadata" src="{href}">\n'
        "This browser can not play the stored media file. "
        '<a href="{href}">Download {file}</a>.\n'
        "</{tag}>\n"
        '<figcaption>Stored media file <code>{file}</code></figcaption>\n'
        "</figure>"
    ).format(tag=tag, href=esc(href), file=esc(filename))


def render_detail(view, category, entry, identifier) -> str:
    """Entry detail page: current metadata, stored assets and the charts."""
    name = view["name"]
    numeric = view["numeric"]
    labels = {route: route_label for route, route_label, _e in view["categories"]}
    label = labels.get(category, category)
    listing_path = catalog_url_path(name, category)

    title = digest_title(entry, numeric)
    description, has_description = digest_latest(entry, "description", numeric)
    published = entry.get("published")
    width, height = entry.get("width"), entry.get("height")
    source_link = entry_source_link(view["source"], identifier)
    removed = entry_is_removed(entry, view["removals"])
    media_file = matching_asset(view["media"], identifier)
    preview_file = matching_asset(view["previews"], identifier)

    parts = [
        '<p class="back"><a href="{0}">&#8592; Back to {1}</a></p>'.format(
            esc(listing_path), esc(label)
        ),
        "<h1>{0}</h1>".format(esc(title)),
        '<p class="meta">{0} &middot; {1} &middot; catalog version {2}{3}</p>'.format(
            esc(name), esc(label), esc(view["version"]),
            ' <span class="badge removed">Removed</span>' if removed else "",
        ),
    ]

    dimensions = (
        "{0} &#215; {1}".format(esc(width), esc(height))
        if width is not None and height is not None
        else "unknown"
    )
    parts.append(
        "<dl class=\"entry-meta\">\n"
        "<dt>Entry id</dt><dd><code class=\"id\">{ident}</code></dd>\n"
        "<dt>Published</dt><dd class=\"published\">{published}</dd>\n"
        "<dt>Dimensions</dt>"
        "<dd class=\"dimensions\" data-width=\"{width}\" data-height=\"{height}\">"
        "{dimensions}</dd>\n"
        "<dt>Source</dt>"
        "<dd><a class=\"source-link\" href=\"{source}\" rel=\"noreferrer\">"
        "{source}</a></dd>\n"
        "</dl>".format(
            ident=esc(identifier),
            published=esc(published),
            width=esc(width),
            height=esc(height),
            dimensions=dimensions,
            source=esc(source_link),
        )
    )

    if has_description:
        text = description if isinstance(description, str) else str(description)
        parts.append('<p class="description">{0}</p>'.format(esc(text)))
    else:
        parts.append('<p class="description empty">(no description)</p>')

    if media_file:
        parts.append(media_element(name, media_file))
    else:
        parts.append(
            '<p class="media missing">No downloaded media file for this entry.</p>'
        )

    if preview_file:
        parts.append(
            '<figure class="preview" data-preview="{file}">\n'
            '<img src="{href}" alt="Preview image for {title}">\n'
            "</figure>".format(
                file=esc(preview_file),
                href=esc(preview_asset_path(name, identifier)),
                title=esc(title),
            )
        )

    data = entry_chart_data(entry, numeric)
    payload = dict(data)
    payload.update({
        "id": identifier,
        "category": category,
        "version": view["version"],
    })
    parts.append(
        '<div class="charts viz-root">\n'
        '<script id="{0}" type="application/json">{1}</script>'.format(
            CHART_DATA_ELEMENT_ID, chart_json(payload)
        )
    )
    charts = [render_chart(field, data[field]) for field in CHART_FIELDS]
    charts = [chart for chart in charts if chart]
    if charts:
        parts.extend(charts)
    else:
        parts.append('<p class="charts empty">Not enough history to chart yet.</p>')
    parts.append("</div>")

    return viewer_page("{0} - {1}".format(title, name), "\n".join(parts))


def render_message(heading, message) -> str:
    return viewer_page(
        "mvault viewer",
        "<h1>{0}</h1>\n<p>{1}</p>\n<p><a href=\"/\">Back to the vault "
        "list</a></p>".format(esc(heading), esc(message)),
    )


def render_redirect(location) -> str:
    return viewer_page(
        "Redirecting",
        "<p>Redirecting to <a href=\"{0}\">{0}</a>.</p>".format(esc(location)),
    )


# ---------------------------------------------------------------------------
# viewer: recent vaults
# ---------------------------------------------------------------------------

# Recent vaults are remembered twice over: in a long-lived cookie, so the same
# browser still sees them in a later session, and in a small state file, so a
# browser that drops cookies is not left with an empty list.


def viewer_state_dir() -> str:
    override = os.environ.get("MVAULT_STATE_DIR")
    if override:
        return override
    home = os.path.expanduser("~")
    if not home or home.startswith("~"):
        home = tempfile.gettempdir()
    return os.path.join(home, ".mvault")


def viewer_state_path() -> str:
    return os.path.join(viewer_state_dir(), VIEWER_STATE_NAME)


def read_viewer_state():
    try:
        with open(viewer_state_path(), "r", encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, ValueError):
        return {}
    return stored if isinstance(stored, dict) else {}


def clean_names(names):
    cleaned = []
    for name in names if isinstance(names, list) else []:
        if isinstance(name, str) and name and name not in cleaned:
            cleaned.append(name)
    return cleaned[:RECENT_LIMIT]


def read_recent_names(base_dir):
    """Recent vault names previously visited in this vault root."""
    recent = read_viewer_state().get("recent")
    if not isinstance(recent, dict):
        return []
    return clean_names(recent.get(base_dir))


def write_recent_names(base_dir, names) -> None:
    stored = read_viewer_state()
    recent = stored.get("recent")
    if not isinstance(recent, dict):
        recent = {}
    recent[base_dir] = clean_names(names)
    stored["recent"] = recent
    try:
        os.makedirs(viewer_state_dir(), exist_ok=True)
        with open(viewer_state_path(), "w", encoding="utf-8") as handle:
            json.dump(stored, handle)
    except (OSError, ValueError):
        pass  # remembering recent vaults must never break a page render


def promote(names, name):
    """``name`` first, everything else in its previous order."""
    promoted = [name]
    for other in names:
        if other != name and other not in promoted:
            promoted.append(other)
    return promoted[:RECENT_LIMIT]


def merge_recent(first, second):
    merged = []
    for name in list(first) + list(second):
        if name and name not in merged:
            merged.append(name)
    return merged[:RECENT_LIMIT]


def parse_recent_cookie(cookies):
    morsel = cookies.get(RECENT_COOKIE)
    if morsel is None or not morsel.value:
        return []
    try:
        decoded = json.loads(unquote(morsel.value))
    except ValueError:
        return []
    return clean_names(decoded)


def recent_cookie(names) -> str:
    value = quote(json.dumps(clean_names(names)), safe="")
    return "{0}={1}; Path=/; Max-Age={2}; SameSite=Lax".format(
        RECENT_COOKIE, value, RECENT_COOKIE_AGE
    )


def missing_cookie(name) -> str:
    return "{0}={1}; Path=/; Max-Age={2}; SameSite=Lax".format(
        MISSING_COOKIE, url_segment(name), MISSING_COOKIE_AGE
    )


def expired_cookie(cookie_name) -> str:
    return "{0}=; Path=/; Max-Age=0; SameSite=Lax".format(cookie_name)


class ViewerState:
    """Server-side half of the recent-vault memory, shared by all requests."""

    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir
        self._lock = threading.Lock()
        self._recent = read_recent_names(base_dir)
        self._missing = None

    def recent(self):
        with self._lock:
            return list(self._recent)

    def record_visit(self, name):
        with self._lock:
            self._recent = promote(self._recent, name)
            snapshot = list(self._recent)
        write_recent_names(self.base_dir, snapshot)
        return snapshot

    def note_missing(self, name) -> None:
        """Remember a vault that could not be opened, for the next landing page."""
        with self._lock:
            self._missing = (name, time.time())

    def take_missing(self):
        with self._lock:
            pending = self._missing
            self._missing = None
        if pending is None:
            return None
        name, when = pending
        if time.time() - when > MISSING_TTL_SECONDS:
            return None
        return name


# ---------------------------------------------------------------------------
# viewer: http
# ---------------------------------------------------------------------------


class ViewerHandler(BaseHTTPRequestHandler):
    """Request handler for the local viewer.

    Every path ends in a well-formed HTML response or a redirect; an
    unreadable or missing vault sends the browser back to the landing page
    instead of failing the request.
    """

    server_version = "mvault-viewer"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    state = None

    # Requests are not logged; the viewer's output is the served pages.
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    # -- dispatch ---------------------------------------------------------

    def _dispatch(self, method) -> None:
        self._head_only = method == "HEAD"
        try:
            self._handle(method)
        except Exception:  # never leak a traceback to the browser
            self._send_html(
                500,
                render_message(
                    "Something went wrong",
                    "The viewer could not complete this request.",
                ),
            )

    def _handle(self, method) -> None:
        parsed = urlsplit(self.path)
        segments = [unquote(part) for part in parsed.path.split("/") if part]

        if method == "POST":
            self._handle_post(segments)
            return
        if not segments:
            self._handle_landing(parse_qs(parsed.query, keep_blank_values=True))
            return
        if segments[0] == "catalog":
            self._handle_catalog(segments)
            return
        if segments[0] == VAULT_ROUTE:
            self._handle_vault(segments)
            return
        self._send_html(404, render_message("Not found", "No such page."))

    # -- routes -----------------------------------------------------------

    def _handle_post(self, segments) -> None:
        # The body is always consumed, so the connection stays usable.
        fields = self._read_form()
        if segments:
            self._redirect("/", 303)
            return
        values = fields.get("catalog") or []
        value = values[0].strip() if values else ""
        if not value:
            self._redirect("/", 303)
            return
        self._redirect(catalog_url_path(value), 303)

    def _handle_landing(self, query) -> None:
        cookies = self._cookies()
        headers = []

        missing = None
        requested = query.get("missing") or []
        if requested and requested[0].strip():
            missing = requested[0]
        if missing is None:
            stored = cookies.get(MISSING_COOKIE)
            if stored is not None and stored.value:
                missing = unquote(stored.value)
        if missing is None:
            missing = self.state.take_missing()
        if cookies.get(MISSING_COOKIE) is not None:
            headers.append(expired_cookie(MISSING_COOKIE))

        recent = []
        names = merge_recent(parse_recent_cookie(cookies), self.state.recent())
        for name in names:
            try:
                view = load_vault_view(self.state.base_dir, name)
            except MVaultError:
                continue  # the vault went away; drop it from the list
            recent.append(
                (name, catalog_url_path(name, view["default_category"]))
            )

        self._send_html(200, render_landing(recent, missing), headers)

    def _handle_catalog(self, segments) -> None:
        if len(segments) < 2:
            self._redirect("/")
            return

        name = segments[1]
        try:
            view = load_vault_view(self.state.base_dir, name)
        except MVaultError:
            self.state.note_missing(name)
            self._redirect("/", 302, [missing_cookie(name)])
            return

        # Reaching any page of a vault counts as visiting it.
        self.state.record_visit(name)
        cookies = [recent_cookie(promote(parse_recent_cookie(self._cookies()), name))]

        default_path = catalog_url_path(name, view["default_category"])
        if len(segments) == 2:
            self._redirect(default_path, 302, cookies)
            return

        category = segments[2]
        entries = None
        for route, _label, route_entries in view["categories"]:
            if route == category:  # category matching is case-sensitive
                entries = route_entries
                break
        if entries is None:
            self._redirect(default_path, 302, cookies)
            return

        if len(segments) > 4:
            self._send_html(
                404, render_message("Not found", "No such page."), cookies
            )
            return
        if len(segments) == 3:
            self._send_html(200, render_listing(view, category, entries), cookies)
            return

        # An entry is only ever looked for inside the category it was asked
        # for, so the same id in another category can not answer for it.
        identifier = segments[3]
        entry = find_entry(entries, identifier)
        if entry is None:
            self._send_html(
                404, render_listing(view, category, entries, identifier), cookies
            )
            return
        self._send_html(
            200, render_detail(view, category, entry, identifier), cookies
        )

    def _handle_vault(self, segments) -> None:
        """Serve one stored media file or preview image of a vault."""
        if len(segments) < 2:
            self._not_found()
            return

        name = segments[1]
        try:
            view = load_vault_view(self.state.base_dir, name)
        except MVaultError:
            self.state.note_missing(name)
            self._redirect("/", 302, [missing_cookie(name)])
            return

        if len(segments) != 4:
            self._not_found()
            return
        kind, tail = segments[2], segments[3]

        if kind == MEDIA_ROUTE_SEGMENT:
            if not safe_asset_name(tail):
                self._forbidden()
                return
            self._send_asset(
                os.path.join(view["directory"], MEDIA_DIRNAME), tail, False
            )
            return

        if kind == PREVIEW_ROUTE_SEGMENT:
            if not safe_asset_name(tail):
                self._forbidden()
                return
            # Previews are addressed by entry id: the stored file is the one
            # whose saved name contains it.
            filename = matching_asset(view["previews"], tail)
            if filename is None or not safe_asset_name(filename):
                self._not_found()
                return
            self._send_asset(
                os.path.join(view["directory"], PREVIEW_DIRNAME), filename, True
            )
            return

        self._not_found()

    def _send_asset(self, directory, filename, image_only) -> None:
        path = os.path.join(directory, filename)
        if not within_directory(directory, path):
            self._forbidden()
            return
        if not os.path.isfile(path):
            self._not_found()
            return
        try:
            size = os.path.getsize(path)
            handle = open(path, "rb")
        except OSError:
            self._not_found()
            return
        # Media files can be large, so they are streamed rather than read into
        # memory in one piece.
        with handle:
            self._send_stream(handle, size, asset_mime(filename, image_only))

    def _not_found(self) -> None:
        self._send_html(
            404, render_message("Not found", "No such file in this vault.")
        )

    def _forbidden(self) -> None:
        self._send_html(
            403, render_message("Forbidden", "That path is not allowed.")
        )

    # -- plumbing ---------------------------------------------------------

    def _cookies(self):
        jar = SimpleCookie()
        header = self.headers.get("Cookie")
        if header:
            try:
                jar.load(header)
            except Exception:
                return SimpleCookie()
        return jar

    def _read_form(self):
        raw = self.headers.get("Content-Length")
        try:
            length = int(raw) if raw else 0
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return {}
        try:
            body = self.rfile.read(length)
        except OSError:
            return {}
        return parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)

    def _redirect(self, location, status=302, cookies=None) -> None:
        self._send_html(
            status, render_redirect(location), cookies, {"Location": location}
        )

    def _send_html(self, status, body, cookies=None, headers=None) -> None:
        payload = body.encode("utf-8")
        try:
            self.send_response(status)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            for cookie in cookies or []:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            if not getattr(self, "_head_only", False):
                self.wfile.write(payload)
        except OSError:
            pass  # the browser hung up mid-response

    def _send_stream(self, handle, size, content_type) -> None:
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "none")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if getattr(self, "_head_only", False):
                return
            while True:
                chunk = handle.read(ASSET_CHUNK_SIZE)
                if not chunk:
                    break
                self.wfile.write(chunk)
        except OSError:
            pass  # the browser hung up mid-response


class ViewerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_viewer_handler(state):
    """Bind one :class:`ViewerState` to a fresh handler class."""
    return type("BoundViewerHandler", (ViewerHandler,), {"state": state})


def open_browser(url) -> None:
    """Open the viewer in a browser, without ever blocking the server."""
    if os.environ.get("MVAULT_NO_BROWSER"):
        return

    def launch():
        try:
            webbrowser.open(url, new=2)
        except Exception:
            pass

    threading.Thread(target=launch, daemon=True).start()


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_init(name: str, url: str) -> int:
    if os.path.exists(name):
        raise MVaultError("vault '{0}' already exists".format(name))
    try:
        os.makedirs(name)
    except OSError as exc:
        raise MVaultError("cannot create vault '{0}': {1}".format(name, exc))

    catalog = {"version": CATALOG_VERSION, "source": url}
    for category in CATEGORIES:
        catalog[category] = []
    write_catalog(name, catalog)
    print("Initialized vault '{0}' at {1}".format(name, catalog_path(name)))
    return 0


def cmd_sync(
    name,
    limits=None,
    skip_metadata=False,
    skip_download=False,
    fmt=None,
    host=None,
    port=None,
):
    # A legacy vault is migrated in memory first, so the download phase always
    # works against a v3 catalog and the migrated ``source`` URL.
    catalog, _migrated, _version = load_vault(name)

    counts = None
    changes = {}
    if not skip_metadata:
        source_by_category = fetch_source(catalog["source"])
        stamp = sync_timestamp(catalog)
        counts, changes = sync_catalog(catalog, source_by_category, stamp)
        # Metadata is durably stored before the download phase runs, so a
        # failing download can never cost the catalog update.
        write_catalog(name, catalog)
        total = sum(len(catalog[category]) for category in CATEGORIES)
        print("Synced vault '{0}' at {1} ({2} entries)".format(name, stamp, total))
    else:
        print("Skipped metadata phase for vault '{0}'".format(name))

    if not skip_download:
        stats = download_phase(name, catalog, limits, fmt)
        print(
            "Downloaded {0} media file(s) and {1} preview file(s)"
            "{2}".format(
                stats["media"],
                stats["previews"],
                ", {0} skipped".format(stats["failed"]) if stats["failed"] else "",
            )
        )
    else:
        print("Skipped download phase for vault '{0}'".format(name))

    if counts is not None:
        print(
            "Changes: {0} added, {1} removed, {2} updated".format(
                counts["added"], counts["removed"], counts["updated"]
            )
        )
        sections = build_sync_sections(catalog, changes, name, host, port)
        for line in render_change_sections(sections):
            print(line)
    return 0


def cmd_digest(name: str, host=None, port=None) -> int:
    raw = read_catalog_document(name)
    plan = digest_plan(raw, name)
    sections, totals = build_digest(plan, name, host, port)
    for line in render_digest(name, plan, sections, totals):
        print(line)
    return 0


def cmd_migrate(name: str) -> int:
    catalog, migrated, version = load_vault(name)
    if not migrated:
        print(
            "Vault '{0}' already uses catalog version {1}".format(
                name, CATALOG_VERSION
            )
        )
        return 0
    write_catalog(name, catalog)
    print(
        "Migrated vault '{0}' from catalog version {1} to {2}".format(
            name, version, CATALOG_VERSION
        )
    )
    return 0


def cmd_serve(name=None, host=None, port=None, launch_browser=True) -> int:
    """Serve the local viewer and open a browser at the requested page."""
    bind_host = host if host else DEFAULT_VIEWER_HOST
    bind_port = DEFAULT_VIEWER_PORT if port is None else int(port)
    base_dir = os.getcwd()

    handler = make_viewer_handler(ViewerState(base_dir))
    try:
        server = ViewerServer((bind_host, bind_port), handler)
    except OSError as exc:
        raise MVaultError(
            "cannot serve the viewer on {0}:{1}: {2}".format(
                bind_host, bind_port, exc
            )
        )

    # The advertised URL always uses the host exactly as it was given.
    served_port = server.server_address[1] if not bind_port else bind_port
    origin = "{0}://{1}:{2}".format(DEFAULT_VIEWER_SCHEME, bind_host, served_port)
    target = origin + "/"
    if name:
        target = origin + resolved_default_path(base_dir, name)

    print("Serving vault viewer at {0}/".format(origin))
    print("Opening {0}".format(target))
    sys.stdout.flush()
    if launch_browser:
        open_browser(target)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("")
    finally:
        server.server_close()
    return 0


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------


def nonnegative_int(text):
    """argparse type for the per-category download limits."""
    value = str(text).strip()
    if not value.isdigit():
        raise argparse.ArgumentTypeError(
            "'{0}' is not a non-negative integer".format(text)
        )
    try:
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "'{0}' is not a non-negative integer".format(text)
        )


def port_number(text):
    """argparse type for ``--port``."""
    value = str(text).strip()
    if not value.isdigit() or not 0 <= int(value) <= 65535:
        raise argparse.ArgumentTypeError("'{0}' is not a port number".format(text))
    return int(value)


def add_viewer_link_options(parser) -> None:
    """``--host``/``--port`` decide the viewer links printed in reports."""
    parser.add_argument(
        "--host",
        metavar="<host>",
        default=DEFAULT_VIEWER_HOST,
        help="host used in viewer links (default: {0})".format(
            DEFAULT_VIEWER_HOST
        ),
    )
    parser.add_argument(
        "--port",
        metavar="<port>",
        type=port_number,
        default=DEFAULT_VIEWER_PORT,
        help="port used in viewer links (default: {0})".format(
            DEFAULT_VIEWER_PORT
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mvault",
        description=(
            "Create local vaults for media-platform metadata and record "
            "tracked-field history by sync timestamp."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<subcommand>")

    init_parser = subparsers.add_parser(
        "init", help="create a new vault with an empty catalog"
    )
    init_parser.add_argument("name", help="vault directory to create")
    init_parser.add_argument("url", help="source metadata URL")

    sync_parser = subparsers.add_parser(
        "sync", help="fetch the source and update the vault catalog"
    )
    sync_parser.add_argument("name", help="existing vault directory")
    for category in CATEGORIES:
        sync_parser.add_argument(
            "--{0}".format(category),
            metavar="<n>",
            type=nonnegative_int,
            default=None,
            help="maximum number of {0} media downloads".format(category),
        )
    sync_parser.add_argument(
        "--skip-metadata",
        action="store_true",
        help="skip the source fetch and metadata update",
    )
    sync_parser.add_argument(
        "--skip-download",
        action="store_true",
        help="skip the download phase",
    )
    sync_parser.add_argument(
        "--format",
        metavar="<str>",
        default=None,
        help="override the media download format and output extension",
    )
    add_viewer_link_options(sync_parser)

    migrate_parser = subparsers.add_parser(
        "migrate", help="convert a legacy catalog to the native version"
    )
    migrate_parser.add_argument("name", help="existing vault directory")

    digest_parser = subparsers.add_parser(
        "digest", help="summarize notable changes recorded in a vault"
    )
    digest_parser.add_argument("name", help="existing vault directory")
    add_viewer_link_options(digest_parser)

    serve_parser = subparsers.add_parser(
        "serve", help="serve the local vault viewer in a browser"
    )
    serve_parser.add_argument(
        "name",
        nargs="?",
        default=None,
        help="vault to open in the browser (default: the vault list)",
    )
    serve_parser.add_argument(
        "--host",
        metavar="<host>",
        default=DEFAULT_VIEWER_HOST,
        help="bind host (default: {0})".format(DEFAULT_VIEWER_HOST),
    )
    serve_parser.add_argument(
        "--port",
        metavar="<port>",
        type=port_number,
        default=DEFAULT_VIEWER_PORT,
        help="bind port (default: {0})".format(DEFAULT_VIEWER_PORT),
    )
    serve_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="serve without opening a browser window",
    )

    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()

    if not argv:
        parser.print_usage(sys.stderr)
        sys.stderr.write("mvault: error: a subcommand is required\n")
        return 2

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_usage(sys.stderr)
        sys.stderr.write("mvault: error: a subcommand is required\n")
        return 2

    try:
        if args.command == "init":
            return cmd_init(args.name, args.url)
        if args.command == "migrate":
            return cmd_migrate(args.name)
        if args.command == "digest":
            return cmd_digest(args.name, args.host, args.port)
        if args.command == "serve":
            return cmd_serve(
                args.name, args.host, args.port, not args.no_browser
            )
        limits = {category: getattr(args, category) for category in CATEGORIES}
        return cmd_sync(
            args.name,
            limits=limits,
            skip_metadata=args.skip_metadata,
            skip_download=args.skip_download,
            fmt=args.format,
            host=args.host,
            port=args.port,
        )
    except MVaultError as exc:
        sys.stderr.write("mvault: error: {0}\n".format(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
