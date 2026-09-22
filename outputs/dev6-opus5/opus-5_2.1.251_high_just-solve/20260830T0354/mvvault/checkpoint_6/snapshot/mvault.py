#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata with tracked-field history."""

import argparse
import html
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, quote, unquote, urlparse

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

# --------------------------------------------------------------------------
# viewer constants
# --------------------------------------------------------------------------

# The local browser viewer and the links appended to human-facing reports share
# these defaults so a printed link always addresses a default `serve` run.
VIEWER_SCHEME = "http"
VIEWER_HOST = "127.0.0.1"
VIEWER_PORT = 8840

# Version 1 vaults keep every entry in a single "entries" array; version 2 and
# version 3 vaults split them across the three native categories.
# Tracked fields the entry detail page exposes as chart data.
CHART_FIELDS = ("views", "likes")

V1_CATEGORIES = ("entries",)
V1_DEFAULT_CATEGORY = "entries"
DEFAULT_CATEGORY = "episodes"


def categories_for_version(version):
    """Valid viewer categories for a catalog of this version."""
    return V1_CATEGORIES if version == 1 else CATEGORIES


def default_category_for_version(version):
    """Category a bare /catalog/<name> request redirects to."""
    return V1_DEFAULT_CATEGORY if version == 1 else DEFAULT_CATEGORY


def _url_segment(value):
    """Escape one path segment, leaving ordinary vault/category/id text alone."""
    return quote(value if isinstance(value, str) else str(value), safe="")


def catalog_route(name, category=None, entry_id=None):
    """Build a viewer path such as /catalog/<name>/<category>/<id>."""
    path = "/catalog/" + _url_segment(name)
    if category is not None:
        path += "/" + _url_segment(category)
        if entry_id is not None:
            path += "/" + _url_segment(entry_id)
    return path


def viewer_origin(host=None, port=None):
    host = VIEWER_HOST if host is None else host
    port = VIEWER_PORT if port is None else port
    return "%s://%s:%d" % (VIEWER_SCHEME, host, int(port))


def viewer_link(name, category, entry_id, host=None, port=None):
    """Absolute viewer link for one entry, as appended to change reports."""
    return viewer_origin(host, port) + catalog_route(name, category, entry_id)


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
# annotations
# --------------------------------------------------------------------------

# A timecode component is a run of digits: leading zeros are fine and
# conventional clock bounds are not enforced, so "90:00" is a valid MM:SS
# timecode worth 5400 seconds.
_TIMECODE_PART_RE = re.compile(r"^\d+$")
_TIMECODE_HINT = "expected SS, MM:SS, or HH:MM:SS"


class AnnotationError(MVaultError):
    """A rejected annotation request, carrying the HTTP status to report."""

    def __init__(self, status, message):
        MVaultError.__init__(self, message)
        self.status = status


def parse_timecode(value):
    """Whole seconds for an `SS`, `MM:SS`, or `HH:MM:SS` timecode string."""
    if not isinstance(value, str):
        raise AnnotationError(400, "invalid 'timecode' format %r: %s"
                                   % (value, _TIMECODE_HINT))
    text = value.strip()
    parts = text.split(":")
    if not text or len(parts) > 3:
        raise AnnotationError(400, "invalid 'timecode' format %r: %s"
                                   % (value, _TIMECODE_HINT))
    seconds = 0
    for part in parts:
        if not _TIMECODE_PART_RE.match(part):
            raise AnnotationError(400, "invalid 'timecode' format %r: %s"
                                       % (value, _TIMECODE_HINT))
        seconds = seconds * 60 + int(part)
    return seconds


def format_timecode(seconds):
    """Render whole seconds back as MM:SS, or HH:MM:SS once past an hour."""
    if not _is_int(seconds) or seconds < 0:
        return "" if seconds is None else str(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, secs)
    return "%d:%02d" % (minutes, secs)


def entry_annotations(entry):
    """The annotations stored on one entry, in creation order."""
    items = entry.get(ANNOTATIONS_FIELD)
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def find_annotation(annotations, annotation_id):
    """The annotation carrying this id, or None."""
    for item in annotations:
        if item.get("id") == annotation_id:
            return item
    return None


def next_annotation_id(annotations):
    """A fresh annotation id no annotation of this entry already uses."""
    taken = set()
    for item in annotations:
        value = item.get("id")
        if isinstance(value, str):
            taken.add(value)
    index = len(annotations) + 1
    while ("a%d" % index) in taken:
        index += 1
    return "a%d" % index


def parse_annotation_body(raw):
    """Decode an annotation request body into a JSON object."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise AnnotationError(400, "request body must be UTF-8 encoded JSON")
    if not raw or not raw.strip():
        raise AnnotationError(400, "request body must be a JSON object")
    try:
        payload = json.loads(raw)
    except ValueError:
        raise AnnotationError(400, "request body is not well-formed JSON")
    if not isinstance(payload, dict):
        raise AnnotationError(400, "request body must be a JSON object")
    return payload


def _required_field(payload, field):
    """One request field that has to be there, named in the failure."""
    value = payload.get(field)
    if value is None:
        raise AnnotationError(400, "missing required field %r" % field)
    return value


def create_annotation(entry, payload):
    """Append one annotation to an entry and return it."""
    title = _required_field(payload, "title")
    timecode = _required_field(payload, "timecode")
    seconds = parse_timecode(timecode)
    annotations = entry_annotations(entry)
    annotation = {
        "id": next_annotation_id(annotations),
        "timecode": seconds,
        "title": title,
        "body": payload.get("body"),
    }
    annotations.append(annotation)
    entry[ANNOTATIONS_FIELD] = annotations
    return annotation


def update_annotation(entry, payload):
    """Replace the fields an update names, leaving omitted ones alone."""
    annotation_id = _required_field(payload, "id")
    annotations = entry_annotations(entry)
    annotation = find_annotation(annotations, annotation_id)
    if annotation is None:
        raise AnnotationError(404, "no annotation %r in this entry"
                                   % (annotation_id,))
    if payload.get("title") is not None:
        annotation["title"] = payload["title"]
    if "body" in payload:
        annotation["body"] = payload["body"]
    entry[ANNOTATIONS_FIELD] = annotations
    return annotation


def delete_annotation(entry, payload):
    """Drop one annotation, keeping the order of the rest."""
    annotation_id = _required_field(payload, "id")
    annotations = entry_annotations(entry)
    annotation = find_annotation(annotations, annotation_id)
    if annotation is None:
        raise AnnotationError(404, "no annotation %r in this entry"
                                   % (annotation_id,))
    entry[ANNOTATIONS_FIELD] = [item for item in annotations
                                if item is not annotation]
    return annotation


ANNOTATION_METHODS = ("POST", "PATCH", "DELETE")
_ANNOTATION_ACTIONS = {
    "POST": create_annotation,
    "PATCH": update_annotation,
    "DELETE": delete_annotation,
}


def annotation_target_category(version, category):
    """Post-migration category for a mutation addressed to `category`.

    A version 1 vault keeps every entry in `entries`, so an annotation request
    still addresses that pre-migration name while the migrated entry lands in
    `episodes`.
    """
    if version == 1 and category == V1_DEFAULT_CATEGORY:
        return DEFAULT_CATEGORY
    return category if category in CATEGORIES else None


def apply_annotation(name, directory, raw, version, category, entry_id,
                     method, payload, stamp=None):
    """Apply one annotation mutation to a vault and persist the result.

    Legacy vaults are migrated to version 3 first because `annotations` does
    not exist before then. The migration and the annotation are written in a
    single pass, so `catalog.bak` keeps the catalog as it was before both.
    Returns ``(target_category, annotation)``.
    """
    action = _ANNOTATION_ACTIONS.get(method)
    if action is None:
        raise AnnotationError(405, "method %s is not allowed here" % method)

    target = annotation_target_category(version, category)
    if target is None:
        raise AnnotationError(404, "no category %r in vault %r"
                                   % (category, name))

    if version == CATALOG_VERSION:
        catalog = raw
    else:
        try:
            catalog = migrate_catalog(directory, raw, version, stamp)
        except MVaultError as exc:
            # Nothing has been written, so the catalog on disk is untouched.
            raise AnnotationError(500, "vault %r: automatic migration to catalog "
                                       "version %d failed: %s"
                                       % (name, CATALOG_VERSION, exc))

    entry = find_entry(catalog, target, entry_id)
    if entry is None:
        raise AnnotationError(404, "no entry %r in category %r of vault %r"
                                   % (entry_id, category, name))

    annotation = action(entry, payload)
    try:
        write_catalog(directory, catalog)
    except MVaultError as exc:
        raise AnnotationError(500, str(exc))
    return target, annotation


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


def digest_link_category(version, key):
    """Category used in a viewer link for an entry found under `key`.

    Version 1 keeps everything in "entries"; version 2 and 3 report the
    category the entry actually resides in.
    """
    return V1_DEFAULT_CATEGORY if version == 1 else key


def build_digest(name, catalog, version, host=None, port=None):
    """Group notable per-entry changes by category and change type."""
    sections = []
    for key, label in digest_categories(version):
        items = catalog.get(key)
        if not isinstance(items, list):
            items = []
        category = digest_link_category(version, key)
        groups = {group: [] for group in DIGEST_GROUP_ORDER}
        for entry in items:
            if not isinstance(entry, dict):
                continue
            group, changed, reappeared = classify_entry(entry, version)
            if group is None:
                continue
            entry_id = entry.get("id")
            groups[group].append({
                "title": entry_title(entry, version),
                "fields": changed,
                "reappeared": reappeared,
                "link": viewer_link(name, category, entry_id, host, port)
                        if isinstance(entry_id, str) and entry_id else None,
            })
        if any(groups[group] for group in DIGEST_GROUP_ORDER):
            sections.append((label, groups))
    return sections


def format_change(item):
    """One reported entry: title, detail suffix when any, then viewer link."""
    details = []
    if item["reappeared"]:
        details.append("reappeared")
    details.extend(item["fields"])
    if details:
        text = "%s (%s)" % (item["title"], ", ".join(details))
    else:
        text = item["title"]
    link = item.get("link")
    if link:
        text = "%s %s" % (text, link)
    return text


def render_change_sections(sections):
    """Render digest-style sections as indented report lines."""
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
    return lines


def classify_sync_entry(entry, stamp):
    """Classify what a single sync stamp did to an entry.

    Returns ``(group, changed_fields, reappeared)`` or ``None`` when this sync
    left the entry untouched.
    """
    present = {}
    for field in TRACKED_FIELDS:
        history = entry.get(field)
        if isinstance(history, dict) and history:
            present[field] = history
    if not present:
        return None
    touched = [field for field in TRACKED_FIELDS
               if field in present and stamp in present[field]]
    if not touched:
        return None
    if all(len(history) == 1 and stamp in history
           for history in present.values()):
        return GROUP_ADDITIONS, [], False

    removed = present.get("removed")
    if removed is not None and stamp in removed and removed[stamp] is True:
        return GROUP_REMOVALS, [], False

    reappeared = False
    if removed is not None and stamp in removed:
        latest, prior, count = history_tail(removed, CATALOG_VERSION)
        if latest is False and count > 1 and prior is True:
            reappeared = True
    changed = [field for field in SOURCE_TRACKED_FIELDS if field in touched]
    if not changed and not reappeared:
        return None
    return GROUP_UPDATES, changed, reappeared


def build_sync_report(name, catalog, stamp, host=None, port=None):
    """Digest-style sections covering only what this sync changed."""
    sections = []
    for category, label in DIGEST_GROUPS:
        items = catalog.get(category)
        if not isinstance(items, list):
            items = []
        groups = {group: [] for group in DIGEST_GROUP_ORDER}
        for entry in items:
            if not isinstance(entry, dict):
                continue
            classified = classify_sync_entry(entry, stamp)
            if classified is None:
                continue
            group, changed, reappeared = classified
            entry_id = entry.get("id")
            groups[group].append({
                "title": entry_title(entry, CATALOG_VERSION),
                "fields": changed,
                "reappeared": reappeared,
                "link": viewer_link(name, category, entry_id, host, port)
                        if isinstance(entry_id, str) and entry_id else None,
            })
        if any(groups[group] for group in DIGEST_GROUP_ORDER):
            sections.append((label, groups))
    return sections


def cmd_digest(name, host=None, port=None):
    # Read-only: the catalog is never migrated, rewritten, or backed up here.
    raw = read_catalog_file(name)
    version = detect_version(name, raw)
    source = digest_source_url(name, raw, version)
    sections = build_digest(name, raw, version, host, port)

    lines = render_change_sections(sections)
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
             fmt=None, host=None, port=None):
    limits = limits or {}
    fmt = normalize_format(fmt)
    catalog, version = load_catalog(name)

    summary = None
    if not skip_metadata:
        summary = sync_metadata_phase(name, catalog, version)
        # The catalog is native (version 3) by this point, so a migrated
        # version 1 vault reports its episode entries under "episodes".
        report = build_sync_report(name, catalog, summary[0], host, port)
        for line in render_change_sections(report):
            print(line)

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
# viewer: persisted "recent vaults" list
# --------------------------------------------------------------------------

RECENT_LIMIT = 20
RECENT_FILE = "recent.json"
RECENT_COOKIE = "mvault_recent"
NOTFOUND_COOKIE = "mvault_notfound"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365

# Recent vaults survive the browser session because the viewer keeps the list
# next to its own state, not only in a cookie.
_VIEWER_STATE = {"missing": None}


def viewer_state_dir():
    override = os.environ.get("MVAULT_STATE_DIR")
    if override:
        return override
    home = os.path.expanduser("~")
    if home and home != "~" and os.path.isdir(home):
        return os.path.join(home, ".mvault")
    return os.path.join(tempfile.gettempdir(), "mvault-state")


def recent_store_path():
    return os.path.join(viewer_state_dir(), RECENT_FILE)


def load_recent():
    """Stored recent-vault records, most recently visited first."""
    try:
        with open(recent_store_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    records = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        directory = item.get("dir")
        records.append({
            "name": name,
            "dir": directory if isinstance(directory, str) else None,
        })
    return records


def save_recent(records):
    path = recent_store_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        partial = path + ".tmp"
        with open(partial, "w", encoding="utf-8") as handle:
            json.dump(records[:RECENT_LIMIT], handle, indent=2)
        os.replace(partial, path)
    except OSError:
        # A viewer that cannot persist its history still works; the cookie
        # copy keeps the list alive for the browser that produced it.
        pass


def remember_recent(name, directory):
    """Record a vault visit, moving it to the front of the recent list."""
    records = [r for r in load_recent()
               if not (r["name"] == name and r.get("dir") in (None, directory))]
    records.insert(0, {"name": name, "dir": directory})
    records = records[:RECENT_LIMIT]
    save_recent(records)
    return [r["name"] for r in records]


# --------------------------------------------------------------------------
# viewer: vault access
# --------------------------------------------------------------------------

def resolve_vault_dir(name):
    """Absolute directory for a vault name, or None when it escapes the root."""
    if not isinstance(name, str) or not name:
        return None
    if name.startswith("/") or name.startswith("\\") or os.path.isabs(name):
        return None
    base = os.path.abspath(os.getcwd())
    try:
        target = os.path.abspath(os.path.join(base, name))
    except (OSError, ValueError):
        return None
    if target == base or not target.startswith(base + os.sep):
        return None
    return target


def viewer_load(name):
    """Return ``(directory, raw_catalog, version)`` for a viewable vault."""
    directory = resolve_vault_dir(name)
    if directory is None or not os.path.isdir(directory):
        raise MVaultError("vault %r does not exist" % name)
    raw = read_catalog_file(directory)
    return directory, raw, detect_version(directory, raw)


def resolve_default_route(name):
    """Route /catalog/<name> redirects to, resolved from the stored version."""
    try:
        _directory, _raw, version = viewer_load(name)
    except MVaultError:
        return catalog_route(name)
    return catalog_route(name, default_category_for_version(version))


def recent_for_display(extra_names=()):
    """Recent vaults still reachable from the serving directory."""
    seen = set()
    listed = []
    for record in load_recent():
        name = record["name"]
        if name in seen:
            continue
        directory = resolve_vault_dir(name)
        if directory is None or not os.path.isdir(directory):
            continue
        stored = record.get("dir")
        if stored is not None and stored != directory:
            continue
        seen.add(name)
        listed.append((name, resolve_default_route(name)))
    for name in extra_names:
        if not isinstance(name, str) or name in seen:
            continue
        directory = resolve_vault_dir(name)
        if directory is None or not os.path.isdir(directory):
            continue
        seen.add(name)
        listed.append((name, resolve_default_route(name)))
    return listed


def media_filenames(directory):
    """Every filename present in <vault>/media/."""
    try:
        return sorted(os.listdir(os.path.join(directory, "media")))
    except OSError:
        return []


def media_contains_id(names, entry_id):
    """Downloaded state: some media filename contains the entry id."""
    if not isinstance(entry_id, str) or not entry_id:
        return False
    return any(entry_id in filename for filename in names)


def viewer_entries(raw, version, category, media_names):
    """Rows for one category, in catalog-array order."""
    items = raw.get(category)
    if not isinstance(items, list):
        items = []
    rows = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        entry_id = entry_id if isinstance(entry_id, str) else ""
        removed = False
        if version == CATALOG_VERSION:
            latest, _prior, count = history_tail(entry.get("removed"), version)
            removed = bool(count) and latest is True
        rows.append({
            "id": entry_id,
            "title": entry_title(entry, version),
            "downloaded": media_contains_id(media_names, entry_id),
            "removed": removed,
        })
    return rows


def find_entry(raw, category, entry_id):
    """The entry with this id inside one category, or None.

    The search never leaves `category`, so an id that exists in another
    category of the same vault does not satisfy the lookup.
    """
    items = raw.get(category)
    if not isinstance(items, list):
        return None
    for entry in items:
        if isinstance(entry, dict) and entry.get("id") == entry_id:
            return entry
    return None


def chart_timestamp(key, version):
    """One history key rendered as an ISO 8601 chart timestamp.

    Version 1 stores UNIX-epoch strings; version 2 and 3 already store ISO
    8601 text, which passes through unchanged.
    """
    if version == 1:
        iso = epoch_key_to_iso(key)
        if iso is not None:
            return iso
    return key


def history_points(history, version):
    """Chart points for one tracked field, oldest first.

    Values are carried through exactly as stored: a `likes` history that
    recorded `null` keeps its `null`, and nothing is filtered or replaced.
    """
    return [{"timestamp": chart_timestamp(key, version), "value": history[key]}
            for key in ordered_history_keys(history, version)]


def history_value(entry, field, version):
    """Current value of a tracked field, or None when it has no history."""
    latest, _prior, count = history_tail(entry.get(field), version)
    return latest if count else None


def entry_source_link(name, catalog, version, entry_id):
    """Source-platform URL for one entry, derived the way its version stores it.

    Version 1 keeps only a channel id and the full source is rebuilt from it;
    version 2 and 3 store the source URL itself.
    """
    return digest_source_url(name, catalog, version).rstrip("/") + "/entry/" + entry_id


def asset_match(names, entry_id):
    """The saved filename that belongs to `entry_id`, or None.

    A file counts as the entry's when its name contains the id. An exact name
    and then an `<id>.<ext>` name win over an incidental substring match so the
    choice stays stable when several files mention the same id.
    """
    if not isinstance(entry_id, str) or not entry_id:
        return None
    ordered = sorted(names)
    for filename in ordered:
        if filename == entry_id:
            return filename
    prefix = entry_id + "."
    for filename in ordered:
        if filename.startswith(prefix):
            return filename
    for filename in ordered:
        if entry_id in filename:
            return filename
    return None


def preview_filenames(directory):
    """Every finished preview filename present in <vault>/previews/."""
    try:
        names = os.listdir(os.path.join(directory, "previews"))
    except OSError:
        return []
    return sorted(n for n in names if not _is_partial_name(n))


def vault_media_route(name, filename):
    """Static endpoint serving one saved media file."""
    return ("/vault/" + _url_segment(name) + "/media/" + _url_segment(filename))


def vault_preview_route(name, entry_id):
    """Static endpoint serving the preview image saved for one entry."""
    return ("/vault/" + _url_segment(name) + "/preview/" + _url_segment(entry_id))


def entry_detail(name, directory, raw, version, category, entry_id,
                 timecode=None):
    """View model for one entry detail page, or None when it does not exist."""
    entry = find_entry(raw, category, entry_id)
    if entry is None:
        return None

    removed = False
    if version == CATALOG_VERSION:
        latest, _prior, count = history_tail(entry.get("removed"), version)
        removed = bool(count) and latest is True

    try:
        source_link = entry_source_link(name, raw, version, entry_id)
    except MVaultError:
        # A vault missing its source information still has metadata and
        # history worth showing.
        source_link = None

    description = history_value(entry, "description", version)
    media_file = asset_match(media_filenames(directory), entry_id)
    preview_file = asset_match(preview_filenames(directory), entry_id)

    return {
        "name": name,
        "version": version,
        "category": category,
        "id": entry_id,
        "title": entry_title(entry, version),
        "description": description if isinstance(description, str) else "",
        "published": entry.get("published"),
        "width": entry.get("width"),
        "height": entry.get("height"),
        "source_link": source_link,
        "listing": catalog_route(name, category),
        "removed": removed,
        "media_file": media_file,
        "media_url": vault_media_route(name, media_file) if media_file else None,
        "preview_url": vault_preview_route(name, entry_id) if preview_file else None,
        "charts": {field: history_points(entry.get(field), version)
                   for field in CHART_FIELDS},
        "annotations": entry_annotations(entry),
        "timecode": timecode,
    }


# --------------------------------------------------------------------------
# viewer: static asset serving
# --------------------------------------------------------------------------

MEDIA_MIME_TYPES = {
    "mp4": "video/mp4", "m4v": "video/mp4", "mpeg": "video/mpeg",
    "mpg": "video/mpeg", "webm": "video/webm", "ogv": "video/ogg",
    "mov": "video/quicktime", "mkv": "video/x-matroska",
    "avi": "video/x-msvideo", "flv": "video/x-flv", "3gp": "video/3gpp",
    "ts": "video/mp2t", "mp3": "audio/mpeg", "m4a": "audio/mp4",
    "aac": "audio/aac", "ogg": "audio/ogg", "oga": "audio/ogg",
    "opus": "audio/opus", "flac": "audio/flac", "wav": "audio/wav",
    "weba": "audio/webm", "m3u8": "application/vnd.apple.mpegurl",
}

IMAGE_MIME_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "jpe": "image/jpeg",
    "png": "image/png", "gif": "image/gif", "webp": "image/webp",
    "avif": "image/avif", "bmp": "image/bmp", "tif": "image/tiff",
    "tiff": "image/tiff", "svg": "image/svg+xml", "ico": "image/x-icon",
    "heic": "image/heic", "jfif": "image/jpeg",
}

DEFAULT_MEDIA_MIME = "application/octet-stream"
DEFAULT_IMAGE_MIME = "image/jpeg"


def _extension_of(filename):
    base = os.path.basename(filename)
    _stem, dot, ext = base.rpartition(".")
    return ext.lower() if dot else ""


def _guessed_mime(filename):
    import mimetypes

    guess, _encoding = mimetypes.guess_type(os.path.basename(filename))
    return guess


def sniff_mime(head):
    """MIME type recognised from a file's leading bytes, or None."""
    if not head:
        return None
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image/gif"
    if head.startswith(b"BM"):
        return "image/bmp"
    if head.startswith(b"<?xml") or head.startswith(b"<svg"):
        return "image/svg+xml"
    if head.startswith(b"RIFF") and len(head) >= 12:
        marker = head[8:12]
        if marker == b"WEBP":
            return "image/webp"
        if marker == b"WAVE":
            return "audio/wav"
        if marker == b"AVI ":
            return "video/x-msvideo"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "video/mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if head.startswith(b"OggS"):
        return "audio/ogg"
    if head.startswith(b"ID3") or head.startswith(b"\xff\xfb"):
        return "audio/mpeg"
    if head.startswith(b"fLaC"):
        return "audio/flac"
    return None


def media_mime_type(filename, head=b""):
    """Media MIME type for a saved media file."""
    known = MEDIA_MIME_TYPES.get(_extension_of(filename))
    if known:
        return known
    known = IMAGE_MIME_TYPES.get(_extension_of(filename))
    if known:
        return known
    guess = _guessed_mime(filename)
    if guess and guess != "application/octet-stream":
        return guess
    sniffed = sniff_mime(head)
    if sniffed:
        return sniffed
    return DEFAULT_MEDIA_MIME


def image_mime_type(filename, head=b""):
    """Image MIME type for a saved preview file."""
    known = IMAGE_MIME_TYPES.get(_extension_of(filename))
    if known:
        return known
    guess = _guessed_mime(filename)
    if isinstance(guess, str) and guess.startswith("image/"):
        return guess
    sniffed = sniff_mime(head)
    if sniffed and sniffed.startswith("image/"):
        return sniffed
    return DEFAULT_IMAGE_MIME


def unsafe_segment(segment):
    """True when a request path segment could escape its asset directory."""
    if not isinstance(segment, str) or not segment:
        return True
    if segment in (".", ".."):
        return True
    if "/" in segment or "\\" in segment or "\x00" in segment:
        return True
    return os.path.isabs(segment)


def safe_asset_path(base, segments):
    """Absolute path under `base` for request segments, or None when it escapes."""
    if not segments or any(unsafe_segment(segment) for segment in segments):
        return None
    root = os.path.abspath(base)
    try:
        target = os.path.abspath(os.path.join(root, *segments))
    except (OSError, ValueError):
        return None
    if target == root or not target.startswith(root + os.sep):
        return None
    return target


# --------------------------------------------------------------------------
# viewer: HTML rendering
# --------------------------------------------------------------------------

VIEWER_STYLE = """
:root { color-scheme: light dark; }
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
       margin: 2rem auto; max-width: 60rem; padding: 0 1rem; line-height: 1.5; }
h1 { margin-bottom: 0.25rem; }
.subtitle { color: #666; margin-top: 0; }
form.vault-form { display: flex; gap: 0.5rem; flex-wrap: wrap;
                  margin: 1rem 0 1.5rem; }
form.vault-form input { flex: 1 1 16rem; padding: 0.5rem 0.6rem;
                        border: 1px solid #999; border-radius: 4px; }
form.vault-form button { padding: 0.5rem 1rem; border-radius: 4px;
                         border: 1px solid #666; cursor: pointer; }
nav.categories { margin: 0 0 1rem; display: flex; gap: 0.75rem;
                 flex-wrap: wrap; }
nav.categories a { text-decoration: none; padding: 0.2rem 0.6rem;
                   border: 1px solid #bbb; border-radius: 999px; }
nav.categories a.current { border-color: #333; font-weight: 600; }
ul.entries, ul.recent { list-style: none; padding: 0; margin: 0; }
ul.entries li.entry { border: 1px solid #ddd; border-left-width: 6px;
                      border-radius: 4px; margin-bottom: 0.5rem;
                      padding: 0.6rem 0.8rem; display: flex; gap: 0.6rem;
                      align-items: center; justify-content: space-between; }
li.entry.state-have { border-left-color: #1a7f37; }
li.entry.state-missing { border-left-color: #bbb; opacity: 0.75; }
li.entry.state-removed { border-left-color: #b42318;
                         text-decoration: line-through; font-style: italic; }
.badge { font-size: 0.75rem; text-transform: uppercase; letter-spacing: .04em;
         border-radius: 999px; padding: 0.1rem 0.55rem; border: 1px solid; }
.badge-downloaded { color: #1a7f37; border-color: #1a7f37; }
.badge-missing { color: #6b7280; border-color: #9ca3af; }
.badge-removed { color: #b42318; border-color: #b42318; }
ul.recent li { margin-bottom: 0.35rem; }
p.notfound { border: 1px solid #b42318; color: #b42318; border-radius: 4px;
             padding: 0.6rem 0.8rem; }
p.empty { color: #666; font-style: italic; }
footer { margin-top: 2rem; color: #666; font-size: 0.85rem; }
p.crumbs { margin-bottom: 1rem; }
article.entry-detail p.description { margin: 0 0 1rem; }
dl.metadata { display: grid; grid-template-columns: max-content 1fr;
              gap: 0.35rem 1rem; margin: 0 0 1.5rem; }
dl.metadata dt { font-weight: 600; color: #666; }
dl.metadata dd { margin: 0; }
section.media video.media-player { width: 100%; max-height: 24rem;
                                   background: #000; border-radius: 4px; }
img.preview-image { max-width: 100%; border-radius: 4px; }
section.chart { margin: 1rem 0; }
section.chart h3 { margin: 0 0 0.25rem; font-size: 1rem; }
section.chart figure { margin: 0; }
svg.chart-svg { width: 100%; height: 10rem; border: 1px solid #ddd;
                border-radius: 4px; }
svg.chart-svg polyline.chart-line { stroke: #0969da; stroke-width: 2; }
svg.chart-svg g.chart-dots circle { fill: #0969da; }
figcaption { color: #666; font-size: 0.85rem; margin-top: 0.25rem; }
section.annotations ol.annotation-list { list-style: none; padding: 0;
                                         margin: 0; }
li.annotation { border: 1px solid #ddd; border-left: 6px solid #0969da;
                border-radius: 4px; margin-bottom: 0.5rem;
                padding: 0.5rem 0.75rem; }
li.annotation .annotation-timecode { font-variant-numeric: tabular-nums;
                                     font-weight: 600; }
li.annotation .annotation-title { margin-left: 0.5rem; }
li.annotation p.annotation-body { margin: 0.35rem 0 0; color: #444; }
"""


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def html_page(title, body):
    return ("<!DOCTYPE html>\n"
            "<html lang=\"en\">\n"
            "<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, "
            "initial-scale=1\">\n"
            "<title>" + esc(title) + "</title>\n"
            "<style>" + VIEWER_STYLE + "</style>\n"
            "</head>\n<body>\n" + body + "\n</body>\n</html>\n")


def render_landing(recent, missing=None):
    parts = ["<h1>mvault viewer</h1>",
             "<p class=\"subtitle\">Open a local vault by name.</p>"]
    if missing:
        parts.append("<p class=\"notfound\" id=\"vault-not-found\" "
                     "role=\"alert\" data-missing=\"" + esc(missing) + "\">"
                     "Vault &quot;" + esc(missing) + "&quot; not found.</p>")
    parts.append(
        "<form class=\"vault-form\" method=\"post\" action=\"/\">\n"
        "<label class=\"visually-hidden\" for=\"catalog\">Vault name</label>\n"
        "<input type=\"text\" id=\"catalog\" name=\"catalog\" "
        "placeholder=\"vault name\" aria-label=\"Vault name\" autofocus>\n"
        "<button type=\"submit\">Open vault</button>\n"
        "</form>")
    parts.append("<h2>Recent vaults</h2>")
    if recent:
        rows = ["<ul class=\"recent\" id=\"recent-vaults\">"]
        for name, route in recent:
            rows.append("<li class=\"recent-vault\" data-vault=\"" + esc(name)
                        + "\"><a href=\"" + esc(route) + "\">" + esc(name)
                        + "</a></li>")
        rows.append("</ul>")
        parts.append("\n".join(rows))
    else:
        parts.append("<ul class=\"recent\" id=\"recent-vaults\"></ul>")
        parts.append("<p class=\"empty\">No vaults visited yet.</p>")
    return html_page("mvault viewer", "\n".join(parts))


def render_listing(name, version, category, rows):
    parts = ["<p><a href=\"/\">&larr; All vaults</a></p>",
             "<h1>" + esc(name) + "</h1>",
             "<p class=\"subtitle\">catalog version " + esc(version)
             + " &middot; " + esc(category) + "</p>"]

    nav = ["<nav class=\"categories\">"]
    for option in categories_for_version(version):
        css = "current" if option == category else ""
        nav.append("<a class=\"" + css + "\" href=\""
                   + esc(catalog_route(name, option)) + "\">" + esc(option)
                   + "</a>")
    nav.append("</nav>")
    parts.append("\n".join(nav))

    if not rows:
        parts.append("<p class=\"empty\">No entries in this category.</p>")
        return html_page(name + " / " + category, "\n".join(parts))

    listing = ["<ul class=\"entries\">"]
    for row in rows:
        classes = ["entry"]
        classes.append("state-have" if row["downloaded"] else "state-missing")
        if row["removed"]:
            classes.append("state-removed")
        badges = []
        if row["downloaded"]:
            badges.append("<span class=\"badge badge-downloaded\">"
                          "Downloaded</span>")
        else:
            badges.append("<span class=\"badge badge-missing\">Missing</span>")
        if row["removed"]:
            badges.append("<span class=\"badge badge-removed\">Removed</span>")
        listing.append(
            "<li class=\"" + " ".join(classes) + "\" id=\"entry-"
            + esc(row["id"]) + "\" data-id=\"" + esc(row["id"])
            + "\" data-downloaded=\"" + ("true" if row["downloaded"] else "false")
            + "\" data-removed=\"" + ("true" if row["removed"] else "false")
            + "\">"
            + "<a class=\"entry-link\" href=\""
            + esc(catalog_route(name, category, row["id"])) + "\">"
            + esc(row["title"]) + "</a>"
            + "<span class=\"badges\">" + "".join(badges) + "</span>"
            + "</li>")
    listing.append("</ul>")
    parts.append("\n".join(listing))
    parts.append("<footer>" + str(len(rows)) + " entries in catalog order."
                 "</footer>")
    return html_page(name + " / " + category, "\n".join(parts))


def chart_payload(detail):
    """Machine-readable chart data embedded in the detail page.

    Points keep the timestamp/value pairing exactly as recorded, oldest first,
    with timestamps already normalized to ISO 8601 for every catalog version.
    """
    payload = {
        "vault": detail["name"],
        "category": detail["category"],
        "id": detail["id"],
        "version": detail["version"],
        "fields": list(CHART_FIELDS),
    }
    for field in CHART_FIELDS:
        payload[field] = detail["charts"].get(field, [])
    return payload


def embedded_json(payload, element_id):
    """A JSON payload embedded in HTML so a machine can read it back."""
    text = json.dumps(payload, ensure_ascii=False)
    # "<" cannot appear raw inside a script element without risking an early
    # close; the escape is still ordinary JSON and parses back unchanged.
    text = text.replace("<", "\\u003c")
    return ("<script type=\"application/json\" id=\"" + esc(element_id)
            + "\">" + text + "</script>")


def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


CHART_WIDTH = 640
CHART_HEIGHT = 180
CHART_PAD = 24


def chart_svg(points):
    """A simple line chart for one field, or "" when there is nothing to plot."""
    plotted = [(index, point["value"]) for index, point in enumerate(points)
               if _numeric(point["value"])]
    if len(points) < 2 or len(plotted) < 2:
        return ""
    values = [value for _index, value in plotted]
    low, high = min(values), max(values)
    span = (high - low) or 1
    steps = len(points) - 1
    inner_w = CHART_WIDTH - 2 * CHART_PAD
    inner_h = CHART_HEIGHT - 2 * CHART_PAD

    coords = []
    for index, value in plotted:
        x = CHART_PAD + (inner_w * index / float(steps))
        y = CHART_HEIGHT - CHART_PAD - (inner_h * (value - low) / float(span))
        coords.append((x, y))

    line = " ".join("%.2f,%.2f" % point for point in coords)
    dots = "".join("<circle cx=\"%.2f\" cy=\"%.2f\" r=\"3\"></circle>" % point
                   for point in coords)
    return ("<svg class=\"chart-svg\" viewBox=\"0 0 %d %d\" role=\"img\" "
            "preserveAspectRatio=\"none\">"
            "<polyline class=\"chart-line\" fill=\"none\" points=\"%s\"></polyline>"
            "<g class=\"chart-dots\">%s</g>"
            "</svg>" % (CHART_WIDTH, CHART_HEIGHT, line, dots))


def render_chart(field, points):
    """One chart section: the drawing when it has a shape, a note when not."""
    svg = chart_svg(points)
    header = ("<h3>" + esc(field.title()) + "</h3>")
    attrs = ("data-field=\"" + esc(field) + "\" data-points=\""
             + str(len(points)) + "\"")
    if not svg:
        return ("<section class=\"chart chart-empty\" id=\"chart-" + esc(field)
                + "\" " + attrs + ">" + header
                + "<p class=\"empty\">Not enough recorded history to chart "
                + esc(field) + ".</p></section>")
    latest = points[-1]["value"]
    caption = ("<figcaption>" + str(len(points)) + " recorded values, oldest "
               "first &middot; latest "
               + esc("null" if latest is None else latest) + "</figcaption>")
    return ("<section class=\"chart\" id=\"chart-" + esc(field) + "\" " + attrs
            + ">" + header + "<figure>" + svg + caption
            + "</figure></section>")


def annotation_payload(detail):
    """Machine-readable annotation data embedded in the detail page.

    Annotations appear in the order `catalog.json` stores them, which is the
    order they were created in.
    """
    return {
        "vault": detail["name"],
        "category": detail["category"],
        "id": detail["id"],
        "timecode": detail["timecode"],
        "annotations": [
            {"id": item.get("id"), "timecode": item.get("timecode"),
             "title": item.get("title"), "body": item.get("body")}
            for item in detail["annotations"]
        ],
    }


def render_annotation(detail, annotation):
    """One stored annotation, rendered so a reader can see all of it."""
    annotation_id = annotation.get("id")
    seconds = annotation.get("timecode")
    title = annotation.get("title")
    body = annotation.get("body")
    seek = catalog_route(detail["name"], detail["category"], detail["id"])
    if _is_int(seconds):
        seek += "?timecode=" + str(seconds)
    parts = [
        "<li class=\"annotation\" id=\"annotation-" + esc(annotation_id)
        + "\" data-annotation-id=\"" + esc(annotation_id)
        + "\" data-timecode=\"" + esc(seconds) + "\">",
        "<a class=\"annotation-seek\" href=\"" + esc(seek)
        + "\"><span class=\"annotation-timecode\" data-seconds=\""
        + esc(seconds) + "\">" + esc(format_timecode(seconds))
        + "</span></a>",
        "<span class=\"annotation-title\">" + esc(title) + "</span>",
        "<span class=\"annotation-seconds\"> &middot; " + esc(seconds)
        + "s</span>",
    ]
    if body is not None:
        parts.append("<p class=\"annotation-body\">" + esc(body) + "</p>")
    parts.append("</li>")
    return "".join(parts)


def render_annotations(detail):
    """The annotation section: every stored annotation, in creation order."""
    items = detail["annotations"]
    parts = ["<section class=\"annotations\" id=\"annotations\" "
             "data-count=\"" + str(len(items)) + "\">",
             "<h2>Annotations</h2>",
             embedded_json(annotation_payload(detail), "annotation-data")]
    if not items:
        parts.append("<p class=\"empty\" id=\"annotations-empty\">No "
                     "annotations have been added to this entry yet.</p>")
    else:
        parts.append("<ol class=\"annotation-list\">")
        parts.extend(render_annotation(detail, item) for item in items)
        parts.append("</ol>")
    parts.append("</section>")
    return "\n".join(parts)


# The detail page seeks the player to the ?timecode= value so a link produced
# by creating an annotation lands on the moment it describes.
SEEK_SCRIPT = """
<script>
(function () {
  var article = document.getElementById("entry-detail");
  var player = document.getElementById("media-player");
  if (!article || !player) { return; }
  var raw = article.getAttribute("data-timecode");
  if (raw === null || raw === "") { return; }
  var at = parseInt(raw, 10);
  if (isNaN(at) || at < 0) { return; }
  var seek = function () { try { player.currentTime = at; } catch (e) {} };
  if (player.readyState > 0) { seek(); }
  player.addEventListener("loadedmetadata", seek);
})();
</script>
"""


def render_detail(detail):
    """The entry detail page: metadata, media, annotations, and chart data."""
    name = detail["name"]
    category = detail["category"]
    entry_id = detail["id"]
    published = detail["published"]
    published_text = "" if published is None else str(published)

    parts = [
        "<p class=\"crumbs\"><a href=\"/\">&larr; All vaults</a> &middot; "
        "<a class=\"back-link\" id=\"back-to-listing\" href=\""
        + esc(detail["listing"]) + "\">&larr; Back to " + esc(name) + " / "
        + esc(category) + "</a></p>",
        "<article class=\"entry-detail\" id=\"entry-detail\" data-vault=\""
        + esc(name) + "\" data-category=\"" + esc(category) + "\" data-id=\""
        + esc(entry_id) + "\" data-version=\"" + esc(detail["version"])
        + "\" data-downloaded=\""
        + ("true" if detail["media_file"] else "false") + "\" data-removed=\""
        + ("true" if detail["removed"] else "false") + "\" data-timecode=\""
        + ("" if detail["timecode"] is None else esc(detail["timecode"]))
        + "\" data-annotations=\"" + str(len(detail["annotations"]))
        + "\">",
        "<h1 class=\"entry-title\" id=\"entry-title\">"
        + esc(detail["title"]) + "</h1>",
        "<p class=\"subtitle\">" + esc(name) + " &middot; " + esc(category)
        + " &middot; " + esc(entry_id) + " &middot; catalog version "
        + esc(detail["version"]) + "</p>",
    ]
    if detail["removed"]:
        parts.append("<p><span class=\"badge badge-removed\" "
                     "id=\"entry-removed\">Removed</span></p>")

    parts.append("<p class=\"description\" id=\"entry-description\">"
                 + esc(detail["description"]) + "</p>")

    published_iso = normalize_published(published_text)
    dimensions = ""
    if detail["width"] is not None and detail["height"] is not None:
        dimensions = "%s×%s" % (detail["width"], detail["height"])

    meta = ["<dl class=\"metadata\">",
            "<dt>Published</dt><dd class=\"published\" id=\"entry-published\" "
            "data-published=\"" + esc(published_text)
            + "\" data-published-iso=\"" + esc(published_iso) + "\">"
            + esc(published_text) + "</dd>",
            "<dt>Dimensions</dt><dd class=\"dimensions\" "
            "id=\"entry-dimensions\" data-width=\"" + esc(detail["width"])
            + "\" data-height=\"" + esc(detail["height"])
            + "\" data-dimensions=\"" + esc(dimensions) + "\">"
            + esc(detail["width"]) + " × " + esc(detail["height"])
            + "</dd>",
            "<dt>Source</dt><dd>" + (
                "<a class=\"source-link\" id=\"source-link\" "
                "rel=\"noreferrer\" href=\"" + esc(detail["source_link"])
                + "\">" + esc(detail["source_link"]) + "</a>"
                if detail["source_link"] else
                "<span class=\"empty\">unavailable</span>") + "</dd>",
            "</dl>"]
    parts.append("\n".join(meta))

    media = ["<section class=\"media\" id=\"media\">", "<h2>Media</h2>"]
    if detail["media_url"]:
        poster = ""
        if detail["preview_url"]:
            poster = " poster=\"" + esc(detail["preview_url"]) + "\""
        # A media fragment starts playback at the requested moment even
        # before the seek script runs.
        source = detail["media_url"]
        if detail["timecode"] is not None:
            source += "#t=" + str(detail["timecode"])
        media.append("<video class=\"media-player\" id=\"media-player\" "
                     "controls preload=\"none\"" + poster
                     + " src=\"" + esc(source)
                     + "\" data-media-file=\"" + esc(detail["media_file"])
                     + "\"></video>")
        media.append("<p><a class=\"media-link\" id=\"media-link\" href=\""
                     + esc(detail["media_url"]) + "\">"
                     + esc(detail["media_file"]) + "</a></p>")
    else:
        media.append("<p class=\"empty\" id=\"media-missing\">No media file "
                     "has been downloaded for this entry yet.</p>")
    if detail["preview_url"]:
        media.append("<p><img class=\"preview-image\" id=\"preview-image\" "
                     "src=\"" + esc(detail["preview_url"]) + "\" alt=\"Preview "
                     "image for " + esc(entry_id) + "\"></p>")
    media.append("</section>")
    parts.append("\n".join(media))

    charts = ["<section class=\"charts\" id=\"charts\">",
              "<h2>Tracked values</h2>",
              embedded_json(chart_payload(detail), "chart-data")]
    for field in CHART_FIELDS:
        charts.append(render_chart(field, detail["charts"].get(field, [])))
    charts.append("</section>")
    parts.append("\n".join(charts))

    parts.append(render_annotations(detail))

    parts.append("</article>")
    parts.append(SEEK_SCRIPT.strip())
    return html_page("%s / %s / %s" % (name, category, detail["title"]),
                     "\n".join(parts))


def render_error(status, message):
    return html_page("mvault viewer: error",
                     "<h1>" + esc(status) + "</h1>\n<p>" + esc(message)
                     + "</p>\n<p><a href=\"/\">&larr; All vaults</a></p>")


# --------------------------------------------------------------------------
# viewer: HTTP server
# --------------------------------------------------------------------------

def _cookie_names(header):
    """Vault names remembered in the browser's own copy of the recent list."""
    if not header:
        return []
    import http.cookies

    jar = http.cookies.SimpleCookie()
    try:
        jar.load(header)
    except Exception:  # noqa: BLE001 - a malformed cookie is simply ignored
        return []
    morsel = jar.get(RECENT_COOKIE)
    if morsel is None:
        return []
    try:
        data = json.loads(unquote(morsel.value))
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, str) and item]


def make_viewer_handler():
    from http.server import BaseHTTPRequestHandler

    class ViewerHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "mvault-viewer/1.0"

        # -- low level replies ------------------------------------------
        def _send(self, status, body=b"", content_type="text/html; charset=utf-8",
                  headers=()):
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for key, value in headers:
                    self.send_header(key, value)
                self.end_headers()
                if self.command != "HEAD" and body:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _html(self, status, text, headers=()):
            self._send(status, text.encode("utf-8"), headers=headers)

        def _redirect(self, location, status=302, headers=()):
            body = ("<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                    "<title>Redirecting</title></head><body>"
                    "<p><a href=\"" + esc(location) + "\">"
                    + esc(location) + "</a></p></body></html>\n"
                    ).encode("utf-8")
            self._send(status, body,
                       headers=(("Location", location),) + tuple(headers))

        def _error(self, status, message):
            self._html(status, render_error("HTTP %d" % status, message))

        # -- cookies ----------------------------------------------------
        def _recent_cookie(self, names):
            value = quote(json.dumps(names[:RECENT_LIMIT]), safe="")
            return (RECENT_COOKIE + "=" + value + "; Path=/; Max-Age="
                    + str(COOKIE_MAX_AGE) + "; SameSite=Lax")

        def _remember(self, name, directory):
            names = remember_recent(name, directory)
            return (("Set-Cookie", self._recent_cookie(names)),)

        # -- request entry points ---------------------------------------
        def do_GET(self):
            self._handle()

        def do_HEAD(self):
            self._handle()

        def do_POST(self):
            self._handle()

        def do_PATCH(self):
            self._handle()

        def do_DELETE(self):
            self._handle()

        def _read_body(self):
            """The request body, drained so the connection stays usable."""
            length = self.headers.get("Content-Length")
            try:
                size = int(length) if length else 0
            except ValueError:
                size = 0
            if size <= 0:
                return b""
            try:
                return self.rfile.read(size)
            except (OSError, ValueError):
                return b""

        def _handle(self):
            body = b""
            if self.command in ANNOTATION_METHODS:
                try:
                    body = self._read_body()
                except Exception:  # noqa: BLE001
                    body = b""
            try:
                if self.command in ("PATCH", "DELETE"):
                    self._route_annotation(self._path_parts(), body)
                elif self.command == "POST":
                    self._route_post(body)
                else:
                    self._route_get()
            except AnnotationError as exc:
                try:
                    self._error(exc.status, str(exc))
                except Exception:  # noqa: BLE001
                    pass
            except Exception:  # noqa: BLE001 - never leak a traceback
                try:
                    self._error(400, "the viewer could not handle this request")
                except Exception:  # noqa: BLE001
                    pass

        # -- routing ----------------------------------------------------
        def _path_parts(self):
            path = urlparse(self.path).path
            return [unquote(part) for part in path.split("/") if part != ""]

        def _route_post(self, raw=b""):
            parts = self._path_parts()
            if parts:
                self._route_annotation(parts, raw)
                return
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
            fields = parse_qs(text, keep_blank_values=True)
            values = fields.get("catalog") or []
            value = values[0].strip() if values else ""
            if not value:
                self._redirect("/", 303)
                return
            self._redirect(catalog_route(value), 303)

        def _route_annotation(self, parts, raw):
            """POST / PATCH / DELETE on /catalog/<name>/<category>/<id>."""
            if len(parts) != 4 or parts[0] != "catalog":
                self._error(404, "unknown path")
                return
            name, category, entry_id = parts[1], parts[2], parts[3]
            try:
                directory, catalog, version = viewer_load(name)
            except MVaultError as exc:
                self._error(404, str(exc))
                return
            payload = parse_annotation_body(raw)
            target, annotation = apply_annotation(
                name, directory, catalog, version, category, entry_id,
                self.command, payload)
            location = catalog_route(name, target, entry_id)
            if self.command == "POST":
                location += "?timecode=" + str(annotation["timecode"])
            self._redirect(location, 303)

        def _query_timecode(self):
            """The ?timecode= seek position of this request, when usable."""
            values = parse_qs(urlparse(self.path).query).get("timecode") or []
            if not values:
                return None
            try:
                return parse_timecode(values[0])
            except MVaultError:
                return None

        def _route_get(self):
            parts = self._path_parts()
            if not parts:
                self._landing()
                return
            if parts[0] == "favicon.ico":
                self._send(204, b"", content_type="image/x-icon")
                return
            if parts[0] == "vault":
                self._vault_asset(parts)
                return
            if parts[0] != "catalog":
                self._error(404, "unknown path")
                return
            if len(parts) == 1 or not parts[1]:
                self._redirect("/")
                return
            if len(parts) > 4:
                self._error(404, "unknown path")
                return

            name = parts[1]
            try:
                directory, raw, version = viewer_load(name)
            except MVaultError:
                self._vault_missing(name)
                return

            cookie = self._remember(name, directory)
            default = default_category_for_version(version)
            if len(parts) == 2:
                self._redirect(catalog_route(name, default), headers=cookie)
                return

            category = parts[2]
            if category not in categories_for_version(version):
                self._redirect(catalog_route(name, default), headers=cookie)
                return

            if len(parts) == 4:
                detail = entry_detail(name, directory, raw, version, category,
                                      parts[3], self._query_timecode())
                if detail is None:
                    self._error(404, "no entry %r in category %r of vault %r"
                                     % (parts[3], category, name))
                    return
                self._html(200, render_detail(detail), headers=cookie)
                return

            rows = viewer_entries(raw, version, category,
                                  media_filenames(directory))
            self._html(200, render_listing(name, version, category, rows),
                       headers=cookie)

        def _vault_missing(self, name):
            """A route named a vault that cannot be opened from here."""
            _VIEWER_STATE["missing"] = name
            self._redirect("/", headers=(
                ("Set-Cookie", NOTFOUND_COOKIE + "=" + quote(name, safe="")
                 + "; Path=/; Max-Age=60; SameSite=Lax"),))

        def _serve_file(self, path, image=False):
            """Send one stored asset with a MIME type that suits its content."""
            try:
                with open(path, "rb") as handle:
                    body = handle.read()
            except OSError:
                self._error(404, "that file is not available")
                return
            head = body[:16]
            filename = os.path.basename(path)
            content_type = (image_mime_type(filename, head) if image
                            else media_mime_type(filename, head))
            self._send(200, body, content_type=content_type)

        def _vault_asset(self, parts):
            """/vault/<name>/media/<file> and /vault/<name>/preview/<id>."""
            if len(parts) < 4 or parts[2] not in ("media", "preview"):
                self._error(404, "unknown path")
                return
            name, kind, rest = parts[1], parts[2], parts[3:]
            if unsafe_segment(name):
                self._error(403, "that path is not allowed")
                return
            try:
                directory, _raw, _version = viewer_load(name)
            except MVaultError:
                self._vault_missing(name)
                return

            if any(unsafe_segment(segment) for segment in rest):
                self._error(403, "that path is not allowed")
                return

            if kind == "media":
                path = safe_asset_path(os.path.join(directory, "media"), rest)
                if path is None:
                    self._error(403, "that path is not allowed")
                    return
                if not os.path.isfile(path):
                    self._error(404, "no such media file")
                    return
                self._serve_file(path)
                return

            if len(rest) != 1:
                self._error(404, "unknown path")
                return
            filename = asset_match(preview_filenames(directory), rest[0])
            if filename is None:
                self._error(404, "no preview image for %r" % rest[0])
                return
            path = safe_asset_path(os.path.join(directory, "previews"),
                                   [filename])
            if path is None or not os.path.isfile(path):
                self._error(404, "no preview image for %r" % rest[0])
                return
            self._serve_file(path, image=True)

        def _landing(self):
            missing = _VIEWER_STATE.get("missing")
            _VIEWER_STATE["missing"] = None
            headers = ()
            if missing is None:
                cookie = self.headers.get("Cookie")
                import http.cookies

                jar = http.cookies.SimpleCookie()
                try:
                    jar.load(cookie or "")
                except Exception:  # noqa: BLE001
                    jar = http.cookies.SimpleCookie()
                morsel = jar.get(NOTFOUND_COOKIE)
                if morsel is not None and morsel.value:
                    missing = unquote(morsel.value)
            if missing:
                headers = (("Set-Cookie", NOTFOUND_COOKIE + "=; Path=/; "
                                          "Max-Age=0; SameSite=Lax"),)
            recent = recent_for_display(_cookie_names(self.headers.get("Cookie")))
            self._html(200, render_landing(recent, missing), headers=headers)

        def log_message(self, fmt, *args):
            sys.stderr.write("mvault viewer: %s - %s\n"
                             % (self.address_string(), fmt % args))

    return ViewerHandler


def make_viewer_server(host, port):
    from http.server import ThreadingHTTPServer

    handler = make_viewer_handler()

    class ViewerServer(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    try:
        return ViewerServer((host, int(port)), handler)
    except OSError as exc:
        raise MVaultError("cannot serve on %s:%s (%s)" % (host, port, exc))


def _browsable_host(host):
    if host in ("", "0.0.0.0", "::", "*"):
        return VIEWER_HOST
    return host


def open_browser(url):
    """Open the system browser without blocking the server loop."""
    import threading

    def target():
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - a headless host simply has none
            pass

    threading.Thread(target=target, daemon=True).start()


def cmd_serve(name=None, host=None, port=None):
    host = VIEWER_HOST if host is None else host
    port = VIEWER_PORT if port is None else port
    server = make_viewer_server(host, port)
    bound_port = server.server_address[1]
    origin = viewer_origin(_browsable_host(host), bound_port)
    target = origin + "/"
    if name:
        target = origin + resolve_default_route(name)
    print("Serving mvault viewer at %s/" % origin)
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


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

COMMANDS = ("init", "sync", "migrate", "digest", "serve")

_NON_NEGATIVE_RE = re.compile(r"^\d+$")


def limit_value(text):
    """argparse type for a non-negative integer category limit."""
    if not _NON_NEGATIVE_RE.match(text.strip()):
        raise argparse.ArgumentTypeError(
            "%r is not a non-negative integer" % text)
    return int(text.strip())


def port_value(text):
    """argparse type for a TCP port (0 asks the OS for a free one)."""
    stripped = text.strip()
    if not _NON_NEGATIVE_RE.match(stripped) or int(stripped) > 65535:
        raise argparse.ArgumentTypeError("%r is not a valid port number" % text)
    return int(stripped)


def host_value(text):
    """argparse type for a bind host / viewer-link host."""
    stripped = text.strip()
    if not stripped:
        raise argparse.ArgumentTypeError("--host requires a non-empty host")
    return stripped


def add_viewer_link_options(parser):
    """Options controlling the host/port used in appended viewer links."""
    parser.add_argument(
        "--host", type=host_value, default=None, metavar="HOST",
        help="host used in viewer links (default %s)" % VIEWER_HOST)
    parser.add_argument(
        "--port", type=port_value, default=None, metavar="PORT",
        help="port used in viewer links (default %d)" % VIEWER_PORT)


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
    add_viewer_link_options(sync_parser)

    migrate_parser = subparsers.add_parser(
        "migrate", help="convert a legacy vault catalog to the native format")
    migrate_parser.add_argument("name", help="vault directory name")

    digest_parser = subparsers.add_parser(
        "digest", help="summarize notable changes recorded in a vault")
    digest_parser.add_argument("name", help="vault directory name")
    add_viewer_link_options(digest_parser)

    serve_parser = subparsers.add_parser(
        "serve", help="serve the local browser viewer for vaults")
    serve_parser.add_argument(
        "name", nargs="?", default=None,
        help="vault to open in the browser (optional)")
    serve_parser.add_argument(
        "--host", type=host_value, default=VIEWER_HOST, metavar="HOST",
        help="bind host (default %s)" % VIEWER_HOST)
    serve_parser.add_argument(
        "--port", type=port_value, default=VIEWER_PORT, metavar="PORT",
        help="bind port (default %d)" % VIEWER_PORT)

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
                            fmt=args.format, host=args.host, port=args.port)
        if args.command == "migrate":
            return cmd_migrate(args.name)
        if args.command == "digest":
            return cmd_digest(args.name, host=args.host, port=args.port)
        if args.command == "serve":
            return cmd_serve(args.name, host=args.host, port=args.port)
    except MVaultError as exc:
        print("mvault: error: %s" % exc, file=sys.stderr)
        return 1
    except OSError as exc:
        print("mvault: error: %s" % exc, file=sys.stderr)
        return 1
    return _usage_error(parser)


if __name__ == "__main__":
    sys.exit(main())
