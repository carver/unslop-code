#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Creates local vaults for media-platform metadata and records tracked-field
history by sync timestamp.

Usage:
    python mvault.py init <name> <url>
    python mvault.py sync <name> [options]
    python mvault.py migrate <name>
    python mvault.py digest <name>
    python mvault.py serve [<name>] [--host=<host>] [--port=<port>]
"""
import argparse
import html
import http.cookies
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
LEGACY_SOURCE_PREFIX = "https://media.example.com/channel/"
CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"
CATEGORIES = ("episodes", "streams", "clips")
HISTORY_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = HISTORY_FIELDS + ("removed",)
STATIC_FIELDS = ("id", "published", "width", "height")
EPOCH_KEY = re.compile(r"^-?\d+$")
NON_NEGATIVE_INT = re.compile(r"^\d+$")
DT_FORMAT = "%Y-%m-%dT%H:%M:%S"
FETCH_TIMEOUT = 30

MEDIA_DIR = "media"
PREVIEW_DIR = "previews"
PART_SUFFIX = ".part"
DOWNLOAD_ATTEMPTS = 3
DEFAULT_EXTENSION = "bin"
# 4xx statuses that a retry can still fix; every other 4xx is permanent.
RETRYABLE_STATUSES = (408, 425, 429)
# `Content-Type` -> file extension, pinned so the answer does not drift with
# the interpreter's mime database (see AMBIGUITIES T22).
CONTENT_TYPE_EXTENSIONS = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
    "video/x-matroska": "mkv",
    "video/mpeg": "mpeg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "application/octet-stream": "bin",
}

# --------------------------------------------------------------------------
# viewer constants
# --------------------------------------------------------------------------

DEFAULT_VIEWER_HOST = "127.0.0.1"
DEFAULT_VIEWER_PORT = 8840
VIEWER_SCHEME = "http"
# A v1 catalog keeps every entry in one `entries` array; v2 and v3 use the
# three named categories.
V1_CATEGORY = "entries"
V1_CATEGORIES = (V1_CATEGORY,)
DEFAULT_CATEGORY = "episodes"
RECENT_COOKIE = "mvault_recent"
RECENT_COOKIE_MAX_AGE = 60 * 60 * 24 * 365
RECENT_LIMIT = 20
REDIRECT_STATUS = 302
REDIRECT_AFTER_POST_STATUS = 303

# Static-file routes: `/vault/<name>/media/<file>` and
# `/vault/<name>/preview/<id>`.
VAULT_ROUTE = "vault"
MEDIA_ROUTE = "media"
PREVIEW_ROUTE = "preview"
DEFAULT_MEDIA_TYPE = "application/octet-stream"
DEFAULT_IMAGE_TYPE = "image/jpeg"

# The two tracked fields the detail page charts.
CHART_FIELDS = ("views", "likes")
CHART_SCRIPT_ID = "chart-data"
SOURCE_ENTRY_PATH = "/entry/"

DIGEST_REMOVALS = "Removals"
DIGEST_ADDITIONS = "Additions"
DIGEST_UPDATES = "Field updates"
DIGEST_GROUPS = (DIGEST_REMOVALS, DIGEST_ADDITIONS, DIGEST_UPDATES)
DIGEST_V1_GROUP = "Entries"
NO_CHANGES_TEXT = "No notable changes found."


class VaultError(Exception):
    """A vault is missing, invalid, or already exists."""


class SourceError(Exception):
    """Source metadata could not be fetched or is malformed."""


class PermanentDownloadError(Exception):
    """The asset is gone for good; retrying cannot help."""


class TransientDownloadError(Exception):
    """The asset might come back; the request is worth retrying."""


def warn(message):
    print("warning: %s" % message, file=sys.stderr)


# --------------------------------------------------------------------------
# datetime helpers
# --------------------------------------------------------------------------

def is_int(value):
    """JSON integer: booleans are not integers even though bool subclasses int."""
    return isinstance(value, int) and not isinstance(value, bool)


def format_dt(moment):
    return moment.strftime(DT_FORMAT)


def parse_dt(text):
    """Parse an ISO 8601 datetime/date string, or return None."""
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    if not candidate:
        return None
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1]
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    # The stored text never carries a timezone suffix.
    return parsed.replace(tzinfo=None, microsecond=0)


def normalize_published(text):
    """Normalize source `published` text to YYYY-MM-DDTHH:MM:SS.

    Date-only values gain a 00:00:00 time component; timezone suffixes are
    dropped. Text that is not ISO 8601 is kept verbatim.
    """
    parsed = parse_dt(text)
    if parsed is None:
        return text
    return format_dt(parsed)


def history_sort_key(key):
    """Chronological order for a history key, tolerating odd text."""
    parsed = parse_dt(key)
    if parsed is None:
        return (1, datetime.min, key)
    return (0, parsed, key)


def latest_key(history):
    if not history:
        return None
    return max(history, key=history_sort_key)


def current_value(history):
    key = latest_key(history)
    return None if key is None else history[key]


# --------------------------------------------------------------------------
# source fetching / validation
# --------------------------------------------------------------------------

def fetch_source(url):
    """HTTP GET the source URL and return the parsed JSON object."""
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise SourceError("HTTP %s from %s" % (exc.code, url))
    except Exception as exc:  # network failures, bad URLs, timeouts
        raise SourceError("could not fetch %s: %s" % (url, exc))

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise SourceError("invalid JSON from %s: %s" % (url, exc))

    if not isinstance(data, dict):
        raise SourceError("source response from %s is not a JSON object" % url)

    result = {}
    for category in CATEGORIES:
        if category not in data:
            raise SourceError("source response is missing '%s'" % category)
        items = data[category]
        if not isinstance(items, list):
            raise SourceError("source field '%s' is not an array" % category)
        result[category] = [validate_source_entry(item, category) for item in items]
    return result


def validate_source_entry(item, category):
    """Check the nine required fields and their types."""
    if not isinstance(item, dict):
        raise SourceError("source entry in '%s' is not an object" % category)

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
        if field not in item:
            raise SourceError(
                "source entry in '%s' is missing required field '%s'"
                % (category, field)
            )
        if not check(item[field]):
            raise SourceError(
                "source entry '%s' in '%s' has wrong type for '%s' (expected %s)"
                % (item.get("id"), category, field, expected)
            )
    return item


# --------------------------------------------------------------------------
# catalog load / validate / save
# --------------------------------------------------------------------------

def catalog_path(vault_dir):
    return os.path.join(vault_dir, CATALOG_NAME)


def backup_path(vault_dir):
    return os.path.join(vault_dir, BACKUP_NAME)


def read_catalog_file(name):
    """Read `<name>/catalog.json` as raw JSON, whatever version it declares."""
    vault_dir = name
    if not os.path.isdir(vault_dir):
        raise VaultError("vault '%s' does not exist" % name)
    path = catalog_path(vault_dir)
    if not os.path.isfile(path):
        raise VaultError("vault '%s' is invalid: missing %s" % (name, CATALOG_NAME))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            catalog = json.load(handle)
    except Exception as exc:
        raise VaultError("vault '%s' is invalid: unreadable %s (%s)"
                         % (name, CATALOG_NAME, exc))
    if not isinstance(catalog, dict):
        raise VaultError("vault '%s' is invalid: catalog is not an object" % name)
    return catalog


def catalog_version(name, catalog):
    """The declared catalog version, validated against the supported set."""
    if "version" not in catalog:
        raise VaultError(
            "vault '%s' is invalid: catalog is missing the 'version' field" % name
        )
    version = catalog["version"]
    if not is_int(version):
        raise VaultError(
            "vault '%s' is invalid: catalog 'version' %r must be an integer "
            "(supported versions: %s)"
            % (name, version, ", ".join(str(v) for v in SUPPORTED_VERSIONS))
        )
    if version not in SUPPORTED_VERSIONS:
        raise VaultError(
            "vault '%s' has unsupported catalog version %d "
            "(supported versions: %s)"
            % (name, version, ", ".join(str(v) for v in SUPPORTED_VERSIONS))
        )
    return version


def validate_native(name, catalog):
    """Root-schema check for a version 3 catalog."""
    if not isinstance(catalog.get("source"), str):
        raise VaultError("vault '%s' is invalid: missing source URL" % name)
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise VaultError(
                "vault '%s' is invalid: '%s' must be an array" % (name, category)
            )
    return catalog


# --------------------------------------------------------------------------
# legacy (version 1 / version 2) migration
# --------------------------------------------------------------------------

def legacy_source_url(source_id):
    """The deterministic source URL of a version 1 vault."""
    return LEGACY_SOURCE_PREFIX + source_id


def malformed(name, detail):
    raise VaultError("vault '%s' has malformed legacy entry data: %s"
                     % (name, detail))


def convert_epoch_key(name, eid, field, key):
    """`"1718444400"` -> `"2024-06-15T09:40:00"` (UTC)."""
    if not isinstance(key, str) or not EPOCH_KEY.match(key.strip()):
        malformed(name, "entry '%s' field '%s' has a non-epoch history key %r"
                        % (eid, field, key))
    try:
        moment = datetime.fromtimestamp(int(key.strip()), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        malformed(name, "entry '%s' field '%s' has an out-of-range epoch key %r"
                        % (eid, field, key))
    return format_dt(moment.replace(tzinfo=None))


def check_history_value(name, eid, field, value):
    if field in ("title", "description", "preview"):
        if not isinstance(value, str):
            malformed(name, "entry '%s' field '%s' has a non-string value %r"
                            % (eid, field, value))
    elif field == "views":
        if not is_int(value):
            malformed(name, "entry '%s' field '%s' has a non-integer value %r"
                            % (eid, field, value))
    elif field == "likes":
        if not (value is None or is_int(value)):
            malformed(name, "entry '%s' field '%s' must be an integer or null, "
                            "got %r" % (eid, field, value))


def convert_history(name, eid, field, history, version):
    """Validate one legacy history object and return it with ISO 8601 keys."""
    if not isinstance(history, dict):
        malformed(name, "entry '%s' field '%s' is not a history object" % (eid, field))
    converted = {}
    for key, value in history.items():
        check_history_value(name, eid, field, value)
        if version == 1:
            converted[convert_epoch_key(name, eid, field, key)] = value
        else:
            if parse_dt(key) is None:
                malformed(name, "entry '%s' field '%s' has a non-ISO 8601 "
                                "history key %r" % (eid, field, key))
            converted[key] = value
    return converted


def migrate_entry(name, item, version, stamp):
    """Convert one legacy entry to the version 3 entry shape."""
    if not isinstance(item, dict):
        malformed(name, "entry is not an object (%r)" % (item,))
    eid = item.get("id")
    if not isinstance(eid, str):
        malformed(name, "entry is missing a string 'id' (%r)" % (item.get("id"),))
    if not isinstance(item.get("published"), str):
        malformed(name, "entry '%s' is missing a string 'published'" % eid)
    for field in ("width", "height"):
        if not is_int(item.get(field)):
            malformed(name, "entry '%s' has a non-integer '%s'" % (eid, field))

    entry = dict(item)
    for field in HISTORY_FIELDS:
        if field not in item:
            malformed(name, "entry '%s' is missing required field '%s'"
                            % (eid, field))
        entry[field] = convert_history(name, eid, field, item[field], version)
    entry["removed"] = {stamp: False}
    entry["annotations"] = []
    return entry


def migrate_catalog(name, catalog, version, moment=None):
    """Return the version 3 representation of a v1 or v2 catalog."""
    stamp = format_dt(moment or datetime.now().replace(microsecond=0))

    if version == 1:
        source_id = catalog.get("source_id")
        if not isinstance(source_id, str):
            raise VaultError(
                "vault '%s' is invalid: version 1 catalog is missing a string "
                "'source_id'" % name
            )
        entries = catalog.get("entries")
        if not isinstance(entries, list):
            raise VaultError(
                "vault '%s' is invalid: version 1 'entries' must be an array" % name
            )
        return {
            "version": CATALOG_VERSION,
            "source": legacy_source_url(source_id),
            "episodes": [migrate_entry(name, item, 1, stamp) for item in entries],
            "streams": [],
            "clips": [],
        }

    source = catalog.get("source")
    if not isinstance(source, str):
        raise VaultError(
            "vault '%s' is invalid: version 2 catalog is missing a string "
            "'source'" % name
        )
    migrated = {"version": CATALOG_VERSION, "source": source}
    for category in CATEGORIES:
        items = catalog.get(category, [])
        if not isinstance(items, list):
            raise VaultError(
                "vault '%s' is invalid: '%s' must be an array" % (name, category)
            )
        migrated[category] = [migrate_entry(name, item, 2, stamp) for item in items]
    return migrated


def load_catalog(name):
    """Load a vault catalog of any supported version as version 3 in memory.

    Returns `(catalog, stored_version)`; nothing is written to disk.
    """
    raw = read_catalog_file(name)
    version = catalog_version(name, raw)
    if version == CATALOG_VERSION:
        return validate_native(name, raw), version
    return migrate_catalog(name, raw, version), version


def save_catalog(name, catalog):
    """Back up the existing catalog, then write the new one."""
    vault_dir = name
    path = catalog_path(vault_dir)
    if os.path.exists(path):
        try:
            shutil.copyfile(path, backup_path(vault_dir))
        except Exception as exc:
            raise VaultError("vault '%s': could not write %s (%s)"
                             % (name, BACKUP_NAME, exc))
    text = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


# --------------------------------------------------------------------------
# sync logic
# --------------------------------------------------------------------------

def sync_timestamp(catalog):
    """A sync timestamp that is strictly newer than every recorded key."""
    moment = datetime.now().replace(microsecond=0)
    newest = None
    for category in CATEGORIES:
        for stored in catalog.get(category, []):
            if not isinstance(stored, dict):
                continue
            for field in TRACKED_FIELDS:
                history = stored.get(field)
                if not isinstance(history, dict):
                    continue
                for key in history:
                    parsed = parse_dt(key)
                    if parsed is not None and (newest is None or parsed > newest):
                        newest = parsed
    if newest is not None and moment <= newest:
        moment = newest + timedelta(seconds=1)
    return moment


def append_history(history, moment, value):
    """Write `value` at a second strictly later than any existing key."""
    newest = None
    for key in history:
        parsed = parse_dt(key)
        if parsed is not None and (newest is None or parsed > newest):
            newest = parsed
    if newest is not None and moment <= newest:
        moment = newest + timedelta(seconds=1)
    history[format_dt(moment)] = value


def new_entry(item, moment):
    """First observation: static fields plus six initial history entries."""
    entry = {
        "id": item["id"],
        "published": normalize_published(item["published"]),
        "width": item["width"],
        "height": item["height"],
    }
    for field in TRACKED_FIELDS:
        entry[field] = {}
    stamp = format_dt(moment)
    for field in HISTORY_FIELDS:
        entry[field][stamp] = item[field]
    entry["removed"][stamp] = False
    entry["annotations"] = []
    return entry


def update_entry(entry, item, moment):
    """Append history entries for tracked fields whose value changed.

    Returns True when at least one history entry was appended, which is what
    the post-sync summary counts as an update.
    """
    entry.setdefault("annotations", [])
    for field in TRACKED_FIELDS:
        if not isinstance(entry.get(field), dict):
            entry[field] = {}
    changed = False
    for field in HISTORY_FIELDS:
        value = item[field]
        history = entry[field]
        if not history or current_value(history) != value:
            append_history(history, moment, value)
            changed = True
    if not entry["removed"] or current_value(entry["removed"]) is not False:
        append_history(entry["removed"], moment, False)
        changed = True
    return changed


def mark_removed(entry, moment):
    """Record that an entry is gone; True when this run is what removed it."""
    history = entry.get("removed")
    if not isinstance(history, dict):
        history = entry["removed"] = {}
    if not history or current_value(history) is not True:
        append_history(history, moment, True)
        return True
    return False


def sort_entries(entries):
    """Newest `published` first; ties break on lexicographically smaller id."""
    def published_key(entry):
        value = entry.get("published")
        return value if isinstance(value, str) else ""

    def entry_id(entry):
        value = entry.get("id")
        return value if isinstance(value, str) else ""

    ordered = sorted(entries, key=entry_id)
    ordered.sort(key=published_key, reverse=True)
    return ordered


def apply_source(catalog, source_data, moment):
    """Apply fetched metadata and report what this run changed.

    Returns `(counts, changes)`, where `changes` lists
    `(category, entry, group)` for every entry the run touched -- the same
    entries the counts summarize, in catalog order. The buckets are disjoint
    by construction: an entry the source still lists is never a removal, and a
    freshly created entry has nothing to update.
    """
    counts = {"added": 0, "removed": 0, "updated": 0}
    changes = []
    for category in CATEGORIES:
        stored_entries = catalog[category]
        by_id = {}
        for entry in stored_entries:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                by_id.setdefault(entry["id"], entry)

        seen = set()
        for item in source_data[category]:
            eid = item["id"]
            seen.add(eid)
            entry = by_id.get(eid)
            if entry is None:
                entry = new_entry(item, moment)
                stored_entries.append(entry)
                by_id[eid] = entry
                counts["added"] += 1
                changes.append((category, entry, DIGEST_ADDITIONS))
            elif update_entry(entry, item, moment):
                counts["updated"] += 1
                changes.append((category, entry, DIGEST_UPDATES))

        for entry in stored_entries:
            if isinstance(entry, dict) and entry.get("id") not in seen:
                if mark_removed(entry, moment):
                    counts["removed"] += 1
                    changes.append((category, entry, DIGEST_REMOVALS))

        catalog[category] = sort_entries(stored_entries)
    return counts, changes


# --------------------------------------------------------------------------
# download phase
# --------------------------------------------------------------------------

def asset_url(source, kind, entry_id, suffix=""):
    """`<source>/<kind>/<entry_id>[.<format>]` (see AMBIGUITIES T21)."""
    return "%s/%s/%s%s" % (source.rstrip("/"), kind, entry_id, suffix)


def extension_for(content_type):
    """The file extension implied by an HTTP `Content-Type` header."""
    if not content_type:
        return DEFAULT_EXTENSION
    main = content_type.split(";")[0].strip().lower()
    if main in CONTENT_TYPE_EXTENSIONS:
        return CONTENT_TYPE_EXTENSIONS[main]
    guessed = mimetypes.guess_extension(main) if main else None
    if guessed:
        return guessed.lstrip(".")
    return DEFAULT_EXTENSION


def http_download(url):
    """GET `url`, returning `(body, content_type)`.

    Failures are classified so the caller knows whether a retry can help.
    """
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
            return response.read(), response.headers.get("Content-Type")
    except urllib.error.HTTPError as exc:
        try:
            exc.close()
        except Exception:
            pass
        if exc.code >= 500 or exc.code in RETRYABLE_STATUSES:
            raise TransientDownloadError("HTTP %s" % exc.code)
        raise PermanentDownloadError("HTTP %s" % exc.code)
    except urllib.error.URLError as exc:
        raise TransientDownloadError("%s" % exc.reason)
    except Exception as exc:  # timeouts, resets, malformed responses
        raise TransientDownloadError("%s" % exc)


def download_with_retries(url):
    """`http_download` with retries for transient failures only."""
    failure = None
    for _attempt in range(DOWNLOAD_ATTEMPTS):
        try:
            return http_download(url)
        except TransientDownloadError as exc:
            failure = exc
    raise TransientDownloadError(
        "%s (after %d attempts)" % (failure, DOWNLOAD_ATTEMPTS)
    )


def store_download(directory, base, extension, body):
    """Write `body` via a `.part` file so a crash leaves no usable artifact."""
    os.makedirs(directory, exist_ok=True)
    name = "%s.%s" % (base, extension) if extension else base
    final = os.path.join(directory, name)
    partial = final + PART_SUFFIX
    try:
        with open(partial, "wb") as handle:
            handle.write(body)
        os.replace(partial, final)
    except Exception:
        if os.path.exists(partial):
            try:
                os.remove(partial)
            except OSError:
                pass
        raise
    return final


def has_media_file(media_dir, entry_id):
    """True when `<vault>/media/` already holds a completed file for the id.

    Partial-download artifacts do not count, so a stale one cannot block a
    later download (see AMBIGUITIES T39).
    """
    if not os.path.isdir(media_dir):
        return False
    prefix = entry_id + "."
    for name in os.listdir(media_dir):
        if name.endswith(PART_SUFFIX):
            continue
        if name == entry_id or name.startswith(prefix):
            return True
    return False


def download_asset(url, directory, entry_id, extension, label):
    """Fetch one asset, warning to stderr instead of aborting on failure."""
    try:
        body, content_type = download_with_retries(url)
    except PermanentDownloadError as exc:
        warn("%s for entry '%s' is unavailable: %s" % (label, entry_id, exc))
        return False
    except TransientDownloadError as exc:
        warn("%s download failed for entry '%s': %s" % (label, entry_id, exc))
        return False
    try:
        store_download(directory, entry_id,
                       extension or extension_for(content_type), body)
    except OSError as exc:
        warn("could not store %s for entry '%s': %s" % (label, entry_id, exc))
        return False
    return True


def download_entry(vault_dir, source, entry_id, fmt):
    """Download an entry's media file and its preview."""
    suffix = "." + fmt if fmt else ""
    download_asset(
        asset_url(source, "media", entry_id, suffix),
        os.path.join(vault_dir, MEDIA_DIR),
        entry_id,
        fmt,
        "media",
    )
    download_asset(
        asset_url(source, "preview", entry_id),
        os.path.join(vault_dir, PREVIEW_DIR),
        entry_id,
        None,
        "preview",
    )


def download_candidates(catalog, category, media_dir, limit):
    """Ids to download: catalog order, media-less, capped at `limit`."""
    selected = []
    if limit == 0:
        return selected
    for entry in catalog.get(category, []):
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            continue
        if has_media_file(media_dir, entry_id):
            continue
        selected.append(entry_id)
        if limit is not None and len(selected) >= limit:
            break
    return selected


def download_phase(name, catalog, limits, fmt):
    """Retrieve media and preview files for the selected candidates."""
    vault_dir = name
    media_dir = os.path.join(vault_dir, MEDIA_DIR)
    source = catalog.get("source")
    if not isinstance(source, str):
        raise VaultError("vault '%s' is invalid: missing source URL" % name)
    for category in CATEGORIES:
        for entry_id in download_candidates(
            catalog, category, media_dir, limits.get(category)
        ):
            download_entry(vault_dir, source, entry_id, fmt)


# --------------------------------------------------------------------------
# viewer model (shared by `serve` and by the links in change reports)
# --------------------------------------------------------------------------

def viewer_categories(version):
    """Route categories that exist for a vault of `version`."""
    return V1_CATEGORIES if version == 1 else CATEGORIES


def viewer_default_category(version):
    """The category `/catalog/<name>` redirects to."""
    return V1_CATEGORY if version == 1 else DEFAULT_CATEGORY


def viewer_path(name, category=None, entry_id=None):
    """A viewer route, with every segment percent-encoded."""
    path = "/catalog/" + urllib.parse.quote(name, safe="")
    if category is not None:
        path += "/" + urllib.parse.quote(category, safe="")
    if entry_id is not None:
        path += "/" + urllib.parse.quote(entry_id, safe="")
    return path


def viewer_link(name, category, entry_id, host=DEFAULT_VIEWER_HOST,
                port=DEFAULT_VIEWER_PORT):
    """`http://<host>:<port>/catalog/<name>/<category>/<id>`."""
    return "%s://%s:%s%s" % (VIEWER_SCHEME, host, port,
                             viewer_path(name, category, entry_id))


def as_array(value):
    return value if isinstance(value, list) else []


def viewer_catalog(name):
    """`(version, raw catalog)` for the viewer, without migrating anything."""
    raw = read_catalog_file(name)
    return catalog_version(name, raw), raw


def viewer_groups(version, raw):
    """`{route_category: [raw entry, ...]}` in `catalog.json` order."""
    if version == 1:
        return {V1_CATEGORY: as_array(raw.get(V1_CATEGORY))}
    return {category: as_array(raw.get(category)) for category in CATEGORIES}


def viewer_load(name):
    """Read a vault for the viewer without migrating it.

    Returns `(version, {route_category: [raw entry, ...]})` in the order the
    entries appear in `catalog.json`.
    """
    version, raw = viewer_catalog(name)
    return version, viewer_groups(version, raw)


def vault_source(version, raw):
    """The vault's source information, however its version records it."""
    if version == 1:
        source_id = raw.get("source_id")
        return legacy_source_url(source_id if isinstance(source_id, str)
                                 else "")
    source = raw.get("source")
    return source if isinstance(source, str) else ""


def source_entry_url(version, raw, entry_id):
    """The source-platform link for one entry (see Detail Page Source Link).

    v1 derives the channel URL from `source_id`; v2 and v3 append to the
    stored `source`. Both are `<source>/entry/<id>`.
    """
    return vault_source(version, raw) + SOURCE_ENTRY_PATH + entry_id


def find_entry(entries, entry_id):
    """The first entry in this category whose `id` matches, or None.

    Lookup never leaves the category it was handed, so a duplicate id in
    another category cannot satisfy it.
    """
    for item in entries:
        if isinstance(item, dict) and item.get("id") == entry_id:
            return item
    return None


def latest_by(history, sorter):
    """The value at the latest history key under `sorter`, or None."""
    if not isinstance(history, dict) or not history:
        return None
    return history[max(history, key=sorter)]


def viewer_title(entry, sorter):
    """Current title, falling back to the id when no title was recorded."""
    value = latest_by(entry.get("title"), sorter)
    if isinstance(value, str) and value:
        return value
    if value is not None:
        return "%s" % (value,)
    entry_id = entry.get("id")
    return entry_id if isinstance(entry_id, str) and entry_id else "<unknown>"


def saved_filenames(name, subdirectory):
    """Completed filenames in one vault subdirectory, in a stable order.

    Partial download artifacts are excluded: they are not saved assets.
    """
    directory = os.path.join(name, subdirectory)
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    return sorted(item for item in names if not item.endswith(PART_SUFFIX))


def media_filenames(name):
    """Completed filenames in `<vault>/media/`; partial artifacts excluded."""
    return saved_filenames(name, MEDIA_DIR)


def matching_file(filenames, entry_id):
    """The first saved filename containing `entry_id`, or None."""
    if not entry_id:
        return None
    for filename in filenames:
        if entry_id in filename:
            return filename
    return None


def media_match(name, entry_id):
    """The saved media filename that belongs to `entry_id`, or None."""
    return matching_file(media_filenames(name), entry_id)


def preview_match(name, entry_id):
    """The saved preview filename that belongs to `entry_id`, or None."""
    return matching_file(saved_filenames(name, PREVIEW_DIR), entry_id)


def static_path(name, kind, target):
    """A `/vault/...` static URL, with every segment percent-encoded."""
    return "/%s/%s/%s/%s" % (VAULT_ROUTE,
                             urllib.parse.quote(name, safe=""),
                             kind,
                             urllib.parse.quote(target, safe=""))


def is_downloaded(entry_id, filenames):
    """A media filename containing the entry id means it is downloaded."""
    if not entry_id:
        return False
    return any(entry_id in filename for filename in filenames)


def is_removed(entry, version, sorter):
    """Latest `removed` value, which only a v3 catalog carries."""
    if version != CATALOG_VERSION:
        return False
    return latest_by(entry.get("removed"), sorter) is True


def viewer_rows(name, version, entries, filenames):
    """The display model for one category listing."""
    sorter = digest_key_sorter(version)
    rows = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        entry_id = item.get("id")
        entry_id = entry_id if isinstance(entry_id, str) else ""
        rows.append({
            "id": entry_id,
            "title": viewer_title(item, sorter),
            "downloaded": is_downloaded(entry_id, filenames),
            "removed": is_removed(item, version, sorter),
        })
    return rows


# --------------------------------------------------------------------------
# digest
# --------------------------------------------------------------------------

def digest_key_sorter(version):
    """Key ordering for a stored history, per `digest` Current Value Resolution.

    v1 compares UNIX-epoch strings numerically; v2 and v3 compare ISO 8601
    strings lexicographically.
    """
    if version == 1:
        def epoch_key(key):
            text = key.strip() if isinstance(key, str) else str(key)
            if EPOCH_KEY.match(text):
                return (0, int(text), "")
            return (1, 0, text)
        return epoch_key

    def iso_key(key):
        return key if isinstance(key, str) else str(key)
    return iso_key


def ordered_history(entry, field, sorter):
    """`(history, keys)` for one field, with keys in oldest-to-newest order."""
    history = entry.get(field)
    if not isinstance(history, dict) or not history:
        return {}, []
    return history, sorted(history, key=sorter)


def digest_title(entry, sorter):
    """Current title, falling back to the id when no title was ever recorded."""
    history, keys = ordered_history(entry, "title", sorter)
    if keys:
        value = history[keys[-1]]
        if isinstance(value, str) and value:
            return value
        return "%s" % (value,)
    entry_id = entry.get("id")
    return entry_id if isinstance(entry_id, str) and entry_id else "<unknown>"


def report_line(name, category, entry, text):
    """One changed-entry line: the title, then its viewer link.

    Both human-facing change reports (`digest` and the post-sync summary) use
    this, so a link always sits on the same line as the title it belongs to
    (see AMBIGUITIES T42).
    """
    entry_id = entry.get("id")
    if not isinstance(entry_id, str) or not entry_id:
        return text
    return "%s %s" % (text, viewer_link(name, category, entry_id))


def is_removal(entry, sorter):
    """Latest `removed` is true and the prior value, if any, is false."""
    history, keys = ordered_history(entry, "removed", sorter)
    if not keys or history[keys[-1]] is not True:
        return False
    return len(keys) < 2 or history[keys[-2]] is False


def changed_fields(entry, fields, sorter):
    """Tracked fields whose latest two history values differ."""
    changed = []
    for field in fields:
        history, keys = ordered_history(entry, field, sorter)
        if len(keys) < 2:
            continue
        if history[keys[-1]] != history[keys[-2]]:
            changed.append("reappeared" if field == "removed" else field)
    return changed


def classify_entry(entry, fields, sorter, detect_removals):
    """`(group, changed_fields)` for one entry, honouring group precedence."""
    if detect_removals and is_removal(entry, sorter):
        return DIGEST_REMOVALS, []

    lengths = []
    for field in fields:
        _history, keys = ordered_history(entry, field, sorter)
        lengths.append(len(keys))
    if lengths and max(lengths) == 1:
        return DIGEST_ADDITIONS, []

    changed = changed_fields(entry, fields, sorter)
    if changed:
        return DIGEST_UPDATES, changed
    return None, []


def digest_load(name):
    """Read a vault for `digest` without migrating it.

    Returns `(version, source_url, [(label, route_category, entries)],
    fields)`. The route category is the one a viewer link for those entries
    must use: `entries` for v1, the entry's own category for v2 and v3.
    """
    raw = read_catalog_file(name)
    version = catalog_version(name, raw)

    if version == 1:
        source_id = raw.get("source_id")
        source = legacy_source_url(source_id if isinstance(source_id, str) else "")
        groups = [(DIGEST_V1_GROUP, V1_CATEGORY, as_array(raw.get("entries")))]
        return version, source, groups, HISTORY_FIELDS

    source = raw.get("source")
    source = source if isinstance(source, str) else ""
    groups = [(category.capitalize(), category, as_array(raw.get(category)))
              for category in CATEGORIES]
    fields = TRACKED_FIELDS if version == CATALOG_VERSION else HISTORY_FIELDS
    return version, source, groups, fields


def digest_trailing_line(name, version, source):
    """Deterministic metadata line closing the digest (see AMBIGUITIES T33)."""
    generated = format_dt(datetime.now().replace(microsecond=0))
    return ("Digest for vault '%s' | catalog version %d | source: %s "
            "| generated %s" % (name, version, source, generated))


def digest_lines(name):
    """The full digest report for a vault, as a list of output lines."""
    version, source, groups, fields = digest_load(name)
    sorter = digest_key_sorter(version)
    detect_removals = version == CATALOG_VERSION

    out = []
    for label, route, entries in groups:
        buckets = {group: [] for group in DIGEST_GROUPS}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            group, changed = classify_entry(entry, fields, sorter,
                                            detect_removals)
            if group is None:
                continue
            text = digest_title(entry, sorter)
            if group == DIGEST_UPDATES:
                text = "%s (%s)" % (text, ", ".join(changed))
            buckets[group].append(report_line(name, route, entry, text))

        if not any(buckets[group] for group in DIGEST_GROUPS):
            continue  # empty category: omitted
        out.append("%s:" % label)
        for group in DIGEST_GROUPS:
            if not buckets[group]:
                continue
            out.append("  %s:" % group)
            for text in buckets[group]:
                out.append("    - %s" % text)
        out.append("")

    if not out:
        out.append(NO_CHANGES_TEXT)
        out.append("")
    out.append(digest_trailing_line(name, version, source))
    return out


# --------------------------------------------------------------------------
# viewer HTTP server
# --------------------------------------------------------------------------

PAGE_STYLE = ("font-family: system-ui, -apple-system, sans-serif; "
              "margin: 2rem; line-height: 1.5;")
BADGE_STYLE = ("display:inline-block; margin-left:0.5rem; padding:0 0.4rem; "
               "border-radius:0.6rem; font-size:0.75rem;")


def page(title, body):
    """A complete, well-formed HTML document."""
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, "
        "initial-scale=1\">\n"
        "<title>" + html.escape(title) + "</title>\n</head>\n"
        "<body style=\"" + PAGE_STYLE + "\">\n" + body + "\n</body>\n</html>\n"
    )


def safe_vault_name(name):
    """Reject anything that would escape the directory `serve` was started in."""
    if not isinstance(name, str) or not name or len(name) > 255:
        return False
    if name in (".", ".."):
        return False
    if "/" in name or "\\" in name or "\0" in name:
        return False
    return not os.path.isabs(name)


def safe_component(text):
    """One path component that cannot escape the directory it is joined to."""
    if not isinstance(text, str) or not text:
        return False
    if text in (".", ".."):
        return False
    if "/" in text or "\\" in text or "\0" in text:
        return False
    return not os.path.isabs(text)


def contained_path(directory, filename):
    """`<directory>/<filename>`, or None when it would leave `directory`.

    Traversal sequences are rejected before the join, and the resolved path
    is checked afterwards so a symlink cannot escape either.
    """
    if not safe_component(filename):
        return None
    base = os.path.realpath(directory)
    target = os.path.realpath(os.path.join(base, filename))
    if target != base and not target.startswith(base + os.sep):
        return None
    return target


def media_content_type(path):
    """An appropriate MIME type for an archived media file."""
    guessed, _encoding = mimetypes.guess_type(path)
    return guessed or DEFAULT_MEDIA_TYPE


def image_content_type(path):
    """An appropriate image MIME type for an archived preview file."""
    guessed, _encoding = mimetypes.guess_type(path)
    if guessed and guessed.startswith("image/"):
        return guessed
    return DEFAULT_IMAGE_TYPE


def viewer_start_path(name):
    """Where `serve <name>` points the browser: the default category page."""
    try:
        version, _groups = viewer_load(name)
    except VaultError:
        return viewer_path(name)
    return viewer_path(name, viewer_default_category(version))


def landing_body(missing, links):
    """The `/` page: a vault-name form plus the recently visited vaults."""
    parts = ["<h1>mvault viewer</h1>"]
    if missing:
        parts.append(
            "<p style=\"color:#b00020\">Vault \"%s\" was not found.</p>"
            % html.escape(missing)
        )
    parts.append(
        "<form method=\"post\" action=\"/\">\n"
        "<label for=\"catalog\">Vault name</label>\n"
        "<input id=\"catalog\" name=\"catalog\" type=\"text\" "
        "autocomplete=\"off\" autofocus>\n"
        "<button type=\"submit\">Open</button>\n</form>"
    )
    if links:
        parts.append("<h2>Recently viewed</h2>")
        parts.append("<ul>")
        for name, path in links:
            parts.append("<li><a href=\"%s\">%s</a></li>"
                         % (html.escape(path, quote=True), html.escape(name)))
        parts.append("</ul>")
    return "\n".join(parts)


def entry_markup(name, category, row):
    """One listing row, styled so each state is visually distinct."""
    entry_id = row["id"]
    label = html.escape(row["title"])
    badges = []
    styles = ["padding:0.25rem 0;"]
    classes = ["entry"]
    if row["downloaded"]:
        classes.append("is-downloaded")
        badges.append(("downloaded", "#1b5e20", "#e3f6e6"))
    else:
        classes.append("is-absent")
        badges.append(("missing", "#5f6368", "#eeeeee"))
    if row["removed"]:
        classes.append("is-removed")
        styles.append("text-decoration:line-through; opacity:0.6;")
        badges.append(("removed", "#b00020", "#fde7ea"))
    if entry_id:
        anchor = "<a href=\"%s\">%s</a>" % (
            html.escape(viewer_path(name, category, entry_id), quote=True),
            label,
        )
    else:
        anchor = label
    badge_markup = "".join(
        "<span style=\"%scolor:%s; background:%s;\">%s</span>"
        % (BADGE_STYLE, color, background, word)
        for word, color, background in badges
    )
    return "<li id=\"entry-%s\" class=\"%s\" style=\"%s\">%s%s</li>" % (
        html.escape(entry_id, quote=True),
        " ".join(classes),
        " ".join(styles),
        anchor,
        badge_markup,
    )


def listing_body(name, category, categories, rows):
    """The category listing."""
    parts = ["<p><a href=\"/\">&larr; mvault viewer</a></p>",
             "<h1>%s &middot; %s</h1>" % (html.escape(name),
                                          html.escape(category))]
    if len(categories) > 1:
        nav = " | ".join(
            "<a href=\"%s\">%s</a>"
            % (html.escape(viewer_path(name, other), quote=True),
               html.escape(other))
            for other in categories
        )
        parts.append("<nav>%s</nav>" % nav)
    if not rows:
        parts.append("<p>No entries in this category.</p>")
    else:
        parts.append("<ol>")
        parts.extend(entry_markup(name, category, row) for row in rows)
        parts.append("</ol>")
    return "\n".join(parts)


# -- entry detail page -----------------------------------------------------

def chart_timestamp(version, key):
    """A history key as an ISO 8601 chart timestamp.

    v1 stores UNIX-epoch strings, which are converted to UTC `YYYY-MM-DDT
    HH:MM:SS`; v2 and v3 already store that format and pass through. Text
    that fits neither shape is passed through untouched rather than dropped.
    """
    text = key if isinstance(key, str) else "%s" % (key,)
    if version != 1:
        return text
    candidate = text.strip()
    if not EPOCH_KEY.match(candidate):
        return text
    try:
        moment = datetime.fromtimestamp(int(candidate), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return text
    return format_dt(moment.replace(tzinfo=None))


def chart_series(entry, field, version, sorter):
    """One field's points, oldest first, with pairing and values untouched.

    Nothing is filtered or replaced, so a `null` in `likes` stays a `null`.
    """
    history, keys = ordered_history(entry, field, sorter)
    return [{"timestamp": chart_timestamp(version, key),
             "value": history[key]} for key in keys]


def chart_payload(entry, version, sorter):
    """`{"views": [...], "likes": [...]}` for the fields that have history."""
    payload = {}
    for field in CHART_FIELDS:
        points = chart_series(entry, field, version, sorter)
        if points:
            payload[field] = points
    return payload


def embed_json(data):
    """JSON that is safe to drop inside a `<script>` element."""
    text = json.dumps(data, ensure_ascii=False)
    for character, escape in (("<", "\\u003c"), (">", "\\u003e"),
                              ("&", "\\u0026")):
        text = text.replace(character, escape)
    return text


def chart_markup(payload):
    """The machine-readable chart data, plus a table per charted field.

    A field with a single point has no chart to draw, so only its data is
    embedded.
    """
    parts = ["<script id=\"%s\" type=\"application/json\">%s</script>"
             % (CHART_SCRIPT_ID, embed_json(payload))]
    for field in CHART_FIELDS:
        points = payload.get(field) or []
        if len(points) < 2:
            continue
        parts.append("<h2>%s over time</h2>" % html.escape(field))
        rows = "".join(
            "<tr><td>%s</td><td>%s</td></tr>"
            % (html.escape("%s" % point["timestamp"]),
               html.escape("null" if point["value"] is None
                           else "%s" % (point["value"],)))
            for point in points
        )
        parts.append(
            "<table class=\"chart\" data-field=\"%s\">"
            "<thead><tr><th>timestamp</th><th>%s</th></tr></thead>"
            "<tbody>%s</tbody></table>"
            % (html.escape(field, quote=True), html.escape(field), rows)
        )
    return parts


def as_text(value):
    """Display text for a stored scalar, with None rendering as empty."""
    if value is None:
        return ""
    return value if isinstance(value, str) else "%s" % (value,)


def detail_value(entry, field, sorter):
    """Current value of a tracked text field, as display text."""
    return as_text(latest_by(entry.get(field), sorter))


def dimensions_text(entry):
    """`width` and `height` as display text."""
    width, height = entry.get("width"), entry.get("height")
    if width is None and height is None:
        return ""
    if width is None or height is None:
        return "%s" % (width if height is None else height,)
    return "%sx%s" % (width, height)


def definition_markup(pairs):
    parts = ["<dl>"]
    for term, value in pairs:
        parts.append("<dt>%s</dt><dd>%s</dd>" % (html.escape(term), value))
    parts.append("</dl>")
    return "\n".join(parts)


def media_markup(name, entry_id):
    """The playback reference, when a downloaded media file matches."""
    filename = media_match(name, entry_id)
    if filename is None:
        return ["<p class=\"media-missing\">No downloaded media file "
                "for this entry.</p>"]
    url = html.escape(static_path(name, MEDIA_ROUTE, filename), quote=True)
    return ["<figure class=\"media\">",
            "<video controls preload=\"metadata\" src=\"%s\"></video>" % url,
            "<figcaption><a href=\"%s\">%s</a></figcaption>"
            % (url, html.escape(filename)),
            "</figure>"]


def preview_markup(name, entry_id):
    """The archived preview image, when one was saved for this entry."""
    if preview_match(name, entry_id) is None:
        return []
    url = html.escape(static_path(name, PREVIEW_ROUTE, entry_id), quote=True)
    return ["<p class=\"preview\"><img src=\"%s\" alt=\"preview image\" "
            "style=\"max-width:480px\"></p>" % url]


def detail_body(name, category, version, raw, entry):
    """The entry detail page: metadata, media, and the chart data."""
    sorter = digest_key_sorter(version)
    entry_id = entry.get("id")
    entry_id = entry_id if isinstance(entry_id, str) else ""
    listing = viewer_path(name, category)
    source = source_entry_url(version, raw, entry_id)
    parts = ["<p><a href=\"%s\">&larr; %s &middot; %s</a></p>"
             % (html.escape(listing, quote=True), html.escape(name),
                html.escape(category)),
             "<h1>%s</h1>" % html.escape(viewer_title(entry, sorter))]
    if is_removed(entry, version, sorter):
        parts.append("<p><span style=\"%scolor:#b00020; background:#fde7ea;\">"
                     "removed</span></p>" % BADGE_STYLE)
    parts.append(definition_markup([
        ("Entry id", html.escape(entry_id)),
        ("Published", html.escape(as_text(entry.get("published")))),
        ("Dimensions", html.escape(dimensions_text(entry))),
        ("Source", "<a href=\"%s\">%s</a>"
         % (html.escape(source, quote=True), html.escape(source))),
    ]))
    description = detail_value(entry, "description", sorter)
    parts.append("<h2>Description</h2>")
    parts.append("<p class=\"description\">%s</p>" % html.escape(description))
    parts.extend(preview_markup(name, entry_id))
    parts.extend(media_markup(name, entry_id))
    parts.extend(chart_markup(chart_payload(entry, version, sorter)))
    parts.append("<p><a href=\"%s\">Back to %s</a></p>"
                 % (html.escape(listing, quote=True), html.escape(category)))
    return "\n".join(parts)


class ViewerState:
    """Server-side memory of which vaults this viewer has shown."""

    def __init__(self):
        self._lock = threading.Lock()
        self._recent = []
        self._missing = None

    def remember(self, name):
        with self._lock:
            if name in self._recent:
                self._recent.remove(name)
            self._recent.insert(0, name)
            del self._recent[RECENT_LIMIT:]
            return list(self._recent)

    def recent(self):
        with self._lock:
            return list(self._recent)

    def flag_missing(self, name):
        with self._lock:
            self._missing = name

    def take_missing(self):
        with self._lock:
            missing, self._missing = self._missing, None
            return missing


class ViewerHandler(BaseHTTPRequestHandler):
    """Routes for `/` and `/catalog/...`; every failure stays well-formed."""

    server_version = "mvault-viewer"
    state = None

    # -- plumbing ----------------------------------------------------------

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def do_GET(self):
        self.dispatch("GET")

    def do_HEAD(self):
        self.dispatch("HEAD")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        try:
            self.route(method)
        except Exception:  # never leak a traceback to the client
            try:
                self.send_page(500, "Server error",
                               "<h1>Server error</h1>"
                               "<p><a href=\"/\">Back to the start page</a></p>")
            except Exception:
                pass

    def send_page(self, status, title, body, headers=()):
        payload = page(title, body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        for key, value in headers:
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def redirect(self, location, status=REDIRECT_STATUS, headers=()):
        escaped = html.escape(location, quote=True)
        body = ("<p>Continue to <a href=\"%s\">%s</a>.</p>"
                % (escaped, html.escape(location)))
        self.send_page(status, "Redirecting", body,
                       headers=(("Location", location),) + tuple(headers))

    def not_found(self, detail, links=(), headers=()):
        trail = "".join(
            "<p><a href=\"%s\">%s</a></p>"
            % (html.escape(href, quote=True), html.escape(text))
            for href, text in tuple(links) + (("/", "Back to the start page"),)
        )
        self.send_page(404, "Not found",
                       "<h1>Not found</h1><p>%s</p>%s"
                       % (html.escape(detail), trail), headers=headers)

    def forbidden(self, detail):
        self.send_page(403, "Forbidden",
                       "<h1>Forbidden</h1><p>%s</p>"
                       "<p><a href=\"/\">Back to the start page</a></p>"
                       % html.escape(detail))

    def send_file(self, path, content_type):
        """Send one archived file; only whole files are served."""
        try:
            with open(path, "rb") as handle:
                payload = handle.read()
        except OSError:
            return self.not_found("That file could not be read.")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    # -- recent vaults -----------------------------------------------------

    def cookie_recents(self):
        """Vault names this browser remembers, most recent first."""
        header = self.headers.get("Cookie")
        if not header:
            return []
        try:
            jar = http.cookies.SimpleCookie(header)
        except http.cookies.CookieError:
            return []
        morsel = jar.get(RECENT_COOKIE)
        if morsel is None:
            return []
        names = []
        for chunk in morsel.value.split(","):
            name = urllib.parse.unquote(chunk).strip()
            if name and safe_vault_name(name) and name not in names:
                names.append(name)
        return names[:RECENT_LIMIT]

    def touch_recent(self, name):
        """Record a visit, returning the `Set-Cookie` header it needs.

        The list lives both in the server and in a long-lived cookie, so a
        later session of the same browser still sees the vault (T46).
        """
        names = self.state.remember(name)
        for other in self.cookie_recents():
            if other not in names:
                names.append(other)
        value = ",".join(urllib.parse.quote(item, safe="")
                         for item in names[:RECENT_LIMIT])
        return (("Set-Cookie", "%s=%s; Path=/; Max-Age=%d; SameSite=Lax"
                 % (RECENT_COOKIE, value, RECENT_COOKIE_MAX_AGE)),)

    def recent_links(self, names):
        """`(name, default category path)` for every still-loadable vault."""
        links = []
        for name in names:
            if not safe_vault_name(name):
                continue
            try:
                version, _groups = viewer_load(name)
            except VaultError:
                continue
            links.append(
                (name, viewer_path(name, viewer_default_category(version)))
            )
        return links

    # -- routing -----------------------------------------------------------

    def route(self, method):
        parts = urllib.parse.urlsplit(self.path)
        segments = [urllib.parse.unquote(segment)
                    for segment in parts.path.split("/") if segment]
        if method == "POST":
            return self.handle_post(segments)
        if not segments:
            return self.handle_root(urllib.parse.parse_qs(parts.query))
        if segments[0] == "catalog":
            return self.handle_catalog(segments[1:])
        if segments[0] == VAULT_ROUTE:
            return self.handle_vault(segments[1:])
        return self.not_found("No such page.")

    def handle_post(self, segments):
        if segments:
            return self.not_found("No such page.")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        fields = urllib.parse.parse_qs(raw.decode("utf-8", "replace"))
        values = fields.get("catalog") or []
        target = values[0].strip() if values else ""
        if not target:
            return self.redirect("/", REDIRECT_AFTER_POST_STATUS)
        return self.redirect(viewer_path(target), REDIRECT_AFTER_POST_STATUS)

    def handle_root(self, query):
        missing = self.state.take_missing()
        if not missing:
            asked = query.get("missing") or []
            missing = asked[0] if asked else None
        names = self.state.recent()
        for name in self.cookie_recents():
            if name not in names:
                names.append(name)
        self.send_page(200, "mvault viewer",
                       landing_body(missing, self.recent_links(names)))

    def vault_missing(self, name):
        """A vault that cannot be read sends the browser back to `/`."""
        self.state.flag_missing(name)
        self.redirect("/")

    def handle_catalog(self, segments):
        if not segments:
            return self.redirect("/")
        if len(segments) > 3:
            return self.not_found("No such page.")
        name = segments[0]
        if not safe_vault_name(name):
            return self.vault_missing(name)
        try:
            version, raw = viewer_catalog(name)
        except VaultError:
            return self.vault_missing(name)
        groups = viewer_groups(version, raw)

        cookie = self.touch_recent(name)
        default_path = viewer_path(name, viewer_default_category(version))
        if len(segments) == 1:
            return self.redirect(default_path, headers=cookie)

        category = segments[1]
        if category not in viewer_categories(version):
            return self.redirect(default_path, headers=cookie)

        entries = groups.get(category, [])
        if len(segments) == 3:
            return self.handle_detail(name, category, version, raw, entries,
                                      segments[2], cookie)
        rows = viewer_rows(name, version, entries, media_filenames(name))
        body = listing_body(name, category, viewer_categories(version), rows)
        self.send_page(200, "%s - %s" % (name, category), body,
                       headers=cookie)

    def handle_detail(self, name, category, version, raw, entries, entry_id,
                      cookie):
        """`/catalog/<name>/<category>/<id>`: one entry's detail page."""
        entry = find_entry(entries, entry_id)
        if entry is None:
            return self.not_found(
                "No entry '%s' in category '%s' of vault '%s'."
                % (entry_id, category, name),
                links=((viewer_path(name, category),
                        "Back to the %s listing" % category),),
                headers=cookie,
            )
        body = detail_body(name, category, version, raw, entry)
        self.send_page(200, "%s - %s" % (name, entry_id), body,
                       headers=cookie)

    # -- archived files ----------------------------------------------------

    def handle_vault(self, segments):
        """`/vault/<name>/media/<file>` and `/vault/<name>/preview/<id>`."""
        if len(segments) != 3:
            return self.not_found("No such page.")
        name, kind, target = segments
        if not safe_vault_name(name):
            # A traversal attempt in the name segment is refused outright
            # rather than treated as a vault that happens to be missing.
            return self.forbidden("That vault name is not allowed.")
        if not os.path.isdir(name):
            return self.vault_missing(name)
        if kind == MEDIA_ROUTE:
            return self.serve_media(name, target)
        if kind == PREVIEW_ROUTE:
            return self.serve_preview(name, target)
        return self.not_found("No such page.")

    def serve_media(self, name, filename):
        """Serve `<vault>/media/<file>` by its exact saved name."""
        path = contained_path(os.path.join(name, MEDIA_DIR), filename)
        if path is None:
            return self.forbidden("That path is not inside the vault's "
                                  "media directory.")
        if not os.path.isfile(path):
            return self.not_found("No media file '%s' in vault '%s'."
                                  % (filename, name))
        return self.send_file(path, media_content_type(path))

    def serve_preview(self, name, entry_id):
        """Serve the preview image whose saved filename contains `<id>`."""
        if not safe_component(entry_id):
            return self.forbidden("That path is not inside the vault's "
                                  "preview directory.")
        filename = preview_match(name, entry_id)
        if filename is None:
            return self.not_found("No preview image for '%s' in vault '%s'."
                                  % (entry_id, name))
        path = contained_path(os.path.join(name, PREVIEW_DIR), filename)
        if path is None or not os.path.isfile(path):
            return self.not_found("No preview image for '%s' in vault '%s'."
                                  % (entry_id, name))
        return self.send_file(path, image_content_type(path))


def make_viewer_handler(state):
    """A handler class bound to one server's state."""
    return type("BoundViewerHandler", (ViewerHandler,), {"state": state})


def open_browser(url):
    """Point the user's browser at `url` without blocking the server."""
    if os.environ.get("MVAULT_NO_BROWSER"):
        return

    def opener():
        try:
            webbrowser.open(url)
        except Exception:  # a headless machine has nothing to open
            pass

    threading.Thread(target=opener, daemon=True).start()


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def command_init(name, url):
    if os.path.exists(name):
        raise VaultError("vault '%s' already exists" % name)
    catalog = {
        "version": CATALOG_VERSION,
        "source": url,
        "episodes": [],
        "streams": [],
        "clips": [],
    }
    os.makedirs(name)
    save_catalog(name, catalog)
    return 0


def command_sync(name, limits=None, fmt=None, skip_metadata=False,
                 skip_download=False):
    """Run the metadata phase, then the download phase.

    A legacy vault is migrated in memory by `load_catalog`, so the download
    phase always sees a v3 catalog and the migrated `source` value.
    """
    catalog, _version = load_catalog(name)

    counts = None
    changes = []
    if not skip_metadata:
        source_data = fetch_source(catalog["source"])
        moment = sync_timestamp(catalog)
        counts, changes = apply_source(catalog, source_data, moment)
        # Persist before downloading: the metadata phase is durable even when
        # a later download fails (see AMBIGUITIES T27).
        save_catalog(name, catalog)

    if not skip_download:
        download_phase(name, catalog, limits or {}, fmt)

    if counts is not None:
        print("Sync summary: added %d, removed %d, updated %d"
              % (counts["added"], counts["removed"], counts["updated"]))
        # The catalog on disk is v3 by now, so every link uses the category
        # the entry ended up in (see AMBIGUITIES T41).
        for line in summary_change_lines(name, changes):
            print(line)
    return 0


def summary_change_lines(name, changes):
    """Changed-entry lines for the post-sync summary, with viewer links.

    Laid out like `digest`: category, then change group, then one line per
    entry carrying the entry's current title and its viewer link.
    """
    sorter = digest_key_sorter(CATALOG_VERSION)
    out = []
    for category in CATEGORIES:
        buckets = {group: [] for group in DIGEST_GROUPS}
        for changed_category, entry, group in changes:
            if changed_category != category:
                continue
            text = viewer_title(entry, sorter)
            buckets[group].append(report_line(name, category, entry, text))
        if not any(buckets[group] for group in DIGEST_GROUPS):
            continue
        out.append("%s:" % category.capitalize())
        for group in DIGEST_GROUPS:
            if not buckets[group]:
                continue
            out.append("  %s:" % group)
            for text in buckets[group]:
                out.append("    - %s" % text)
    return out


def command_migrate(name):
    """Convert a v1 or v2 catalog to v3 on disk; a v3 catalog is a no-op."""
    raw = read_catalog_file(name)
    version = catalog_version(name, raw)
    if version == CATALOG_VERSION:
        validate_native(name, raw)
        return 0
    migrated = migrate_catalog(name, raw, version)
    save_catalog(name, migrated)
    return 0


def command_digest(name):
    """Print a human-readable summary of notable changes; never writes."""
    for line in digest_lines(name):
        print(line)
    return 0


def command_serve(name=None, host=DEFAULT_VIEWER_HOST,
                  port=DEFAULT_VIEWER_PORT):
    """Serve the local viewer and open a browser on it."""
    handler = make_viewer_handler(ViewerState())
    try:
        server = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise VaultError("could not serve on %s:%s (%s)" % (host, port, exc))

    bound_port = server.server_address[1]
    shown_host = DEFAULT_VIEWER_HOST if host in ("", "0.0.0.0", "::") else host
    base = "%s://%s:%d" % (VIEWER_SCHEME, shown_host, bound_port)
    target = base + "/" if not name else base + viewer_start_path(name)
    print("Serving mvault viewer at %s/" % base, flush=True)
    if target != base + "/":
        print("Opening %s" % target, flush=True)
    open_browser(target)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # Ctrl-C is how a local viewer is stopped
        pass
    finally:
        server.server_close()
    return 0


def port_number(text):
    """A `--port` value: a TCP port, where 0 means "any free port"."""
    if not NON_NEGATIVE_INT.match(text or "") or int(text) > 65535:
        raise argparse.ArgumentTypeError("%r is not a valid port" % text)
    return int(text)


def non_negative_int(text):
    """An `--episodes`/`--streams`/`--clips` limit: digits only, no sign."""
    if not NON_NEGATIVE_INT.match(text or ""):
        raise argparse.ArgumentTypeError(
            "%r is not a non-negative integer" % text
        )
    return int(text)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mvault.py",
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
        "sync", help="fetch source metadata and update the vault catalog"
    )
    sync_parser.add_argument("name", help="existing vault directory")
    for category in CATEGORIES:
        sync_parser.add_argument(
            "--%s" % category,
            type=non_negative_int,
            default=None,
            metavar="<n>",
            help="maximum number of media downloads from %s" % category,
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
        dest="fmt",
        default=None,
        metavar="<str>",
        help="override the media download format and output extension",
    )

    migrate_parser = subparsers.add_parser(
        "migrate", help="convert a legacy (v1/v2) catalog to the v3 format"
    )
    migrate_parser.add_argument("name", help="existing vault directory")

    digest_parser = subparsers.add_parser(
        "digest", help="summarize notable changes recorded in a vault"
    )
    digest_parser.add_argument("name", help="existing vault directory")

    serve_parser = subparsers.add_parser(
        "serve", help="browse local vaults in a web viewer"
    )
    serve_parser.add_argument(
        "name", nargs="?", default=None,
        help="vault to open in the browser (optional)",
    )
    serve_parser.add_argument(
        "--host", default=DEFAULT_VIEWER_HOST, metavar="<host>",
        help="bind host (default %s)" % DEFAULT_VIEWER_HOST,
    )
    serve_parser.add_argument(
        "--port", type=port_number, default=DEFAULT_VIEWER_PORT,
        metavar="<port>", help="bind port (default %d)" % DEFAULT_VIEWER_PORT,
    )

    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help(sys.stderr)
        return 2

    try:
        if args.command == "init":
            return command_init(args.name, args.url)
        if args.command == "migrate":
            return command_migrate(args.name)
        if args.command == "digest":
            return command_digest(args.name)
        if args.command == "serve":
            return command_serve(args.name, args.host, args.port)
        fmt = args.fmt
        if isinstance(fmt, str):
            fmt = fmt[1:] if fmt.startswith(".") else fmt
            fmt = fmt or None
        limits = {category: getattr(args, category) for category in CATEGORIES}
        return command_sync(
            args.name,
            limits=limits,
            fmt=fmt,
            skip_metadata=args.skip_metadata,
            skip_download=args.skip_download,
        )
    except VaultError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    except SourceError as exc:
        print("error: source metadata fetch failed: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
