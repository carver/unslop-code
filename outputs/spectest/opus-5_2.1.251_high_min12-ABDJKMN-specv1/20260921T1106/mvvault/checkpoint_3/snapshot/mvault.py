#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Creates vault directories holding a `catalog.json`, and records the history of
tracked fields keyed by sync timestamp.
"""
import argparse
import json
import mimetypes
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

CATEGORIES = ("episodes", "streams", "clips")
STATIC_FIELDS = ("id", "published", "width", "height")
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)
SOURCE_FIELDS = STATIC_FIELDS + SOURCE_TRACKED_FIELDS

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"
CATALOG_VERSION = 3
SUPPORTED_VERSIONS = (1, 2, 3)
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/%s"
TS_FORMAT = "%Y-%m-%dT%H:%M:%S"
FETCH_FAILURE = "Source metadata fetch failure"

PROG = "mvault.py"

MEDIA_DIR = "media"
PREVIEW_DIR = "previews"
PARTIAL_SUFFIX = ".part"
DEFAULT_EXTENSION = ".bin"
DOWNLOAD_ATTEMPTS = 3          # one initial try plus two retries
RETRY_DELAY = 0.0              # retries are immediate; nothing here rate-limits

# Content-Type values whose extension is pinned rather than left to the
# platform's mime database, which varies between machines.
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
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/json": ".json",
    "application/octet-stream": ".bin",
    "text/plain": ".txt",
    "text/html": ".html",
}

# digest presentation
V1_GROUP_LABEL = "Entries"
CATEGORY_LABELS = (
    ("episodes", "Episodes"),
    ("streams", "Streams"),
    ("clips", "Clips"),
)
REMOVALS_GROUP = "Removals"
ADDITIONS_GROUP = "Additions"
UPDATES_GROUP = "Field updates"
DIGEST_GROUPS = (REMOVALS_GROUP, ADDITIONS_GROUP, UPDATES_GROUP)
REAPPEARED_LABEL = "reappeared"
NO_CHANGES_TEXT = "No notable changes found."
UNTITLED = "(untitled)"


class MvaultError(Exception):
    """A user-facing failure; the message is printed to stderr."""


class DownloadError(Exception):
    """One asset could not be retrieved; `permanent` suppresses retries."""

    def __init__(self, detail, permanent):
        super().__init__(detail)
        self.permanent = permanent


class SourceFetchError(MvaultError):
    """The source metadata could not be fetched or is malformed."""

    def __init__(self, detail):
        super().__init__("%s: %s" % (FETCH_FAILURE, detail))


# --------------------------------------------------------------------------
# type helpers
# --------------------------------------------------------------------------

def is_string(value):
    return isinstance(value, str)


def is_integer(value):
    # bool is a subclass of int, but a boolean is not a pixel count.
    return isinstance(value, int) and not isinstance(value, bool)


def is_likes(value):
    return value is None or is_integer(value)


FIELD_CHECKS = {
    "id": is_string,
    "published": is_string,
    "width": is_integer,
    "height": is_integer,
    "title": is_string,
    "description": is_string,
    "views": is_integer,
    "likes": is_likes,
    "preview": is_string,
}


def same_value(left, right):
    """Change detection: `null` is an ordinary value, and bools are not ints."""
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return type(left) is type(right) and left == right


# --------------------------------------------------------------------------
# datetime handling
# --------------------------------------------------------------------------

def format_datetime(moment):
    """Render as `YYYY-MM-DDTHH:MM:SS`, never locale-sensitive."""
    return "%04d-%02d-%02dT%02d:%02d:%02d" % (
        moment.year, moment.month, moment.day,
        moment.hour, moment.minute, moment.second,
    )


def parse_datetime(text):
    """Parse ISO 8601 datetime or date-only text; None when unparseable."""
    if not isinstance(text, str):
        return None
    candidate = text.strip()
    if not candidate:
        return None
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(candidate, pattern)
                break
            except ValueError:
                continue
        else:
            return None
    # Timezone suffixes are dropped, not converted; fractions are truncated.
    return parsed.replace(tzinfo=None, microsecond=0)


def normalize_published(text):
    """Date-only values gain a `00:00:00` time component."""
    parsed = parse_datetime(text)
    if parsed is None:
        return text
    return format_datetime(parsed)


def epoch_to_datetime(text):
    """Parse a version 1 UNIX-epoch-seconds history key; None when unusable."""
    if not isinstance(text, str):
        return None
    try:
        seconds = int(text.strip())
    except (ValueError, AttributeError):
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(
            tzinfo=None, microsecond=0)
    except (OverflowError, OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# history helpers
# --------------------------------------------------------------------------

def history_sort_key(key):
    parsed = parse_datetime(key)
    if parsed is None:
        return (0, datetime.min, key)
    return (1, parsed, key)


def latest_key(history):
    if not history:
        return None
    return max(history, key=history_sort_key)


def current_value(history):
    key = latest_key(history)
    return None if key is None else history[key]


def append_change(history, value, stamp):
    """Record `value` at `stamp` unless it already is the current value."""
    key = latest_key(history)
    if key is not None and same_value(history[key], value):
        return False
    history[stamp] = value
    return True


def newest_history_moment(catalog):
    """The latest datetime appearing as a history key anywhere in the catalog."""
    newest = None
    for category in CATEGORIES:
        for item in catalog.get(category, []):
            if not isinstance(item, dict):
                continue
            for field in TRACKED_FIELDS:
                history = item.get(field)
                if not isinstance(history, dict):
                    continue
                for key in history:
                    moment = parse_datetime(key)
                    if moment is not None and (newest is None or moment > newest):
                        newest = moment
    return newest


def sync_timestamp(catalog):
    """One timestamp per sync, strictly newer than every existing history key."""
    moment = datetime.now().replace(microsecond=0)
    newest = newest_history_moment(catalog)
    if newest is not None and moment <= newest:
        moment = newest + timedelta(seconds=1)
    return format_datetime(moment)


# --------------------------------------------------------------------------
# catalog storage
# --------------------------------------------------------------------------

def catalog_path(vault):
    return os.path.join(vault, CATALOG_NAME)


def backup_path(vault):
    return os.path.join(vault, BACKUP_NAME)


def new_catalog(url):
    return {
        "version": CATALOG_VERSION,
        "source": url,
        "episodes": [],
        "streams": [],
        "clips": [],
    }


def write_catalog(vault, catalog):
    """Back up any existing catalog byte-for-byte, then write the new one."""
    path = catalog_path(vault)
    if os.path.exists(path):
        # A backup that cannot be written aborts the write entirely, so the
        # existing catalog is never replaced without a recovery copy.
        try:
            shutil.copyfile(path, backup_path(vault))
        except OSError as exc:
            raise MvaultError("could not write %s for vault %s (%s)"
                              % (BACKUP_NAME, vault, exc))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(catalog, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        # The spec's persistence boundary: metadata is on disk before the
        # download phase (and therefore before a successful sync returns).
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass


def read_catalog_file(name):
    """Read `<name>/catalog.json`, or raise with the vault name."""
    if not os.path.isdir(name):
        raise MvaultError("vault not found: %s" % name)
    path = catalog_path(name)
    if not os.path.isfile(path):
        raise MvaultError("invalid vault: %s: missing %s" % (name, CATALOG_NAME))
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (ValueError, OSError) as exc:
        raise MvaultError("invalid vault: %s: unreadable %s (%s)"
                          % (name, CATALOG_NAME, exc))


def invalid_vault(name, detail):
    return MvaultError("invalid vault: %s: %s" % (name, detail))


def detect_version(name, catalog):
    """The catalog's declared version, validated against the supported set."""
    if not isinstance(catalog, dict):
        raise invalid_vault(name, "catalog root is not an object")
    if "version" not in catalog:
        raise invalid_vault(name, "missing catalog version field")
    version = catalog["version"]
    if not is_integer(version):
        raise invalid_vault(name, "non-integer catalog version %r" % (version,))
    if version not in SUPPORTED_VERSIONS:
        raise invalid_vault(name, "unsupported catalog version %r" % (version,))
    return version


# --------------------------------------------------------------------------
# legacy catalogs
# --------------------------------------------------------------------------

def v1_source_url(source_id):
    return V1_SOURCE_TEMPLATE % source_id


def convert_history(name, entry_id, field, history, epoch_keys):
    """Validate one stored history object, converting v1 epoch keys to ISO."""
    if not isinstance(history, dict):
        raise invalid_vault(
            name, "entry %r has a malformed %r history" % (entry_id, field))
    check = FIELD_CHECKS[field]
    converted = {}
    for key, value in history.items():
        if not is_string(key):
            raise invalid_vault(
                name, "entry %r has a non-string %r history key" % (entry_id, field))
        if epoch_keys:
            moment = epoch_to_datetime(key)
            if moment is None:
                raise invalid_vault(
                    name, "entry %r has a malformed epoch key %r in %r"
                          % (entry_id, key, field))
            key = format_datetime(moment)
        elif parse_datetime(key) is None:
            raise invalid_vault(
                name, "entry %r has a malformed datetime key %r in %r"
                      % (entry_id, key, field))
        if not check(value):
            raise invalid_vault(
                name, "entry %r has a wrong-typed %r history value" % (entry_id, field))
        converted[key] = value
    return converted


def migrate_entry(name, item, stamp, epoch_keys):
    """One legacy entry in v3 shape: converted history, `removed`, `annotations`."""
    if not isinstance(item, dict):
        raise invalid_vault(name, "legacy entry is not an object")
    entry_id = item.get("id")
    if not is_string(entry_id):
        raise invalid_vault(name, "legacy entry has a missing or non-string id")
    if "published" in item and not is_string(item["published"]):
        raise invalid_vault(name, "entry %r has a non-string published" % entry_id)
    for field in ("width", "height"):
        if field in item and not is_integer(item[field]):
            raise invalid_vault(
                name, "entry %r has a non-integer %s" % (entry_id, field))
    migrated = dict(item)
    for field in SOURCE_TRACKED_FIELDS:
        if field in item:
            migrated[field] = convert_history(
                name, entry_id, field, item[field], epoch_keys)
    # Legacy entries carry neither field, so both are additions.
    migrated["removed"] = {stamp: False}
    migrated["annotations"] = []
    return migrated


def migrate_v1(name, catalog, stamp):
    source_id = catalog.get("source_id")
    if not is_string(source_id):
        raise invalid_vault(name, "missing or non-string source_id")
    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise invalid_vault(name, "entries is missing or not an array")
    return {
        "version": CATALOG_VERSION,
        "source": v1_source_url(source_id),
        "episodes": [migrate_entry(name, item, stamp, True) for item in entries],
        "streams": [],
        "clips": [],
    }


def migrate_v2(name, catalog, stamp):
    source = catalog.get("source")
    if not is_string(source):
        raise invalid_vault(name, "missing or non-string source URL")
    migrated = {"version": CATALOG_VERSION, "source": source}
    for category in CATEGORIES:
        items = catalog.get(category)
        if not isinstance(items, list):
            raise invalid_vault(
                name, "category %r is missing or not an array" % category)
        migrated[category] = [migrate_entry(name, item, stamp, False)
                              for item in items]
    return migrated


def migration_timestamp():
    """One ISO 8601 timestamp for a whole migration run."""
    return format_datetime(datetime.now().replace(microsecond=0))


def validate_v3(name, catalog):
    if not is_string(catalog.get("source")):
        raise invalid_vault(name, "missing or non-string source URL")
    for category in CATEGORIES:
        items = catalog.get(category)
        if not isinstance(items, list):
            raise invalid_vault(
                name, "category %r is missing or not an array" % category)
        for item in items:
            if not isinstance(item, dict) or not is_string(item.get("id")):
                raise invalid_vault(
                    name, "category %r holds a malformed entry" % category)
    return catalog


def load_vault(name):
    """Load a vault as a v3 catalog in memory; returns (catalog, on-disk version).

    Version 1 and 2 catalogs are converted here and only here; nothing is
    written, so a read-only command leaves a legacy `catalog.json` alone.
    """
    raw = read_catalog_file(name)
    version = detect_version(name, raw)
    if version == CATALOG_VERSION:
        return validate_v3(name, raw), version
    stamp = migration_timestamp()
    if version == 1:
        return migrate_v1(name, raw, stamp), version
    return migrate_v2(name, raw, stamp), version


def load_catalog(name):
    """The v3 catalog of a vault, whatever version is stored on disk."""
    return load_vault(name)[0]


# --------------------------------------------------------------------------
# source fetching
# --------------------------------------------------------------------------

def fetch_source(url):
    """HTTP GET the source URL with urllib.request and parse its JSON body."""
    try:
        response = urllib.request.urlopen(url)
    except Exception as exc:                      # URLError, HTTPError, ...
        raise SourceFetchError("could not fetch %s (%s)" % (url, exc))
    try:
        raw = response.read()
    except Exception as exc:
        raise SourceFetchError("could not read %s (%s)" % (url, exc))
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
            raise SourceFetchError("undecodable response from %s (%s)" % (url, exc))
    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise SourceFetchError("invalid JSON from %s (%s)" % (url, exc))
    return validate_source(document)


def validate_source(document):
    """Every category must be an array of entries carrying all nine fields."""
    if not isinstance(document, dict):
        raise SourceFetchError("source response is not a JSON object")
    validated = {}
    for category in CATEGORIES:
        items = document.get(category)
        if not isinstance(items, list):
            raise SourceFetchError(
                "source response category %r is missing or not an array" % category)
        for item in items:
            if not isinstance(item, dict):
                raise SourceFetchError(
                    "source entry in %r is not an object" % category)
            for field in SOURCE_FIELDS:
                if field not in item:
                    raise SourceFetchError(
                        "source entry in %r is missing field %r" % (category, field))
                if not FIELD_CHECKS[field](item[field]):
                    raise SourceFetchError(
                        "source entry %r in %r has wrong type for field %r"
                        % (item.get("id"), category, field))
        validated[category] = items
    return validated


# --------------------------------------------------------------------------
# catalog updates
# --------------------------------------------------------------------------

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
    entry["annotations"] = []
    return entry


def update_entry(entry, source_entry, stamp):
    """Re-observe an existing entry; True when anything actually changed."""
    for field in TRACKED_FIELDS:
        if not isinstance(entry.get(field), dict):
            entry[field] = {}
    changed = False
    for field in SOURCE_TRACKED_FIELDS:
        changed |= append_change(entry[field], source_entry[field], stamp)
    changed |= append_change(entry["removed"], False, stamp)
    return changed


def mark_removed(entry, stamp):
    """Record a disappearance; True only for a newly removed entry."""
    if not isinstance(entry.get("removed"), dict):
        entry["removed"] = {}
    return append_change(entry["removed"], True, stamp)


def sort_entries(entries):
    """Newest `published` first; ties break by lexicographically smaller id."""
    entries.sort(key=lambda item: item.get("id") or "")
    entries.sort(key=lambda item: item.get("published") or "", reverse=True)


def update_catalog(catalog, source, stamp):
    """Apply source metadata and return the post-sync (added, removed,
    updated) counts. Each entry lands in at most one count, with the same
    precedence `digest` uses: removal, then addition, then field update."""
    counts = {"added": 0, "removed": 0, "updated": 0}
    for category in CATEGORIES:
        entries = catalog[category]
        by_id = {entry["id"]: entry for entry in entries}
        seen = set()
        for source_entry in source[category]:
            eid = source_entry["id"]
            seen.add(eid)
            existing = by_id.get(eid)
            if existing is None:
                entry = make_entry(source_entry, stamp)
                entries.append(entry)
                by_id[eid] = entry
                counts["added"] += 1
            elif update_entry(existing, source_entry, stamp):
                counts["updated"] += 1
        for entry in entries:
            if entry["id"] not in seen and mark_removed(entry, stamp):
                counts["removed"] += 1
        sort_entries(entries)
    return counts


# --------------------------------------------------------------------------
# download phase
# --------------------------------------------------------------------------

def warn(message):
    sys.stderr.write("%s: warning: %s\n" % (PROG, message))


def permanent_status(code):
    """4xx means the content is gone for good; 5xx and timeouts are transient."""
    if not is_integer(code):
        return False
    if code in (408, 425, 429):
        return False
    return 400 <= code < 500


def close_quietly(handle):
    close = getattr(handle, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def response_content_type(response):
    headers = getattr(response, "headers", None)
    if headers is None:
        info = getattr(response, "info", None)
        headers = info() if callable(info) else None
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    return getter("Content-Type") or getter("content-type")


def sanitize_extension(text):
    kept = "".join(ch for ch in text if ch.isalnum() or ch in "-_")
    return kept.strip("-_")


def extension_for(content_type):
    """The stored file's extension, derived from the HTTP `Content-Type`."""
    if not is_string(content_type):
        return DEFAULT_EXTENSION
    base = content_type.split(";", 1)[0].strip().lower()
    if not base:
        return DEFAULT_EXTENSION
    if base in CONTENT_TYPE_EXTENSIONS:
        return CONTENT_TYPE_EXTENSIONS[base]
    guessed = mimetypes.guess_extension(base)
    if guessed:
        return guessed
    subtype = sanitize_extension(base.rsplit("/", 1)[-1])
    return "." + subtype if subtype else DEFAULT_EXTENSION


def request_asset(url):
    """One HTTP GET; returns (body, content-type) or raises DownloadError."""
    try:
        response = urllib.request.urlopen(url)
    except urllib.error.HTTPError as exc:
        code = getattr(exc, "code", None)
        close_quietly(exc)
        raise DownloadError("HTTP %s" % code, permanent_status(code))
    except Exception as exc:                      # URLError, socket errors, ...
        raise DownloadError(str(exc) or exc.__class__.__name__, False)
    try:
        body = response.read()
        content_type = response_content_type(response)
    except Exception as exc:
        raise DownloadError(str(exc) or exc.__class__.__name__, False)
    finally:
        close_quietly(response)
    if isinstance(body, str):
        body = body.encode("utf-8")
    return body, content_type


def fetch_asset(url, attempts=DOWNLOAD_ATTEMPTS):
    """Retry transient failures; permanent ones are raised on the first try."""
    failure = None
    for attempt in range(attempts):
        try:
            return request_asset(url)
        except DownloadError as exc:
            if exc.permanent:
                raise
            failure = exc
            if RETRY_DELAY and attempt + 1 < attempts:
                time.sleep(RETRY_DELAY)
    raise failure


def is_partial(name):
    return name.endswith(PARTIAL_SUFFIX)


def stored_media_names(directory):
    """Names already in `<vault>/media/`, ignoring partial-download artifacts."""
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    return [name for name in names if not is_partial(name)]


def clear_partials(directory, entry_id):
    """Drop stale `.part` artifacts left by earlier interrupted downloads."""
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if is_partial(name) and entry_id in name:
            remove_quietly(os.path.join(directory, name))


def store_asset(directory, entry_id, extension, body):
    """Write through a `.part` file so a crash never leaves a truncated asset."""
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        raise DownloadError("could not create %s (%s)" % (directory, exc), True)
    filename = entry_id + extension
    partial = os.path.join(directory, filename + PARTIAL_SUFFIX)
    final = os.path.join(directory, filename)
    try:
        with open(partial, "wb") as handle:
            handle.write(body)
        os.replace(partial, final)
    except OSError as exc:
        remove_quietly(partial)
        raise DownloadError("could not write %s (%s)" % (final, exc), True)
    clear_partials(directory, entry_id)
    return filename


def asset_url(base, kind, entry_id, extension=""):
    return "%s/%s/%s%s" % (base, kind, entry_id, extension)


def download_entry(base, entry_id, media_dir, preview_dir, override):
    """Media then preview for one entry; warns and returns None on failure."""
    suffix = "." + override if override else ""
    media_url = asset_url(base, "media", entry_id, suffix)
    try:
        body, content_type = fetch_asset(media_url)
    except DownloadError as exc:
        warn("skipped media for entry %s: %s (%s)" % (entry_id, media_url, exc))
        return None
    extension = suffix if override else extension_for(content_type)
    try:
        stored = store_asset(media_dir, entry_id, extension, body)
    except DownloadError as exc:
        warn("skipped media for entry %s: %s" % (entry_id, exc))
        return None

    preview_url = asset_url(base, "preview", entry_id)
    try:
        body, content_type = fetch_asset(preview_url)
    except DownloadError as exc:
        warn("skipped preview for entry %s: %s (%s)"
             % (entry_id, preview_url, exc))
        return stored
    try:
        store_asset(preview_dir, entry_id, extension_for(content_type), body)
    except DownloadError as exc:
        warn("skipped preview for entry %s: %s" % (entry_id, exc))
    return stored


def download_phase(name, catalog, limits, override):
    """Fetch media and previews for candidate entries, category by category."""
    base = catalog.get("source")
    if not is_string(base):
        return
    base = base.rstrip("/")
    media_dir = os.path.join(name, MEDIA_DIR)
    preview_dir = os.path.join(name, PREVIEW_DIR)
    stored = stored_media_names(media_dir)
    for category in CATEGORIES:
        limit = limits.get(category)
        taken = 0
        for entry in catalog.get(category) or []:
            if limit is not None and taken >= limit:
                break
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id")
            if not is_string(entry_id) or not entry_id:
                continue
            if any(entry_id in existing for existing in stored):
                continue
            taken += 1
            filename = download_entry(
                base, entry_id, media_dir, preview_dir, override)
            if filename is not None:
                stored.append(filename)


# --------------------------------------------------------------------------
# digest
# --------------------------------------------------------------------------

def epoch_order_key(key):
    """v1 keys order by the number they spell, not by their text."""
    try:
        return (1, int(str(key).strip()), str(key))
    except (TypeError, ValueError):
        return (0, 0, str(key))


def ordered_values(history, numeric):
    """History values oldest-first under the version's key ordering."""
    if not isinstance(history, dict) or not history:
        return []
    keys = sorted(history, key=epoch_order_key if numeric else str)
    return [history[key] for key in keys]


def digest_fields(version):
    """`removed` is only a tracked field where the format actually has one."""
    return TRACKED_FIELDS if version == CATALOG_VERSION else SOURCE_TRACKED_FIELDS


def digest_entries(items):
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def digest_sections(name):
    """(version, source URL, [(label, entries)]) read without migrating."""
    raw = read_catalog_file(name)
    version = detect_version(name, raw)
    if version == 1:
        source_id = raw.get("source_id")
        if not is_string(source_id):
            raise invalid_vault(name, "missing or non-string source_id")
        return (version, v1_source_url(source_id),
                [(V1_GROUP_LABEL, digest_entries(raw.get("entries")))])
    source = raw.get("source")
    if not is_string(source):
        raise invalid_vault(name, "missing or non-string source URL")
    sections = [(label, digest_entries(raw.get(key)))
                for key, label in CATEGORY_LABELS]
    return version, source, sections


def entry_title(item, values):
    title = values["title"][-1] if values.get("title") else None
    if is_string(title) and title:
        return title
    entry_id = item.get("id")
    return entry_id if is_string(entry_id) and entry_id else UNTITLED


def classify_entry(item, version, numeric):
    """(group, title, changed-field labels); group is None when unremarkable."""
    fields = digest_fields(version)
    values = {field: ordered_values(item.get(field), numeric) for field in fields}
    title = entry_title(item, values)

    removed = values.get("removed") or []
    if removed:
        latest = removed[-1]
        prior = removed[-2] if len(removed) > 1 else None
        if latest is True and (len(removed) == 1 or prior is False):
            return REMOVALS_GROUP, title, []

    if all(len(values[field]) <= 1 for field in fields):
        return ADDITIONS_GROUP, title, []

    changed = []
    reappeared = False
    for field in fields:
        series = values[field]
        if len(series) < 2 or same_value(series[-1], series[-2]):
            continue
        if field == "removed":
            reappeared = series[-1] is False and series[-2] is True
            continue
        changed.append(field)
    if reappeared:
        changed.append(REAPPEARED_LABEL)
    if changed:
        return UPDATES_GROUP, title, changed
    return None, title, []


def digest_lines(name, version, source, sections):
    numeric = version == 1
    lines = []
    reported = False
    for label, items in sections:
        buckets = dict((group, []) for group in DIGEST_GROUPS)
        for item in items:
            group, title, changed = classify_entry(item, version, numeric)
            if group is not None:
                buckets[group].append((title, changed))
        if not any(buckets[group] for group in DIGEST_GROUPS):
            continue                              # empty category is omitted
        reported = True
        lines.append(label)
        for group in DIGEST_GROUPS:
            if not buckets[group]:
                continue
            lines.append("  " + group)
            for title, changed in buckets[group]:
                suffix = " (%s)" % ", ".join(changed) if changed else ""
                lines.append("    - %s%s" % (title, suffix))
    if not reported:
        lines.append(NO_CHANGES_TEXT)
    lines.append("Digest of vault %s: catalog version %d, source %s"
                 % (name, version, source))
    return lines


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def command_init(args):
    name = args.name
    if os.path.exists(name):
        raise MvaultError("vault already exists: %s" % name)
    try:
        os.makedirs(name)
    except OSError as exc:
        raise MvaultError("could not create vault %s (%s)" % (name, exc))
    write_catalog(name, new_catalog(args.url))
    return 0


def command_migrate(args):
    name = args.name
    catalog, version = load_vault(name)
    if version == CATALOG_VERSION:
        # Already native: no rewrite, and therefore no backup either.
        return 0
    write_catalog(name, catalog)
    return 0


def nonnegative_int(text):
    """A category limit: a plain non-negative integer, nothing else."""
    try:
        value = int(text)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(
            "not a non-negative integer: %r" % (text,))
    if value < 0:
        raise argparse.ArgumentTypeError(
            "not a non-negative integer: %r" % (text,))
    return value


def normalize_format(text):
    """The `--format` override, without a leading dot; empty means no override."""
    if not is_string(text):
        return None
    cleaned = text.strip().lstrip(".")
    return cleaned or None


def report_summary(counts):
    sys.stdout.write("Sync summary: added %d, removed %d, updated %d\n"
                     % (counts["added"], counts["removed"], counts["updated"]))


def command_sync(args):
    name = args.name
    limits = {"episodes": args.episodes,
              "streams": args.streams,
              "clips": args.clips}
    override = normalize_format(args.format)
    # A v1/v2 catalog is migrated in memory here; the metadata phase's write
    # backs up the original pre-migration catalog and stores the v3 result.
    # With --skip-metadata nothing is written, so a legacy vault stays legacy
    # while the download phase still works off the migrated v3 view.
    catalog = load_catalog(name)
    if not args.skip_metadata:
        # Fetching and validating happens before any write, so a failed sync
        # leaves the vault unchanged.
        source = fetch_source(catalog["source"])
        stamp = sync_timestamp(catalog)
        counts = update_catalog(catalog, source, stamp)
        write_catalog(name, catalog)
        report_summary(counts)
    if not args.skip_download:
        # Download failures are warnings only; the run still succeeds.
        download_phase(name, catalog, limits, override)
    return 0


def command_digest(args):
    name = args.name
    version, source, sections = digest_sections(name)
    for line in digest_lines(name, version, source, sections):
        sys.stdout.write(line + "\n")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Create local vaults for media-platform metadata and "
                    "record tracked-field history by sync timestamp.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<subcommand>")

    init_parser = subparsers.add_parser(
        "init", help="create a new vault with an empty catalog")
    init_parser.add_argument("name", help="vault directory to create")
    init_parser.add_argument("url", help="source metadata URL")
    init_parser.set_defaults(func=command_init)

    sync_parser = subparsers.add_parser(
        "sync", help="fetch source metadata, update a vault, download media")
    sync_parser.add_argument("name", help="existing vault directory")
    for category in CATEGORIES:
        sync_parser.add_argument(
            "--%s" % category, type=nonnegative_int, default=None, metavar="<n>",
            help="maximum number of %s media downloads" % category)
    sync_parser.add_argument(
        "--skip-metadata", action="store_true", dest="skip_metadata",
        help="skip the source fetch and metadata update")
    sync_parser.add_argument(
        "--skip-download", action="store_true", dest="skip_download",
        help="skip the download phase")
    sync_parser.add_argument(
        "--format", default=None, metavar="<str>", dest="format",
        help="override the media download format and output extension")
    sync_parser.set_defaults(func=command_sync)

    digest_parser = subparsers.add_parser(
        "digest", help="summarize notable changes recorded in a vault")
    digest_parser.add_argument("name", help="existing vault directory")
    digest_parser.set_defaults(func=command_digest)

    migrate_parser = subparsers.add_parser(
        "migrate", help="convert a legacy vault catalog to the v3 format")
    migrate_parser.add_argument("name", help="existing vault directory")
    migrate_parser.set_defaults(func=command_migrate)

    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not argv:
        parser.print_help(sys.stderr)
        return 2
    args = parser.parse_args(argv)
    if getattr(args, "func", None) is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        return args.func(args)
    except MvaultError as exc:
        sys.stderr.write("%s: error: %s\n" % (PROG, exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
