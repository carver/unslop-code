#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Creates local vaults for media-platform metadata and records tracked-field
history by sync timestamp.

Usage:
    python mvault.py init <name> <url>
    python mvault.py sync <name> [options]
    python mvault.py migrate <name>
    python mvault.py digest <name>
"""
import argparse
import json
import mimetypes
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

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
    """Apply fetched metadata and return this run's added/removed/updated counts.

    The buckets are disjoint by construction: an entry the source still lists
    is never a removal, and a freshly created entry has nothing to update.
    """
    counts = {"added": 0, "removed": 0, "updated": 0}
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
            elif update_entry(entry, item, moment):
                counts["updated"] += 1

        for entry in stored_entries:
            if isinstance(entry, dict) and entry.get("id") not in seen:
                if mark_removed(entry, moment):
                    counts["removed"] += 1

        catalog[category] = sort_entries(stored_entries)
    return counts


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

    Returns `(version, source_url, [(category_label, entries)], fields)`.
    """
    raw = read_catalog_file(name)
    version = catalog_version(name, raw)

    def array(value):
        return value if isinstance(value, list) else []

    if version == 1:
        source_id = raw.get("source_id")
        source = legacy_source_url(source_id if isinstance(source_id, str) else "")
        groups = [(DIGEST_V1_GROUP, array(raw.get("entries")))]
        return version, source, groups, HISTORY_FIELDS

    source = raw.get("source")
    source = source if isinstance(source, str) else ""
    groups = [(category.capitalize(), array(raw.get(category)))
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
    for label, entries in groups:
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
            buckets[group].append(text)

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
    if not skip_metadata:
        source_data = fetch_source(catalog["source"])
        moment = sync_timestamp(catalog)
        counts = apply_source(catalog, source_data, moment)
        # Persist before downloading: the metadata phase is durable even when
        # a later download fails (see AMBIGUITIES T27).
        save_catalog(name, catalog)

    if not skip_download:
        download_phase(name, catalog, limits or {}, fmt)

    if counts is not None:
        print("Sync summary: added %d, removed %d, updated %d"
              % (counts["added"], counts["removed"], counts["updated"]))
    return 0


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
