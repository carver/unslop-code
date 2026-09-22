#!/usr/bin/env python3
"""mvault - local vaults for media-platform metadata.

Creates a vault directory holding a ``catalog.json`` and records the history of
tracked fields (title, description, views, likes, preview, removed) keyed by the
timestamp of the sync that observed each value.
"""

import json
import mimetypes
import os
import shutil
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from html import escape
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"

VERSION = 3
SUPPORTED_VERSIONS = (1, 2, 3)
CATEGORIES = ("episodes", "streams", "clips")

# A version 1 catalog stores a short platform identifier instead of a full URL.
V1_SOURCE_TEMPLATE = "https://media.example.com/channel/%s"

STATIC_FIELDS = ("id", "published", "width", "height")
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)

TS_FORMAT = "%Y-%m-%dT%H:%M:%S"

# Download phase layout.  Media and preview files live beside catalog.json and
# are named after the entry id they belong to.
MEDIA_DIRNAME = "media"
PREVIEW_DIRNAME = "previews"
MEDIA_REMOTE = "media"
PREVIEW_REMOTE = "preview"

# A download is streamed into ``<name>.part`` and renamed into place, so an
# interrupted run never leaves a truncated file that looks complete.
PARTIAL_SUFFIX = ".part"

DOWNLOAD_ATTEMPTS = 3
RETRY_DELAY = 0.1

DEFAULT_EXTENSION = "bin"
CONTENT_TYPE_EXTENSIONS = {
    "video/mp4": "mp4",
    "video/mpeg": "mpeg",
    "video/webm": "webm",
    "video/quicktime": "mov",
    "video/x-matroska": "mkv",
    "video/x-msvideo": "avi",
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
    "application/json": "json",
    "application/octet-stream": "bin",
    "text/plain": "txt",
}

# Transient statuses are worth retrying; everything else in the 4xx range means
# the content is permanently unavailable for this run.
RETRYABLE_STATUSES = (408, 425, 429)

DIGEST_GROUPS = ("Removed", "Added", "Updated")
V1_CATEGORY_LABEL = "Entries"
CATEGORY_LABELS = {"episodes": "Episodes", "streams": "Streams", "clips": "Clips"}

USAGE = """usage: mvault.py <subcommand> [args...]

Local vaults for media-platform metadata.

subcommands:
  init <name> <url>   create a new vault named <name> tracking the source <url>
  sync <name>         fetch the vault source, record tracked-field changes and
                      download missing media and preview files
  migrate <name>      convert a legacy (version 1 or 2) catalog to version 3
  digest <name>       summarize notable changes recorded in a vault
  serve [<name>]      browse vaults in a local web viewer and open a browser,
                      where entry pages manage timecoded annotations (a legacy
                      vault migrates to version 3 as its first annotation lands)

serve options:
  --host=<host>       bind address of the viewer (default 127.0.0.1)
  --port=<port>       bind port of the viewer (default 8840)
  --no-browser        start the viewer without opening a browser

sync options:
  --episodes=<n>      download at most <n> missing episode media files
  --streams=<n>       download at most <n> missing stream media files
  --clips=<n>         download at most <n> missing clip media files
  --skip-metadata     skip the source fetch; run the download phase only
  --skip-download     skip the download phase; fetch and persist metadata only
  --format=<str>      request <str> media and store it with that extension

options:
  -h, --help          show this help message and exit
"""


class MvaultError(Exception):
    """Any failure that should be reported to stderr with a non-zero exit."""


class SourceError(MvaultError):
    """Source metadata fetch failure (network, decoding or schema problem)."""


class DownloadError(Exception):
    """A single media/preview download failed.

    ``transient`` failures are worth retrying (connection trouble, 5xx, 429);
    anything else means the content is permanently unavailable.
    """

    def __init__(self, reason, transient=False):
        Exception.__init__(self, reason)
        self.reason = reason
        self.transient = transient


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def is_int(value):
    """True for real integers - booleans are not accepted as integers."""
    return isinstance(value, int) and not isinstance(value, bool)


def format_timestamp(moment):
    return moment.strftime(TS_FORMAT)


def parse_timestamp(text):
    """Parse a history key / published value into a naive datetime.

    Accepts full ISO 8601 datetimes (with or without a timezone suffix) and
    date-only text, which normalizes to a ``00:00:00`` time component.
    """
    if not isinstance(text, str):
        raise ValueError("not a datetime string")

    raw = text.strip()
    if not raw:
        raise ValueError("empty datetime string")

    candidate = raw
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"

    try:
        moment = datetime.fromisoformat(candidate)
    except ValueError:
        moment = None
        for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                        "%Y-%m-%dT%H:%M", "%Y/%m/%d"):
            try:
                moment = datetime.strptime(candidate, pattern)
                break
            except ValueError:
                continue
        if moment is None:
            raise ValueError("unrecognized datetime text: %r" % text)

    if moment.tzinfo is not None:
        moment = moment.replace(tzinfo=None)
    return moment.replace(microsecond=0)


def normalize_published(text):
    """Normalize a published value to ``YYYY-MM-DDTHH:MM:SS``."""
    try:
        return format_timestamp(parse_timestamp(text))
    except ValueError:
        # Unparseable text is kept verbatim so no information is lost.
        return text


def history_keys(history):
    """History keys sorted chronologically."""
    if not isinstance(history, dict):
        return []

    def key(item):
        try:
            return (0, parse_timestamp(item), item)
        except ValueError:
            return (1, datetime.min, item)

    return sorted(history.keys(), key=key)


def latest_value(history, default=None):
    keys = history_keys(history)
    if not keys:
        return default
    return history[keys[-1]]


def latest_moment(history):
    """Newest timestamp in a history object, or ``None`` when empty."""
    newest = None
    if not isinstance(history, dict):
        return None
    for raw in history:
        try:
            moment = parse_timestamp(raw)
        except ValueError:
            continue
        if newest is None or moment > newest:
            newest = moment
    return newest


# --------------------------------------------------------------------------- #
# legacy catalog migration
# --------------------------------------------------------------------------- #

HISTORY_VALUE_CHECKS = {
    "title": (lambda v: isinstance(v, str), "must be a string"),
    "description": (lambda v: isinstance(v, str), "must be a string"),
    "views": (is_int, "must be an integer"),
    "likes": (lambda v: v is None or is_int(v), "must be an integer or null"),
    "preview": (lambda v: isinstance(v, str), "must be a string"),
}


def epoch_key_to_iso(key):
    """Convert a version 1 UNIX-epoch history key to ``YYYY-MM-DDTHH:MM:SS`` UTC."""
    if not isinstance(key, str):
        raise ValueError("history key is not a string")

    raw = key.strip()
    if not raw:
        raise ValueError("empty history key")

    try:
        seconds = int(raw, 10)
    except ValueError:
        raise ValueError("%r is not UNIX epoch seconds" % key)

    try:
        moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        raise ValueError("%r is out of range for UNIX epoch seconds" % key)
    return format_timestamp(moment.replace(tzinfo=None))


def migration_timestamp(now=None):
    """ISO 8601 timestamp stamped on history entries added by a migration."""
    return format_timestamp((now or datetime.now()).replace(microsecond=0))


def migrate_history(history, field, version, fail):
    """Return a version 3 history object for one legacy tracked field."""
    if not isinstance(history, dict):
        fail(field, "must be a history object")

    predicate, reason = HISTORY_VALUE_CHECKS[field]
    converted = []
    for key, value in history.items():
        if version == 1:
            try:
                stamp = epoch_key_to_iso(key)
            except ValueError as exc:
                fail(field, "has an invalid history key (%s)" % exc)
        else:
            try:
                parse_timestamp(key)
            except ValueError as exc:
                fail(field, "has an invalid history key (%s)" % exc)
            stamp = key
        if not predicate(value):
            fail(field, "has a history value that %s (got %r)" % (reason, value))
        converted.append((stamp, value))

    if version == 1:
        # Epoch keys order numerically; sort so the converted keys stay
        # chronological and any duplicates resolve to the newest observation.
        converted.sort(key=lambda item: (parse_timestamp(item[0]), item[0]))
    return dict(converted)


def migrate_entry(entry, category, version, stamp, vault):
    """Return a version 3 copy of one version 1 or version 2 entry."""
    if not isinstance(entry, dict):
        raise MvaultError("vault %r is invalid: malformed version %d entry in %r "
                          "(not an object)" % (vault, version, category))

    def fail(field, reason):
        raise MvaultError("vault %r is invalid: malformed version %d entry %r in %r: "
                          "field %r %s"
                          % (vault, version, entry.get("id"), category, field, reason))

    static_checks = (
        ("id", lambda v: isinstance(v, str), "must be a string"),
        ("published", lambda v: isinstance(v, str), "must be a string"),
        ("width", is_int, "must be an integer"),
        ("height", is_int, "must be an integer"),
    )
    for field, predicate, reason in static_checks:
        if field not in entry:
            fail(field, "is missing")
        if not predicate(entry[field]):
            fail(field, reason)

    migrated = dict(entry)
    for field in SOURCE_TRACKED_FIELDS:
        if field not in entry:
            fail(field, "is missing")
        migrated[field] = migrate_history(entry[field], field, version, fail)

    # Legacy entries carry neither of these; both are mandatory in version 3.
    if "removed" not in migrated:
        migrated["removed"] = {stamp: False}
    if "annotations" not in migrated:
        migrated["annotations"] = []
    return migrated


def legacy_categories(vault, catalog, version):
    """Return ``{category: [raw entry, ...]}`` for a legacy catalog."""
    if version == 1:
        entries = catalog.get("entries")
        if entries is None:
            entries = []
        if not isinstance(entries, list):
            raise MvaultError("vault %r is invalid: version 1 %r is not a list"
                              % (vault, "entries"))
        # Every version 1 entry migrates into the episodes category.
        return {"episodes": entries, "streams": [], "clips": []}

    raw = {}
    for category in CATEGORIES:
        items = catalog.get(category)
        if items is None:
            items = []
        if not isinstance(items, list):
            raise MvaultError("vault %r is invalid: version %d %r category is not "
                              "a list" % (vault, version, category))
        raw[category] = items
    return raw


def legacy_source(vault, catalog, version):
    """Resolve the full source URL of a legacy catalog."""
    if version == 1:
        source_id = catalog.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise MvaultError("vault %r is invalid: version 1 catalog is missing "
                              "source_id" % vault)
        return V1_SOURCE_TEMPLATE % source_id

    source = catalog.get("source")
    if not isinstance(source, str):
        raise MvaultError("vault %r is invalid: missing source URL" % vault)
    return source


def migrate_catalog(vault, catalog, version, stamp=None):
    """Return a version 3 catalog built from a version 1 or 2 catalog."""
    stamp = stamp or migration_timestamp()

    source = legacy_source(vault, catalog, version)
    raw = legacy_categories(vault, catalog, version)

    migrated = {"version": VERSION, "source": source}
    for category in CATEGORIES:
        migrated[category] = [migrate_entry(item, category, version, stamp, vault)
                              for item in raw[category]]

    # Anything else the legacy catalog carried is local-only data; keep it.
    replaced = set(CATEGORIES) | {"version", "source", "source_id", "entries"}
    for key, value in catalog.items():
        if key not in replaced:
            migrated[key] = value
    return migrated


def catalog_version(vault, catalog):
    """Validate and return the ``version`` field of a catalog document."""
    if "version" not in catalog:
        raise MvaultError("vault %r is invalid: %s is missing the version field"
                          % (vault, CATALOG_NAME))

    version = catalog["version"]
    if not is_int(version):
        raise MvaultError("vault %r is invalid: catalog version must be an integer "
                          "(got %r)" % (vault, version))
    if version not in SUPPORTED_VERSIONS:
        raise MvaultError("vault %r is invalid: unsupported catalog version %d "
                          "(supported versions: %s)"
                          % (vault, version,
                             ", ".join(str(known) for known in SUPPORTED_VERSIONS)))
    return version


# --------------------------------------------------------------------------- #
# vault io
# --------------------------------------------------------------------------- #

def catalog_path(name):
    return os.path.join(name, CATALOG_NAME)


def backup_path(name):
    return os.path.join(name, BACKUP_NAME)


def load_catalog(name):
    """Load the catalog of an existing vault as a version 3 document.

    Returns ``(catalog, version)`` where ``catalog`` is always in the native
    version 3 shape and ``version`` is the version found on disk.  Legacy
    catalogs are migrated in memory only - nothing is written here, so
    read-only commands never rewrite ``catalog.json``.
    """
    path = catalog_path(name)
    if not os.path.isdir(name):
        raise MvaultError("vault %r does not exist" % name)
    if not os.path.isfile(path):
        raise MvaultError("vault %r is invalid: missing %s" % (name, CATALOG_NAME))

    try:
        with open(path, "r", encoding="utf-8") as handle:
            catalog = json.load(handle)
    except (OSError, ValueError) as exc:
        raise MvaultError("vault %r is invalid: unreadable %s (%s)"
                          % (name, CATALOG_NAME, exc))

    if not isinstance(catalog, dict):
        raise MvaultError("vault %r is invalid: %s is not a JSON object"
                          % (name, CATALOG_NAME))

    version = catalog_version(name, catalog)
    if version != VERSION:
        catalog = migrate_catalog(name, catalog, version)

    if not isinstance(catalog.get("source"), str):
        raise MvaultError("vault %r is invalid: missing source URL" % name)
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise MvaultError("vault %r is invalid: missing %r category"
                              % (name, category))
    for entry in all_entries(catalog):
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise MvaultError("vault %r is invalid: malformed entry" % name)
    return catalog, version


def all_entries(catalog):
    for category in CATEGORIES:
        for entry in catalog.get(category) or []:
            yield entry


def write_catalog(name, catalog):
    """Write the catalog, backing up any pre-existing copy byte-for-byte.

    The backup is taken first, so a failure to write it aborts before the
    on-disk ``catalog.json`` is touched.
    """
    path = catalog_path(name)
    if os.path.isfile(path):
        try:
            shutil.copyfile(path, backup_path(name))
        except OSError as exc:
            raise MvaultError("vault %r: cannot write %s (%s)"
                              % (name, BACKUP_NAME, exc))

    payload = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload)
            # Flush to disk: the catalog is durably saved before sync moves on
            # to the download phase, which may fail entry by entry.
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise MvaultError("vault %r: cannot write %s (%s)"
                          % (name, CATALOG_NAME, exc))


# --------------------------------------------------------------------------- #
# source fetching
# --------------------------------------------------------------------------- #

def fetch_source(url):
    """HTTP GET the source URL and return the decoded JSON document."""
    if not isinstance(url, str) or not url:
        raise SourceError("source metadata fetch failed: missing source URL")

    try:
        body = http_get(url)
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError("source metadata fetch failed for %s: %s" % (url, exc))

    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceError("source metadata fetch failed for %s: %s" % (url, exc))

    try:
        return json.loads(body)
    except ValueError as exc:
        raise SourceError("source metadata fetch failed for %s: invalid JSON (%s)"
                          % (url, exc))


def http_get(url):
    """Perform the GET, preferring ``requests`` when it is installed."""
    try:
        import requests  # noqa: WPS433 (optional dependency)
    except ImportError:
        requests = None

    if requests is not None:
        response = requests.get(url)
        raise_for_status = getattr(response, "raise_for_status", None)
        if callable(raise_for_status):
            raise_for_status()
        text = getattr(response, "text", None)
        if text is not None:
            return text
        return response.content

    from urllib.request import urlopen

    with urlopen(url) as response:
        return response.read()


def parse_source(document):
    """Validate the source document and return ``{category: [entry, ...]}``."""
    if not isinstance(document, dict):
        raise SourceError("source metadata fetch failed: "
                          "expected a JSON object at the document root")

    parsed = {}
    for category in CATEGORIES:
        items = document.get(category)
        if not isinstance(items, list):
            raise SourceError("source metadata fetch failed: "
                              "missing or invalid %r array" % category)
        parsed[category] = [validate_source_entry(item, category) for item in items]
    return parsed


def validate_source_entry(item, category):
    """Validate one source entry, returning a normalized copy."""
    if not isinstance(item, dict):
        raise SourceError("source metadata fetch failed: "
                          "malformed entry in %r (not an object)" % category)

    def fail(field, reason):
        raise SourceError("source metadata fetch failed: malformed entry %r in %r: "
                          "field %r %s" % (item.get("id"), category, field, reason))

    checks = (
        ("id", lambda v: isinstance(v, str), "must be a string"),
        ("published", lambda v: isinstance(v, str), "must be a string"),
        ("width", is_int, "must be an integer"),
        ("height", is_int, "must be an integer"),
        ("title", lambda v: isinstance(v, str), "must be a string"),
        ("description", lambda v: isinstance(v, str), "must be a string"),
        ("views", is_int, "must be an integer"),
        ("likes", lambda v: v is None or is_int(v), "must be an integer or null"),
        ("preview", lambda v: isinstance(v, str), "must be a string"),
    )
    for field, predicate, reason in checks:
        if field not in item:
            fail(field, "is missing")
        if not predicate(item[field]):
            fail(field, reason)

    entry = {
        "id": item["id"],
        "published": normalize_published(item["published"]),
        "width": item["width"],
        "height": item["height"],
    }
    for field in SOURCE_TRACKED_FIELDS:
        entry[field] = item[field]
    return entry


# --------------------------------------------------------------------------- #
# download phase
# --------------------------------------------------------------------------- #

def join_url(source, *parts):
    """Join a source URL with remote path segments using single slashes."""
    base = str(source or "").rstrip("/")
    return "/".join([base] + [str(part).strip("/") for part in parts])


def is_transient_status(status):
    """True when an HTTP status is worth retrying."""
    if not is_int(status):
        return True
    return status >= 500 or status in RETRYABLE_STATUSES


def extension_for(content_type):
    """Derive a media extension from an HTTP ``Content-Type`` header."""
    if not isinstance(content_type, str):
        return DEFAULT_EXTENSION

    value = content_type.split(";")[0].strip().lower()
    if not value:
        return DEFAULT_EXTENSION
    if value in CONTENT_TYPE_EXTENSIONS:
        return CONTENT_TYPE_EXTENSIONS[value]

    guessed = mimetypes.guess_extension(value)
    if guessed:
        return guessed.lstrip(".")

    # "video/x-fancy" -> "fancy": the subtype is the best remaining hint.
    subtype = value.partition("/")[2].strip()
    if subtype.startswith("x-"):
        subtype = subtype[2:]
    subtype = subtype.split("+")[0]
    if subtype and all(ch.isalnum() or ch in "-_" for ch in subtype):
        return subtype
    return DEFAULT_EXTENSION


def http_download(url):
    """GET ``url`` and return ``(content, content_type)``.

    Any successful response is treated as downloadable content; only the
    ``Content-Type`` header is inspected, and only to pick an extension.
    """
    try:
        import requests  # noqa: WPS433 (optional dependency)
    except ImportError:
        requests = None

    if requests is not None:
        try:
            response = requests.get(url)
        except Exception as exc:
            raise DownloadError(str(exc) or exc.__class__.__name__, transient=True)

        status = getattr(response, "status_code", 200)
        if is_int(status) and status >= 400:
            raise DownloadError("HTTP %d" % status,
                                transient=is_transient_status(status))

        headers = getattr(response, "headers", None) or {}
        getter = getattr(headers, "get", None)
        content_type = getter("Content-Type") if callable(getter) else None
        content = getattr(response, "content", None)
        if content is None:
            content = b""
        if isinstance(content, str):
            content = content.encode("utf-8")
        return content, content_type

    from urllib.error import HTTPError, URLError
    from urllib.request import urlopen

    try:
        with urlopen(url) as response:
            content = response.read()
            content_type = response.headers.get("Content-Type")
            return content, content_type
    except HTTPError as exc:
        raise DownloadError("HTTP %d" % exc.code,
                            transient=is_transient_status(exc.code))
    except URLError as exc:
        raise DownloadError(str(exc.reason), transient=True)
    except Exception as exc:
        raise DownloadError(str(exc) or exc.__class__.__name__, transient=True)


def download_with_retries(url):
    """Download ``url``, retrying transient failures.

    Returns ``(content, content_type)`` or raises the final ``DownloadError``.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return http_download(url)
        except DownloadError as exc:
            if not exc.transient or attempt >= DOWNLOAD_ATTEMPTS:
                exc.attempts = attempt
                raise
            if RETRY_DELAY:
                time.sleep(RETRY_DELAY)


def warn(message):
    sys.stderr.write("warning: %s\n" % message)


def stored_filename(directory, entry_id):
    """Name of the file already stored for ``entry_id``, or ``None``.

    Partial-download artifacts are ignored, so a stale ``.part`` file never
    hides a missing download.
    """
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return None

    for name in names:
        if name.endswith(PARTIAL_SUFFIX):
            continue
        if name != entry_id and not name.startswith(entry_id + "."):
            continue
        if os.path.isfile(os.path.join(directory, name)):
            return name
    return None


def save_download(directory, filename, content):
    """Write ``content`` to ``directory/filename`` via a partial artifact."""
    try:
        if not os.path.isdir(directory):
            os.makedirs(directory)
        partial = os.path.join(directory, filename + PARTIAL_SUFFIX)
        with open(partial, "wb") as handle:
            handle.write(content)
        # Rename last: the final name only ever appears once it is complete.
        os.replace(partial, os.path.join(directory, filename))
    except OSError as exc:
        raise DownloadError("cannot write %s (%s)" % (filename, exc))


def download_asset(vault, kind, entry_id, url, directory, extension=None):
    """Fetch one asset, warning and returning False when it cannot be stored."""
    try:
        content, content_type = download_with_retries(url)
    except DownloadError as exc:
        attempts = getattr(exc, "attempts", 1)
        if exc.transient and attempts > 1:
            warn("vault %s: %s download for %s failed after %d attempts (%s); "
                 "skipping" % (vault, kind, entry_id, attempts, exc.reason))
        else:
            warn("vault %s: %s download for %s is unavailable (%s); skipping"
                 % (vault, kind, entry_id, exc.reason))
        return False

    suffix = extension if extension else extension_for(content_type)
    filename = "%s.%s" % (entry_id, suffix) if suffix else entry_id
    try:
        save_download(directory, filename, content)
    except DownloadError as exc:
        warn("vault %s: %s download for %s could not be stored (%s); skipping"
             % (vault, kind, entry_id, exc.reason))
        return False
    return True


def download_candidates(catalog, category, media_dir, limit):
    """Entries of ``category`` still missing media, in catalog order."""
    if limit == 0:
        return []

    candidates = []
    for entry in catalog.get(category) or []:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            continue
        if stored_filename(media_dir, entry_id) is not None:
            continue
        candidates.append(entry_id)
        if limit is not None and len(candidates) >= limit:
            break
    return candidates


def download_phase(name, catalog, options):
    """Fetch missing media (and matching previews) for every category."""
    media_dir = os.path.join(name, MEDIA_DIRNAME)
    preview_dir = os.path.join(name, PREVIEW_DIRNAME)
    source = catalog.get("source")
    override = options.get("format")

    stored = 0
    for category in CATEGORIES:
        limit = options["limits"].get(category)
        for entry_id in download_candidates(catalog, category, media_dir, limit):
            remote = entry_id + ("." + override if override else "")
            media_url = join_url(source, MEDIA_REMOTE, remote)
            if not download_asset(name, "media", entry_id, media_url, media_dir,
                                  extension=override):
                continue
            stored += 1
            if stored_filename(preview_dir, entry_id) is None:
                preview_url = join_url(source, PREVIEW_REMOTE, entry_id)
                download_asset(name, "preview", entry_id, preview_url, preview_dir)
    return stored


# --------------------------------------------------------------------------- #
# sync logic
# --------------------------------------------------------------------------- #

def sync_timestamp(catalog, now=None):
    """The timestamp used for every history entry appended by this sync.

    Always strictly newer than every timestamp already recorded in the catalog,
    so repeated syncs within the same second still advance.
    """
    moment = (now or datetime.now()).replace(microsecond=0)
    newest = None
    for entry in all_entries(catalog):
        for field in TRACKED_FIELDS:
            candidate = latest_moment(entry.get(field))
            if candidate is not None and (newest is None or candidate > newest):
                newest = candidate
    if newest is not None and moment <= newest:
        moment = newest + timedelta(seconds=1)
    return format_timestamp(moment)


def record(entry, field, value, stamp):
    """Append ``value`` to a tracked field when it differs from the current one."""
    history = entry.get(field)
    if not isinstance(history, dict):
        history = {}
        entry[field] = history

    if history:
        current = latest_value(history)
        if current == value and type(current) is type(value):
            return False

    history[stamp] = value
    return True


def sort_entries(entries):
    """Newest ``published`` first, ties broken by lexicographically smaller id."""
    ordered = sorted(entries, key=lambda entry: str(entry.get("id") or ""))
    return sorted(ordered, key=lambda entry: str(entry.get("published") or ""),
                  reverse=True)


def apply_source(catalog, source, stamp, changes=None):
    """Merge fetched source entries into the catalog in place.

    Returns ``{"added": n, "removed": n, "updated": n}`` describing what this
    sync changed.  An entry is counted once, newest-state first: a fresh entry
    is an addition, an entry that just disappeared is a removal, and anything
    else with a changed tracked field is an update.

    When ``changes`` is a dict it is filled with the entries behind those
    counts, as ``{category: {group: [(entry, changed fields), ...]}}``, so the
    caller can report them line by line.
    """
    counts = {"added": 0, "removed": 0, "updated": 0}

    for category in CATEGORIES:
        entries = catalog.get(category) or []
        by_id = {}
        for entry in entries:
            by_id.setdefault(entry["id"], entry)

        known = set(by_id)
        seen = set()
        added = []
        removed = []
        changed = {}
        for item in source[category]:
            seen.add(item["id"])
            entry = by_id.get(item["id"])
            fresh = entry is None
            if fresh:
                entry = {field: item[field] for field in STATIC_FIELDS}
                entries.append(entry)
                by_id[item["id"]] = entry
                added.append(entry)
            touched = []
            for field in SOURCE_TRACKED_FIELDS:
                if record(entry, field, item[field], stamp):
                    touched.append(field)
            if record(entry, "removed", False, stamp):
                touched.append("removed")
            if touched and item["id"] in known:
                changed[item["id"]] = (entry, touched)

        counts["added"] += len(seen - known)

        for entry in entries:
            if entry["id"] not in seen and record(entry, "removed", True, stamp):
                counts["removed"] += 1
                changed.pop(entry["id"], None)
                removed.append(entry)

        counts["updated"] += len(changed)
        catalog[category] = sort_entries(entries)

        if changes is not None:
            changes[category] = {
                "Removed": [(entry, []) for entry in removed],
                "Added": [(entry, []) for entry in added],
                "Updated": list(changed.values()),
            }

    return counts


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def command_init(args):
    if len(args) != 2:
        raise MvaultError("usage: mvault.py init <name> <url>")
    name, url = args

    if os.path.exists(name):
        raise MvaultError("cannot create vault %r: %s already exists" % (name, name))

    try:
        os.makedirs(name)
    except OSError as exc:
        raise MvaultError("cannot create vault %r: %s" % (name, exc))

    catalog = {"version": VERSION, "source": url,
               "episodes": [], "streams": [], "clips": []}
    write_catalog(name, catalog)
    print("initialized vault %s tracking %s" % (name, url))
    return 0


def parse_limit(option, value):
    """Parse a ``--<category>=<n>`` download limit."""
    text = value.strip()
    if not text or not text.isdigit():
        raise MvaultError("option --%s expects a non-negative integer (got %r)"
                          % (option, value))
    try:
        return int(text, 10)
    except ValueError:
        raise MvaultError("option --%s expects a non-negative integer (got %r)"
                          % (option, value))


def parse_sync_args(args):
    """Return ``(name, options)`` for the sync subcommand.

    Every option is validated here so a bad command line aborts before any
    vault is read, fetched or written.
    """
    options = {"limits": dict.fromkeys(CATEGORIES),
               "skip_metadata": False, "skip_download": False, "format": None}
    positional = []

    for arg in args:
        if not arg.startswith("-") or arg == "-":
            positional.append(arg)
            continue
        if not arg.startswith("--"):
            raise MvaultError("unrecognized option %r" % arg)

        name, sep, value = arg[2:].partition("=")
        key = name.replace("-", "_")
        if key in CATEGORIES and sep:
            options["limits"][key] = parse_limit(name, value)
        elif key == "format" and sep:
            if not value:
                raise MvaultError("option --format expects a format string")
            options["format"] = value
        elif key == "skip_metadata" and not sep:
            options["skip_metadata"] = True
        elif key == "skip_download" and not sep:
            options["skip_download"] = True
        else:
            raise MvaultError("unrecognized option %r" % arg)

    if len(positional) != 1:
        raise MvaultError("usage: mvault.py sync <name> [options]")
    return positional[0], options


def command_sync(args):
    name, options = parse_sync_args(args)

    # A legacy catalog is migrated in memory here; the version 3 result is what
    # gets synced and written back below (the backup keeps the original).
    catalog, _version = load_catalog(name)

    if options["skip_metadata"]:
        print("synced vault %s (metadata phase skipped)" % name)
    else:
        source = parse_source(fetch_source(catalog["source"]))

        catalog["version"] = VERSION
        stamp = sync_timestamp(catalog)
        changes = {}
        counts = apply_source(catalog, source, stamp, changes)
        # Persist before the download phase: metadata is durably saved even
        # when a later download fails.
        write_catalog(name, catalog)

        total = sum(len(catalog[category]) for category in CATEGORIES)
        print("synced vault %s at %s (%d entries)" % (name, stamp, total))
        print("changes: %d added, %d removed, %d updated"
              % (counts["added"], counts["removed"], counts["updated"]))
        # The catalog is version 3 by the time it is written, so every changed
        # entry is linked through the category it now lives in.
        for line in sync_change_lines(name, changes):
            print(line)

    if not options["skip_download"]:
        download_phase(name, catalog, options)
    return 0


def command_migrate(args):
    if len(args) != 1:
        raise MvaultError("usage: mvault.py migrate <name>")
    name = args[0]

    catalog, version = load_catalog(name)
    if version == VERSION:
        print("vault %s is already at version %d" % (name, VERSION))
        return 0

    write_catalog(name, catalog)
    print("migrated vault %s from version %d to version %d"
          % (name, version, VERSION))
    return 0


# --------------------------------------------------------------------------- #
# digest
# --------------------------------------------------------------------------- #

def load_raw_catalog(name):
    """Load a catalog exactly as stored, without migrating it.

    ``digest`` reads vaults of any supported version in their own shape, so it
    never rewrites ``catalog.json`` (and never leaves a ``catalog.bak``).
    """
    path = catalog_path(name)
    if not os.path.isdir(name):
        raise MvaultError("vault %r does not exist" % name)
    if not os.path.isfile(path):
        raise MvaultError("vault %r is invalid: missing %s" % (name, CATALOG_NAME))

    try:
        with open(path, "r", encoding="utf-8") as handle:
            catalog = json.load(handle)
    except (OSError, ValueError) as exc:
        raise MvaultError("vault %r is invalid: unreadable %s (%s)"
                          % (name, CATALOG_NAME, exc))

    if not isinstance(catalog, dict):
        raise MvaultError("vault %r is invalid: %s is not a JSON object"
                          % (name, CATALOG_NAME))

    return catalog, catalog_version(name, catalog)


def digest_tracked_fields(version):
    """Tracked fields available in a catalog of ``version``."""
    if version >= 3:
        return TRACKED_FIELDS
    # Version 1 and 2 entries carry no ``removed`` field at all.
    return SOURCE_TRACKED_FIELDS


def digest_history_keys(history, version):
    """History keys of one field, oldest first, ordered the version's way.

    Version 1 keys are UNIX-epoch strings and only order correctly when they
    are compared numerically; version 2 and 3 use ISO 8601 text, which orders
    lexicographically.
    """
    if not isinstance(history, dict):
        return []

    if version == 1:
        def key(item):
            try:
                return (0, int(str(item).strip(), 10), str(item))
            except ValueError:
                return (1, 0, str(item))
        return sorted(history.keys(), key=key)

    return sorted(history.keys(), key=str)


def digest_current(entry, field, version, default=None):
    """Value of ``field`` at its latest history key."""
    history = entry.get(field)
    keys = digest_history_keys(history, version)
    if not keys:
        return default
    return history[keys[-1]]


def digest_categories(catalog, version):
    """``[(label, [entry, ...]), ...]`` in a deterministic order."""
    if version == 1:
        # Version 1 has no categories; everything lives in one flat list.
        return [(V1_CATEGORY_LABEL, catalog.get("entries") or [])]
    return [(CATEGORY_LABELS[category], catalog.get(category) or [])
            for category in CATEGORIES]


def digest_source(name, catalog, version):
    """Source URL of the catalog as loaded, per its own version rules."""
    return legacy_source(name, catalog, version)


def classify_entry(entry, version, fields):
    """Return ``(group, changed_fields)`` for one entry.

    Groups are exclusive and resolved by precedence: removals first, then
    additions, then field updates.  ``None`` means nothing notable happened.
    """
    histories = {}
    for field in fields:
        history = entry.get(field)
        if isinstance(history, dict):
            histories[field] = digest_history_keys(history, version)

    changed = []
    for field in fields:
        keys = histories.get(field) or []
        if len(keys) < 2:
            continue
        history = entry[field]
        if history[keys[-1]] != history[keys[-2]]:
            changed.append(field)

    if version >= 3:
        keys = histories.get("removed") or []
        if keys:
            history = entry["removed"]
            latest = history[keys[-1]]
            prior = history[keys[-2]] if len(keys) >= 2 else False
            if latest is True and prior is False:
                return "Removed", []

    if histories and all(len(keys) <= 1 for keys in histories.values()):
        return "Added", []
    if changed:
        return "Updated", changed
    return None, []


def digest_labels(fields):
    """Human-readable names for the changed fields of an update."""
    labels = ["reappeared"] if "removed" in fields else []
    labels.extend(field for field in fields if field != "removed")
    return labels


def digest_entry_text(entry, version, group, changed):
    """One digest line body: current title plus any changed field names."""
    title = digest_current(entry, "title", version)
    if not isinstance(title, str) or not title.strip():
        title = title if isinstance(title, str) else entry.get("id")
        if not isinstance(title, str) or not title.strip():
            title = str(entry.get("id"))

    labels = digest_labels(changed) if group == "Updated" else []
    if labels:
        return "%s (%s)" % (title, ", ".join(labels))
    return title


def report_lines(groups, label, entry_line):
    """Render one category block of a change report, or nothing when quiet."""
    if not any(groups.get(group) for group in DIGEST_GROUPS):
        return []  # a category with no notable changes is omitted

    lines = ["%s:" % label]
    for group in DIGEST_GROUPS:
        items = groups.get(group) or []
        if not items:
            continue
        lines.append("  %s:" % group)
        for entry, changed in items:
            lines.append("    - %s" % entry_line(entry, group, changed))
    return lines


def digest_lines(name, catalog, version):
    """Body of the digest report, one line per output row."""
    fields = digest_tracked_fields(version)
    lines = []

    for label, entries in digest_categories(catalog, version):
        # Version 1 reports its single "Entries" group; the rest are named
        # after the catalog categories, which are also the viewer routes.
        category = label.lower()
        grouped = {group: [] for group in DIGEST_GROUPS}
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                group, changed = classify_entry(entry, version, fields)
                if group is None:
                    continue
                grouped[group].append((entry, changed))

        def entry_line(entry, group, changed, category=category, version=version):
            return "%s %s" % (digest_entry_text(entry, version, group, changed),
                              viewer_link(name, category, entry.get("id")))

        lines.extend(report_lines(grouped, label, entry_line))
    return lines


def sync_change_lines(name, changes):
    """Post-sync report of the entries this sync added, removed or updated.

    The catalog is always version 3 once a sync has written it, so a version 1
    vault reports its migrated entries under the categories they landed in.
    """
    lines = []
    for category in CATEGORIES:
        def entry_line(entry, group, changed, category=category):
            return "%s %s" % (digest_entry_text(entry, VERSION, group, changed),
                              viewer_link(name, category, entry.get("id")))

        lines.extend(report_lines(changes.get(category) or {},
                                  CATEGORY_LABELS[category], entry_line))
    return lines


def command_digest(args):
    if len(args) != 1:
        raise MvaultError("usage: mvault.py digest <name>")
    name = args[0]

    catalog, version = load_raw_catalog(name)
    source = digest_source(name, catalog, version)

    lines = digest_lines(name, catalog, version)
    if not lines:
        lines = ["no notable changes found"]

    for line in lines:
        print(line)
    print("digest of vault %s (catalog version %d) from %s at %s"
          % (name, version, source,
             format_timestamp(datetime.now().replace(microsecond=0))))
    return 0


# --------------------------------------------------------------------------- #
# viewer links
# --------------------------------------------------------------------------- #

# The viewer is a local, single-user tool; links printed by the reporting
# commands point at the address ``serve`` binds by default.
VIEWER_SCHEME = "http"
VIEWER_HOST = "127.0.0.1"
VIEWER_PORT = 8840

# Version 1 catalogs keep every entry in one flat list instead of categories.
V1_CATEGORY = "entries"


def default_category(version):
    """Category the viewer opens for a vault of ``version``."""
    return V1_CATEGORY if version == 1 else CATEGORIES[0]


def valid_categories(version):
    """Categories a vault of ``version`` can be browsed by."""
    return (V1_CATEGORY,) if version == 1 else CATEGORIES


def category_entries(catalog, version, category):
    """Entries of ``category`` in the order they appear in ``catalog.json``."""
    key = V1_CATEGORY if version == 1 else category
    entries = catalog.get(key)
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def viewer_path(*parts):
    """Build a viewer URL path out of already-decoded segments."""
    return "/" + "/".join(quote(str(part), safe="") for part in parts)


def viewer_link(name, category, entry_id, host=VIEWER_HOST, port=VIEWER_PORT):
    """Absolute link to the viewer page for one entry."""
    return "%s://%s:%d%s" % (VIEWER_SCHEME, host, port,
                             viewer_path("catalog", name, category, entry_id))


def entry_title(entry, version, default=None):
    """Current title of an entry, falling back to its id."""
    title = digest_current(entry, "title", version)
    if isinstance(title, str) and title.strip():
        return title
    fallback = default if default is not None else entry.get("id")
    return fallback if isinstance(fallback, str) else str(fallback)


def media_filenames(name):
    """Names stored in ``<vault>/media/``, sorted for a stable page."""
    try:
        return sorted(os.listdir(os.path.join(name, MEDIA_DIRNAME)))
    except OSError:
        return []


def is_downloaded(media_names, entry_id):
    """True when a stored media filename contains ``entry_id``."""
    if not isinstance(entry_id, str) or not entry_id:
        return False
    return any(entry_id in stored for stored in media_names)


def is_removed(entry, version):
    """True when the latest ``removed`` value of an entry is true.

    Only version 3 entries carry the field; older catalogs never mark removals.
    """
    if version < 3:
        return False
    return digest_current(entry, "removed", version, default=False) is True


# --------------------------------------------------------------------------- #
# entry detail data
# --------------------------------------------------------------------------- #

# Static assets are served below /vault/<name>/ so viewer pages and vault files
# never share a namespace with the catalog routes.
VAULT_ROUTE = "vault"
MEDIA_ROUTE = "media"
PREVIEW_ROUTE = "preview"

# Remote path segment a source platform uses for a single entry page.
ENTRY_REMOTE = "entry"

# Tracked fields the detail page plots; both are numeric histories (``likes``
# may legitimately be null at any observation).
CHART_FIELDS = ("views", "likes")

# A chart is only drawn once a field has at least two observations to join.
CHART_MIN_POINTS = 2

EXTENSION_CONTENT_TYPES = {
    "mp4": "video/mp4", "m4v": "video/mp4", "mpeg": "video/mpeg",
    "mpg": "video/mpeg", "webm": "video/webm", "mov": "video/quicktime",
    "mkv": "video/x-matroska", "avi": "video/x-msvideo", "ts": "video/mp2t",
    "mp3": "audio/mpeg", "m4a": "audio/mp4", "aac": "audio/aac",
    "ogg": "audio/ogg", "oga": "audio/ogg", "opus": "audio/ogg",
    "wav": "audio/wav", "flac": "audio/flac", "weba": "audio/webm",
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp", "avif": "image/avif",
    "bmp": "image/bmp", "svg": "image/svg+xml", "tif": "image/tiff",
    "tiff": "image/tiff", "ico": "image/x-icon",
}

DEFAULT_MEDIA_TYPE = "application/octet-stream"
DEFAULT_IMAGE_TYPE = "image/png"


def content_type_for(filename, fallback=DEFAULT_MEDIA_TYPE):
    """Best-effort MIME type for a stored asset filename."""
    extension = filename.rpartition(".")[2].lower() if "." in filename else ""
    if extension in EXTENSION_CONTENT_TYPES:
        return EXTENSION_CONTENT_TYPES[extension]
    guessed = mimetypes.guess_type(filename)[0]
    return guessed or fallback


def image_content_type(filename):
    """MIME type for a preview asset; previews always answer as an image."""
    guessed = content_type_for(filename, DEFAULT_IMAGE_TYPE)
    return guessed if guessed.startswith("image/") else DEFAULT_IMAGE_TYPE


def vault_filenames(name, dirname):
    """Names stored in ``<vault>/<dirname>/``, sorted for a stable page."""
    try:
        return sorted(os.listdir(os.path.join(name, dirname)))
    except OSError:
        return []


def preview_filenames(name):
    """Names stored in ``<vault>/previews/``, sorted for a stable page."""
    return vault_filenames(name, PREVIEW_DIRNAME)


def matching_filename(names, entry_id):
    """First stored filename that contains ``entry_id``, or ``None``.

    Downloads are named after the entry they belong to, but the extension is
    decided by the source, so the match is by containment rather than equality.
    """
    if not isinstance(entry_id, str) or not entry_id:
        return None
    for stored in names:
        if entry_id in stored:
            return stored
    return None


def media_url(name, filename):
    """Static endpoint serving one stored media file."""
    return viewer_path(VAULT_ROUTE, name, MEDIA_ROUTE, filename)


def preview_url(name, entry_id):
    """Static endpoint serving the preview image stored for an entry."""
    return viewer_path(VAULT_ROUTE, name, PREVIEW_ROUTE, entry_id)


def find_entry(catalog, version, category, entry_id):
    """The entry of ``category`` whose id is ``entry_id``, or ``None``.

    The search never leaves the named category, so the same id appearing in a
    different category does not satisfy the lookup.  Entries marked removed are
    ordinary members of their category and stay reachable.
    """
    for entry in category_entries(catalog, version, category):
        raw = entry.get("id")
        if raw == entry_id:
            return entry
        if not isinstance(raw, str) and raw is not None and str(raw) == entry_id:
            return entry
    return None


def entry_source_link(name, catalog, version, entry_id):
    """Deterministic link to the entry on the platform the vault mirrors.

    Version 1 stores a short channel identifier that expands to a full URL;
    version 2 and 3 store the source URL itself.  Both then address a single
    entry the same way.
    """
    try:
        source = legacy_source(name, catalog, version)
    except MvaultError:
        return None
    if not source:
        return None
    return join_url(source, ENTRY_REMOTE, entry_id)


def chart_timestamp(key, version):
    """A history key rendered as an ISO 8601 chart timestamp.

    Version 1 keys are UNIX-epoch strings and convert to UTC; version 2 and 3
    keys are already ISO 8601 and pass through untouched.
    """
    if version == 1:
        try:
            return epoch_key_to_iso(key)
        except ValueError:
            return str(key)
    return key if isinstance(key, str) else str(key)


def chart_points(entry, field, version):
    """Chart points of one tracked field, oldest first.

    Values are carried through exactly as recorded - a null ``likes`` reading
    stays null rather than being dropped or replaced.
    """
    history = entry.get(field)
    if not isinstance(history, dict):
        return []
    return [{"timestamp": chart_timestamp(key, version), "value": history[key]}
            for key in digest_history_keys(history, version)]


def chart_data(entry, version):
    """``{field: [point, ...]}`` for every field the detail page plots."""
    return dict((field, chart_points(entry, field, version))
                for field in CHART_FIELDS)


# --------------------------------------------------------------------------- #
# annotations
# --------------------------------------------------------------------------- #

# Entry key holding the ordered list of user-managed annotations.  Only a
# version 3 entry carries it, so annotating a legacy vault migrates it first.
ANNOTATIONS_FIELD = "annotations"

# Query parameter the entry detail page reads to seek playback.
TIMECODE_PARAM = "timecode"

# Annotation ids are generated locally and only have to be unique inside the
# entry that stores them.
ANNOTATION_ID_PREFIX = "a"

# ``SS``, ``MM:SS`` and ``HH:MM:SS`` are the accepted timecode shapes.  Clock
# bounds are deliberately not enforced: ``90:00`` is a valid ``MM:SS`` timecode.
TIMECODE_PARTS = 3
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
TIMECODE_SHAPES = "expected SS, MM:SS or HH:MM:SS"

DIGITS = frozenset("0123456789")

# Request methods that manage annotations, mapped to the operation they run.
ANNOTATION_METHODS = {"POST": "create", "PATCH": "update", "DELETE": "delete"}

# Annotation writes are serialized: the viewer answers on many threads, but a
# catalog is read, changed and written back as a single unit.
ANNOTATION_LOCK = threading.Lock()


class ViewerError(Exception):
    """A request failure that maps onto exactly one HTTP status."""

    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status
        self.message = message


def is_digits(text):
    """True for a non-empty run of plain ASCII digits."""
    return isinstance(text, str) and bool(text) and all(c in DIGITS for c in text)


def parse_timecode(value):
    """Whole seconds for a ``SS`` / ``MM:SS`` / ``HH:MM:SS`` timecode.

    Every component is a non-negative integer and may carry leading zeros.
    Conventional clock bounds do not apply, so ``"90:00"`` reads as ninety
    minutes (5400 seconds) rather than as an error.
    """
    if is_int(value):
        if value < 0:
            raise ValueError("timecode must not be negative")
        return int(value)
    if not isinstance(value, str):
        raise ValueError("timecode must be a string")

    parts = value.strip().split(":")
    if not 1 <= len(parts) <= TIMECODE_PARTS:
        raise ValueError(TIMECODE_SHAPES)

    seconds = 0
    for part in parts:
        if not is_digits(part):
            raise ValueError(TIMECODE_SHAPES)
        seconds = seconds * SECONDS_PER_MINUTE + int(part, 10)
    return seconds


def format_timecode(seconds):
    """Render whole seconds back as ``M:SS`` (or ``H:MM:SS`` past an hour)."""
    total = max(int(seconds), 0)
    hours, rest = divmod(total, SECONDS_PER_HOUR)
    minutes, remainder = divmod(rest, SECONDS_PER_MINUTE)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, remainder)
    return "%d:%02d" % (minutes, remainder)


def seek_seconds(query):
    """The ``?timecode=`` value of a detail page request, or ``None``.

    The page only seeks to a timecode it understands; anything else is ignored
    so a hand-typed URL still renders the entry.
    """
    values = query.get(TIMECODE_PARAM) or []
    if not values:
        return None
    try:
        return parse_timecode(values[0])
    except ValueError:
        return None


def annotation_id(item):
    """Identifier of one stored annotation as page and request text."""
    raw = item.get("id")
    return raw if isinstance(raw, str) else str(raw)


def annotation_seconds(item):
    """Timecode of one stored annotation in whole seconds."""
    try:
        return parse_timecode(item.get(TIMECODE_PARAM))
    except ValueError:
        return 0


def entry_annotations(entry):
    """Stored annotations of an entry, in creation order.

    Legacy vaults and hand-edited catalogs may keep anything under the key, so
    only a list of objects counts as annotation data.
    """
    stored = entry.get(ANNOTATIONS_FIELD)
    if not isinstance(stored, list):
        return []
    return [item for item in stored if isinstance(item, dict)]


def annotation_list(entry):
    """The entry's annotation list, created in place when it is missing."""
    stored = entry.get(ANNOTATIONS_FIELD)
    if not isinstance(stored, list):
        stored = []
        entry[ANNOTATIONS_FIELD] = stored
    return stored


def find_annotation(annotations, wanted):
    for item in annotations:
        if isinstance(item, dict) and annotation_id(item) == wanted:
            return item
    return None


def next_annotation_id(annotations):
    """A short identifier no annotation of this entry uses yet."""
    used = set(annotation_id(item) for item in annotations
               if isinstance(item, dict))
    index = 1
    while "%s%d" % (ANNOTATION_ID_PREFIX, index) in used:
        index += 1
    return "%s%d" % (ANNOTATION_ID_PREFIX, index)


# ---- request decoding ----------------------------------------------------- #

def annotation_payload(body):
    """Decode an annotation request body into a JSON object."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise ViewerError(400, "annotation request body must be UTF-8 JSON")
    try:
        payload = json.loads(text)
    except ValueError:
        raise ViewerError(400, "annotation request body is not valid JSON")
    if not isinstance(payload, dict):
        raise ViewerError(400, "annotation request body must be a JSON object")
    return payload


def missing_field(field):
    # Quotes would only reach the page as entities, so the field is named bare.
    return ViewerError(400, "annotation request is missing required field: %s"
                            % field)


def required_text(payload, field):
    """Read a mandatory text field out of an annotation request."""
    if field not in payload or payload[field] is None:
        raise missing_field(field)
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        raise ViewerError(400, "annotation field %s must be a non-empty string"
                               % field)
    return value


def required_id(payload):
    """Read the annotation identifier an update or delete request names."""
    if "id" not in payload or payload["id"] is None:
        raise missing_field("id")
    if is_int(payload["id"]):
        # A numeric id is a spelling of the same identifier, not a new type.
        return str(payload["id"])
    return required_text(payload, "id")


def optional_body(payload):
    """Read the optional ``body`` field; absent and null both mean ``null``."""
    value = payload.get("body")
    if value is not None and not isinstance(value, str):
        raise ViewerError(400, "annotation field body must be a string or null")
    return value


def plan_create(payload):
    """Validate a create request and return the operation that applies it."""
    title = required_text(payload, "title")
    if TIMECODE_PARAM not in payload or payload[TIMECODE_PARAM] is None:
        raise missing_field(TIMECODE_PARAM)
    try:
        seconds = parse_timecode(payload[TIMECODE_PARAM])
    except ValueError as exc:
        raise ViewerError(400, "invalid timecode format: %s (%s)"
                               % (payload[TIMECODE_PARAM], exc))
    note = optional_body(payload)

    def apply(annotations):
        # Creation order is list order, so a new annotation always appends.
        annotations.append({"id": next_annotation_id(annotations),
                            TIMECODE_PARAM: seconds,
                            "title": title,
                            "body": note})
        return "%s=%d" % (TIMECODE_PARAM, seconds)
    return apply


def plan_update(payload):
    """Validate an update request and return the operation that applies it."""
    wanted = required_id(payload)
    fields = {}
    if "title" in payload:
        fields["title"] = required_text(payload, "title")
    if "body" in payload:
        fields["body"] = optional_body(payload)
    if not fields:
        raise ViewerError(400, "annotation update requires a new title or "
                               "body field")

    def apply(annotations):
        item = find_annotation(annotations, wanted)
        if item is None:
            raise ViewerError(404, "no annotation %s in this entry" % wanted)
        # Fields the request left out keep the value they already had.
        item.update(fields)
        return None
    return apply


def plan_delete(payload):
    """Validate a delete request and return the operation that applies it."""
    wanted = required_id(payload)

    def apply(annotations):
        item = find_annotation(annotations, wanted)
        if item is None:
            raise ViewerError(404, "no annotation %s in this entry" % wanted)
        # Removed by identity, so an annotation that merely looks the same
        # as another one stays where it is.
        annotations[:] = [other for other in annotations if other is not item]
        return None
    return apply


ANNOTATION_PLANS = {"create": plan_create, "update": plan_update,
                    "delete": plan_delete}


def annotation_plan(method, payload):
    """The validated operation one annotation request asks for."""
    return ANNOTATION_PLANS[ANNOTATION_METHODS[method]](payload)


# ---- catalog side --------------------------------------------------------- #

def annotation_category(version, category):
    """Category the annotated entry ends up in, or ``None`` when unroutable.

    A version 1 vault is addressed through its own flat ``entries`` category,
    but the entry lives in ``episodes`` once the annotation migrates the vault.
    """
    if version == 1:
        return CATEGORIES[0] if category in (V1_CATEGORY, CATEGORIES[0]) else None
    return category if category in CATEGORIES else None


def annotate_entry(name, category, entry_id, apply):
    """Run one annotation operation against a vault and persist the result.

    Annotations only exist in version 3, so a legacy vault is migrated first -
    by the same rules as the ``migrate`` command - and the migration is written
    together with the annotation.  The ``catalog.bak`` left behind therefore
    holds the catalog as it was before both changes, and a failing operation
    (or a failing migration) writes nothing at all.

    Returns ``(category, query)``: the category holding the entry after any
    migration, and the query string of the redirect that follows.
    """
    with ANNOTATION_LOCK:
        catalog, version = load_raw_catalog(name)

        target = annotation_category(version, category)
        if target is None:
            raise ViewerError(404, "no category %s in vault %s" % (category, name))

        # The entry is addressed by its pre-migration category, so it is looked
        # up in the catalog exactly as it is stored today.
        entry = find_entry(catalog, version, category, entry_id)
        if entry is None:
            raise ViewerError(404, "no entry %s in category %s of vault %s"
                                   % (entry_id, category, name))

        if version != VERSION:
            catalog = migrate_catalog(name, catalog, version)
            entry = find_entry(catalog, VERSION, target, entry_id)
            if entry is None:
                raise ViewerError(404, "no entry %s in category %s of vault %s"
                                       % (entry_id, target, name))

        query = apply(annotation_list(entry))
        write_catalog(name, catalog)
        return target, query


# --------------------------------------------------------------------------- #
# viewer pages
# --------------------------------------------------------------------------- #

RECENT_STORE = ".mvault-viewer.json"
RECENT_COOKIE = "mvault_recent"
RECENT_LIMIT = 20
RECENT_MAX_AGE = 60 * 60 * 24 * 365

STYLE_PATH = "/viewer.css"
STYLE = """
:root { color-scheme: light dark; }
body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 52rem;
       padding: 0 1rem; line-height: 1.5; }
h1 { margin-bottom: 0.25rem; }
a { color: #1a5fb4; }
.crumbs { color: #666; margin-top: 0; }
form.open { display: flex; gap: 0.5rem; align-items: center; margin: 1rem 0; }
input[type=text] { padding: 0.4rem 0.5rem; font-size: 1rem; flex: 1; }
button { padding: 0.4rem 0.9rem; font-size: 1rem; }
p.error { background: #ffd6d6; border-left: 4px solid #c01c28; color: #5e1414;
          padding: 0.6rem 0.8rem; }
ul.entries, ul.recent { list-style: none; padding: 0; }
ul.entries li { border: 1px solid #ccc; border-left-width: 6px;
                border-radius: 4px; margin: 0.4rem 0; padding: 0.5rem 0.75rem; }
ul.entries li.downloaded { border-left-color: #2ec27e; }
ul.entries li.missing { border-left-color: #c0bfbc; opacity: 0.75; }
ul.entries li.removed { border-left-color: #c01c28; text-decoration: line-through; }
.badge { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em;
         border-radius: 999px; padding: 0.1rem 0.5rem; margin-left: 0.4rem; }
.state-downloaded { background: #2ec27e; color: #06281a; }
.state-missing { background: #deddda; color: #3d3846; }
.state-removed { background: #c01c28; color: #fff; }
nav.categories a { margin-right: 0.75rem; }
dl.meta { display: grid; grid-template-columns: max-content 1fr; gap: 0.3rem 1rem; }
dl.meta dt { font-weight: 600; color: #666; }
dl.meta dd { margin: 0; }
figure.media, figure.chart, figure.preview { margin: 1rem 0; }
video.player, img.preview { max-width: 100%; border-radius: 4px; }
p.media.missing { color: #666; font-style: italic; }
figure.chart figcaption { font-weight: 600; text-transform: capitalize; }
svg.spark { width: 100%; height: auto; border: 1px solid #ccc; border-radius: 4px; }
svg.spark polyline { fill: none; stroke: #1a5fb4; stroke-width: 2;
                     stroke-linejoin: round; stroke-linecap: round; }
svg.spark circle { fill: #1a5fb4; }
p.description { white-space: pre-wrap; }
p.seek { color: #666; font-style: italic; }
ol.annotations { list-style: none; padding: 0; }
ol.annotations li { border: 1px solid #ccc; border-left: 6px solid #1a5fb4;
                    border-radius: 4px; margin: 0.4rem 0; padding: 0.5rem 0.75rem; }
ol.annotations .timecode { font-variant-numeric: tabular-nums; font-weight: 600; }
ol.annotations .seconds { color: #666; font-size: 0.85rem; }
ol.annotations .title { margin-left: 0.5rem; }
ol.annotations p.body { margin: 0.35rem 0 0; white-space: pre-wrap; }
ol.annotations .controls { margin-top: 0.35rem; }
ol.annotations button { font-size: 0.8rem; padding: 0.15rem 0.5rem;
                        margin-right: 0.3rem; }
form.annotate { display: grid; gap: 0.4rem; margin: 1rem 0; max-width: 32rem; }
form.annotate textarea, form.annotation-edit textarea { font: inherit;
                        padding: 0.4rem 0.5rem; min-height: 3rem; }
form.annotate input[type=text], form.annotation-edit input[type=text] {
                        flex: none; }
form.annotation-edit { display: grid; gap: 0.3rem; margin-top: 0.4rem; }
"""


def render_page(title, body):
    """Wrap page ``body`` in the shared HTML document skeleton."""
    return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>%s</title>\n<link rel=\"stylesheet\" href=\"%s\">\n</head>\n"
            "<body>\n%s\n</body>\n</html>\n" % (escape(title), STYLE_PATH, body))


def render_landing(recent, missing=None):
    """Landing page: the vault form, any error notice and recent vaults."""
    parts = ["<h1>mvault viewer</h1>"]
    if missing:
        parts.append("<p class=\"error\" id=\"error\">Vault not found: "
                     "<code>%s</code></p>" % escape(str(missing)))
    parts.append(
        "<form class=\"open\" method=\"post\" action=\"/\">\n"
        "<label for=\"catalog\">Vault name</label>\n"
        "<input type=\"text\" id=\"catalog\" name=\"catalog\" placeholder=\"vault\""
        " autofocus>\n<button type=\"submit\">Open</button>\n</form>")

    if recent:
        items = "\n".join(
            "<li><a href=\"%s\">%s</a></li>" % (escape(target), escape(label))
            for label, target in recent)
        parts.append("<section id=\"recent\">\n<h2>Recent vaults</h2>\n"
                     "<ul class=\"recent\">\n%s\n</ul>\n</section>" % items)
    return render_page("mvault viewer", "\n".join(parts))


def render_entry_item(name, version, category, entry, media_names):
    """One ``<li>`` of a category listing."""
    entry_id = entry.get("id")
    entry_id = entry_id if isinstance(entry_id, str) else str(entry_id)
    classes = ["entry"]
    badges = []

    if is_downloaded(media_names, entry_id):
        classes.append("downloaded")
        badges.append("<span class=\"badge state-downloaded\">downloaded</span>")
    else:
        classes.append("missing")
        badges.append("<span class=\"badge state-missing\">missing</span>")

    if is_removed(entry, version):
        classes.append("removed")
        badges.append("<span class=\"badge state-removed\">removed</span>")

    return ("<li class=\"%s\" id=\"entry-%s\"><a class=\"title\" href=\"%s\">%s</a>"
            " <span class=\"eid\">%s</span>%s</li>"
            % (" ".join(classes), escape(entry_id),
               escape(viewer_path("catalog", name, category, entry_id)),
               escape(entry_title(entry, version)), escape(entry_id),
               "".join(badges)))


def render_listing(name, version, category, entries, media_names):
    """Category listing page linking every entry to its detail page."""
    nav = " ".join(
        "<a href=\"%s\">%s</a>" % (escape(viewer_path("catalog", name, known)),
                                   escape(known))
        for known in valid_categories(version))

    parts = ["<h1>%s</h1>" % escape(name),
             "<p class=\"crumbs\"><a href=\"/\">all vaults</a> &middot; "
             "category <strong>%s</strong> &middot; catalog version %d</p>"
             % (escape(category), version),
             "<nav class=\"categories\">%s</nav>" % nav]

    if entries:
        items = "\n".join(
            render_entry_item(name, version, category, entry, media_names)
            for entry in entries)
        parts.append("<ul class=\"entries\">\n%s\n</ul>" % items)
    else:
        parts.append("<p class=\"empty\">No entries in this category.</p>")

    return render_page("%s / %s" % (name, category), "\n".join(parts))


def chart_svg(field, points):
    """Inline sparkline for one tracked field, or ``""`` when not worth drawing.

    Only numeric readings can be plotted, so null ``likes`` observations leave a
    gap in the line while remaining present in the embedded chart data.
    """
    plotted = [(index, float(point["value"]))
               for index, point in enumerate(points)
               if isinstance(point["value"], (int, float))
               and not isinstance(point["value"], bool)]
    if len(plotted) < CHART_MIN_POINTS:
        return ""

    width, height, pad = 640.0, 160.0, 14.0
    lowest = min(value for _index, value in plotted)
    highest = max(value for _index, value in plotted)
    span = (highest - lowest) or 1.0
    steps = (len(points) - 1) or 1

    coords = []
    for index, value in plotted:
        x = pad + (width - 2 * pad) * (float(index) / steps)
        y = height - pad - (height - 2 * pad) * ((value - lowest) / span)
        coords.append((x, y))

    line = " ".join("%.2f,%.2f" % point for point in coords)
    dots = "".join("<circle cx=\"%.2f\" cy=\"%.2f\" r=\"3\"></circle>" % point
                   for point in coords)
    return ("<svg class=\"spark\" viewBox=\"0 0 %d %d\" role=\"img\" "
            "preserveAspectRatio=\"none\" aria-label=\"%s over time\">"
            "<polyline points=\"%s\"></polyline>%s</svg>"
            % (int(width), int(height), escape(field), line, dots))


def render_charts(entry, version):
    """History section: machine-readable chart data plus drawn sparklines."""
    data = chart_data(entry, version)
    # The payload travels as JSON inside the page so a reader does not have to
    # scrape rendered markup; "</" is escaped so it cannot end the script tag.
    blob = json.dumps(data, sort_keys=False).replace("</", "<\\/")

    parts = ["<section class=\"charts\" id=\"charts\">",
             "<h2>History</h2>",
             "<script id=\"chart-data\" type=\"application/json\">%s</script>" % blob]

    for field in CHART_FIELDS:
        svg = chart_svg(field, data[field])
        if not svg:
            # A field observed once has no trend to draw; its data stays above.
            continue
        parts.append("<figure class=\"chart\" id=\"chart-%s\">\n"
                     "<figcaption>%s</figcaption>\n%s\n</figure>"
                     % (escape(field), escape(field), svg))
    parts.append("</section>")
    return "\n".join(parts)


def detail_text(value, fallback=""):
    """Render a tracked value as page text without losing non-string data."""
    if isinstance(value, str):
        return value
    if value is None:
        return fallback
    return str(value)


SEEK_SCRIPT = """
(function () {
  var at = %d;
  var player = document.querySelector("video.player");
  if (!player) { return; }
  var seek = function () { try { player.currentTime = at; } catch (err) {} };
  player.addEventListener("loadedmetadata", seek);
  if (player.readyState > 0) { seek(); }
})();
"""

ANNOTATION_SCRIPT = """
(function () {
  var section = document.getElementById("annotations");
  if (!section) { return; }
  var target = section.getAttribute("data-action");

  var send = function (method, payload) {
    fetch(target, {
      method: method,
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)
    }).then(function (response) {
      if (response.redirected) { window.location.href = response.url; }
      else { window.location.reload(); }
    });
  };

  var create = document.getElementById("annotate");
  if (create) {
    create.addEventListener("submit", function (event) {
      event.preventDefault();
      var fields = new FormData(create);
      send("POST", {title: fields.get("title"),
                    timecode: fields.get("timecode"),
                    body: fields.get("body") || null});
    });
  }

  section.addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest("button[data-id]")
                                      : null;
    if (!button) { return; }
    var id = button.getAttribute("data-id");
    if (button.classList.contains("delete")) {
      send("DELETE", {id: id});
      return;
    }
    var form = section.querySelector("form.annotation-edit[data-id=" +
                                     JSON.stringify(id) + "]");
    if (form) { form.hidden = !form.hidden; }
  });

  section.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.classList || !form.classList.contains("annotation-edit")) { return; }
    event.preventDefault();
    var fields = new FormData(form);
    send("PATCH", {id: form.getAttribute("data-id"),
                   title: fields.get("title"),
                   body: fields.get("body") || null});
  });
})();
"""


def inline_script(ident, source):
    """Embed page script so its text can never close the script element."""
    return "<script id=\"%s\">%s</script>" % (ident, source.replace("</", "<\\/"))


def render_seek(seek):
    """Notice and player hook that start playback at the requested timecode."""
    if seek is None:
        return ""
    return ("<p class=\"seek\" id=\"seek\" data-timecode=\"%d\">Playing from "
            "<span class=\"timecode\">%s</span> "
            "(<span class=\"seconds\">%d</span>s).</p>\n%s"
            % (seek, escape(format_timecode(seek)), seek,
               inline_script("seek-script", SEEK_SCRIPT % seek)))


def render_annotation(target, item):
    """One stored annotation as a list item of the detail page."""
    ident = annotation_id(item)
    seconds = annotation_seconds(item)
    title = detail_text(item.get("title"))
    body = item.get("body")
    link = "%s?%s=%d" % (target, TIMECODE_PARAM, seconds)

    parts = ["<li class=\"annotation\" id=\"annotation-%s\" data-id=\"%s\" "
             "data-timecode=\"%d\">" % (escape(ident), escape(ident), seconds),
             "<a class=\"timecode\" href=\"%s\">%s</a> "
             "(<span class=\"seconds\">%d</span>s)"
             % (escape(link), escape(format_timecode(seconds)), seconds),
             "<span class=\"title\">%s</span>" % escape(title)]
    if isinstance(body, str) and body:
        parts.append("<p class=\"body\">%s</p>" % escape(body))
    parts.append("<p class=\"controls\">"
                 "<button type=\"button\" class=\"edit\" data-id=\"%s\">edit"
                 "</button>"
                 "<button type=\"button\" class=\"delete\" data-id=\"%s\">delete"
                 "</button></p>" % (escape(ident), escape(ident)))
    parts.append("<form class=\"annotation-edit\" data-id=\"%s\" hidden>\n"
                 "<input type=\"text\" name=\"title\" value=\"%s\" "
                 "aria-label=\"annotation title\">\n"
                 "<textarea name=\"body\" aria-label=\"annotation note\">%s"
                 "</textarea>\n<button type=\"submit\">save</button>\n</form>"
                 % (escape(ident), escape(title),
                    escape(body if isinstance(body, str) else "")))
    parts.append("</li>")
    return "\n".join(parts)


def render_annotations(name, category, entry_id, entry):
    """Annotation section: every stored note plus the forms that manage them."""
    target = viewer_path("catalog", name, category, entry_id)
    items = entry_annotations(entry)

    parts = ["<section class=\"annotations\" id=\"annotations\" "
             "data-action=\"%s\">" % escape(target),
             "<h2>Annotations</h2>"]
    if items:
        parts.append("<ol class=\"annotations\">\n%s\n</ol>"
                     % "\n".join(render_annotation(target, item)
                                 for item in items))
    else:
        parts.append("<p class=\"empty\" id=\"no-annotations\">"
                     "No annotations for this entry.</p>")

    parts.append("<form class=\"annotate\" id=\"annotate\" method=\"post\" "
                 "action=\"%s\">\n"
                 "<label for=\"annotation-title\">Title</label>\n"
                 "<input type=\"text\" id=\"annotation-title\" name=\"title\" "
                 "required>\n"
                 "<label for=\"annotation-timecode\">Timecode</label>\n"
                 "<input type=\"text\" id=\"annotation-timecode\" "
                 "name=\"timecode\" placeholder=\"1:30\" required>\n"
                 "<label for=\"annotation-body\">Note</label>\n"
                 "<textarea id=\"annotation-body\" name=\"body\"></textarea>\n"
                 "<button type=\"submit\">Add annotation</button>\n</form>"
                 % escape(target))
    parts.append(inline_script("annotation-script", ANNOTATION_SCRIPT))
    parts.append("</section>")
    return "\n".join(parts)


def render_detail(name, version, category, entry, source_link,
                  media_name, preview_name, seek=None):
    """Entry detail page: metadata, source link, media, charts and notes.

    ``seek`` is the ``?timecode=`` value of the request in whole seconds; the
    player starts there instead of at the beginning.
    """
    entry_id = detail_text(entry.get("id"))
    listing = viewer_path("catalog", name, category)
    title = entry_title(entry, version)

    parts = ["<h1 class=\"title\">%s</h1>" % escape(title),
             "<p class=\"crumbs\"><a href=\"/\">all vaults</a> &middot; "
             "<a href=\"%s\">%s</a> &middot; category <strong>%s</strong>"
             " &middot; catalog version %d</p>"
             % (escape(listing), escape(name), escape(category), version),
             "<p class=\"back\"><a class=\"back\" href=\"%s\">"
             "&larr; back to %s / %s</a></p>"
             % (escape(listing), escape(name), escape(category))]

    if is_removed(entry, version):
        parts.append("<p class=\"badge state-removed\" id=\"removed\">"
                     "removed</p>")

    if media_name:
        target = media_url(name, media_name)
        # A media fragment makes the requested timecode survive a plain reload,
        # even before the page script gets to touch the player.
        playing = target + ("#t=%d" % seek if seek is not None else "")
        parts.append("<figure class=\"media\" id=\"media\">\n"
                     "<video class=\"player\" controls preload=\"none\" "
                     "src=\"%s\"%s>\n"
                     "<a href=\"%s\">%s</a>\n</video>\n"
                     "<figcaption><a class=\"media-file\" href=\"%s\">%s</a>"
                     "</figcaption>\n</figure>"
                     % (escape(playing),
                        " data-timecode=\"%d\"" % seek if seek is not None else "",
                        escape(target), escape(media_name),
                        escape(target), escape(media_name)))
    else:
        parts.append("<p class=\"media missing\" id=\"media\">"
                     "No downloaded media file for this entry.</p>")

    seeking = render_seek(seek)
    if seeking:
        parts.append(seeking)

    if preview_name:
        parts.append("<figure class=\"preview\">\n<img class=\"preview\" "
                     "src=\"%s\" alt=\"preview image for %s\">\n</figure>"
                     % (escape(preview_url(name, entry_id)), escape(entry_id)))

    published = detail_text(entry.get("published"), "unknown")
    width, height = entry.get("width"), entry.get("height")
    if is_int(width) and is_int(height):
        dimensions = ("<span class=\"width\">%d</span> &times; "
                      "<span class=\"height\">%d</span>" % (width, height))
    else:
        dimensions = "unknown"

    rows = [("Identifier", "<code class=\"eid\">%s</code>" % escape(entry_id)),
            ("Published", "<span class=\"published\">%s</span>"
                          % escape(published)),
            ("Dimensions", "<span class=\"dimensions\">%s</span>" % dimensions)]
    if source_link:
        rows.append(("Source", "<a class=\"source\" href=\"%s\">%s</a>"
                               % (escape(source_link), escape(source_link))))

    parts.append("<dl class=\"meta\">\n%s\n</dl>"
                 % "\n".join("<dt>%s</dt><dd>%s</dd>" % (label, value)
                              for label, value in rows))

    description = detail_text(digest_current(entry, "description", version))
    parts.append("<h2>Description</h2>\n<p class=\"description\">%s</p>"
                 % escape(description))

    parts.append(render_charts(entry, version))
    parts.append(render_annotations(name, category, entry_id, entry))
    return render_page("%s / %s / %s" % (name, category, entry_id),
                       "\n".join(parts))


def render_error(status, message):
    """Minimal, well-formed page for an HTTP error response."""
    return render_page("mvault viewer - %d" % status,
                       "<h1>%d</h1>\n<p class=\"error\">%s</p>\n"
                       "<p><a href=\"/\">back to all vaults</a></p>"
                       % (status, escape(message)))


# --------------------------------------------------------------------------- #
# recent vaults
# --------------------------------------------------------------------------- #

MISSING_COOKIE = "mvault_missing"
MISSING_TTL = 30
LAST_MISSING = {"name": None, "at": 0.0}


def note_missing_vault(name):
    """Remember an unopenable vault and return the cookie announcing it.

    The landing page is reached by a plain redirect to ``/``, so the name of
    the vault travels in a short-lived cookie instead of the URL.  It is also
    kept in memory for the same few seconds, which is what a client that does
    not keep cookies ends up reading.
    """
    LAST_MISSING["name"] = name
    LAST_MISSING["at"] = time.monotonic()
    return "%s=%s; Max-Age=%d; Path=/; SameSite=Lax" % (
        MISSING_COOKIE, quote(name, safe=""), MISSING_TTL)


def take_missing_vault(header):
    """Return ``(vault name or None, cookie clearing the notice or None)``."""
    name = None
    clear = None

    try:
        jar = SimpleCookie()
        jar.load(header or "")
        morsel = jar.get(MISSING_COOKIE)
    except Exception:
        morsel = None
    if morsel is not None and morsel.value:
        name = unquote(morsel.value)
        clear = "%s=; Max-Age=0; Path=/" % MISSING_COOKIE

    if name is None and LAST_MISSING["name"] is not None:
        if time.monotonic() - LAST_MISSING["at"] <= MISSING_TTL:
            name = LAST_MISSING["name"]

    # A notice is shown once; a later visit to the landing page is clean.
    LAST_MISSING["name"] = None
    return name, clear


def recent_store_path():
    return os.path.join(os.getcwd(), RECENT_STORE)


def clean_recent(names):
    """De-duplicate a recent list, keeping the most recent position of each."""
    ordered = []
    for name in names:
        if isinstance(name, str) and name and name not in ordered:
            ordered.append(name)
    return ordered[:RECENT_LIMIT]


def load_recent_store():
    """Recently visited vaults recorded on this machine, newest first."""
    try:
        with open(recent_store_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []

    names = data.get("recent") if isinstance(data, dict) else data
    return clean_recent(names) if isinstance(names, list) else []


def save_recent_store(names):
    """Persist the recent list; a read-only directory is not an error."""
    try:
        with open(recent_store_path(), "w", encoding="utf-8") as handle:
            json.dump({"recent": clean_recent(names)}, handle)
    except OSError:
        pass


def decode_recent_cookie(header):
    """Recent vaults carried by the browser, newest first."""
    if not header:
        return []
    try:
        jar = SimpleCookie()
        jar.load(header)
    except Exception:
        return []

    morsel = jar.get(RECENT_COOKIE)
    if morsel is None:
        return []
    try:
        names = json.loads(unquote(morsel.value))
    except (ValueError, TypeError):
        return []
    return clean_recent(names) if isinstance(names, list) else []


def encode_recent_cookie(names):
    """``Set-Cookie`` value keeping the recent list across browser sessions."""
    payload = quote(json.dumps(clean_recent(names)), safe="")
    return "%s=%s; Max-Age=%d; Path=/; SameSite=Lax" % (RECENT_COOKIE, payload,
                                                        RECENT_MAX_AGE)


def touch_recent(name, cookie_names):
    """Record a visit to ``name`` both on disk and for the visiting browser."""
    stored = clean_recent([name] + load_recent_store())
    save_recent_store(stored)
    return clean_recent([name] + list(cookie_names))


def recent_links(cookie_names):
    """``[(name, default category path), ...]`` for vaults that still exist."""
    links = []
    for name in clean_recent(list(cookie_names) + load_recent_store()):
        try:
            _catalog, version = load_raw_catalog(name)
        except MvaultError:
            continue
        links.append((name, viewer_path("catalog", name, default_category(version))))
    return links


# --------------------------------------------------------------------------- #
# viewer server
# --------------------------------------------------------------------------- #

def safe_vault_name(name):
    """True when ``name`` is a plain vault name below the served directory."""
    if not name or name in (".", ".."):
        return False
    if name.startswith("/") or name.startswith("~") or "\\" in name:
        return False
    if os.path.isabs(name):
        return False
    return all(part not in ("", ".", "..") for part in name.split("/"))


def safe_relative_path(parts):
    """Join decoded URL segments into a relative path, or ``None`` if unsafe.

    Any ``..`` component - however it was spelled in the request - is rejected
    outright so a static request can never address a file outside its folder.
    """
    pieces = []
    for part in parts:
        if os.path.isabs(str(part)):
            return None
        for piece in str(part).replace("\\", "/").split("/"):
            if piece in ("", "."):
                continue
            if piece == "..":
                return None
            pieces.append(piece)
    if not pieces:
        return None
    return os.path.join(*pieces)


def contained_path(directory, relative):
    """Resolve ``relative`` inside ``directory``, or ``None`` when it escapes.

    Re-checked after resolution so a symlink pointing out of the folder is
    refused just like a literal traversal sequence.
    """
    base = os.path.realpath(directory)
    target = os.path.realpath(os.path.join(base, relative))
    if target != base and not target.startswith(base + os.sep):
        return None
    return target


# Longest chunk-size (or trailer) line the viewer reads from a chunked body.
MAX_CHUNK_LINE = 65536


class ViewerHandler(BaseHTTPRequestHandler):
    """Serves the vault viewer; every route answers with a complete response."""

    server_version = "mvault-viewer/1.0"
    protocol_version = "HTTP/1.1"

    # ---- plumbing ------------------------------------------------------- #

    def log_message(self, *args):
        pass  # the viewer is interactive; request logs would only be noise

    def respond(self, status, body="", content_type="text/html; charset=utf-8",
                headers=()):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            # Vaults change under the viewer; never answer from a cache.
            self.send_header("Cache-Control", "no-store")
            for key, value in headers:
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD" and payload:
                self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the browser went away mid-response; nothing to recover

    def redirect(self, location, status=302, headers=()):
        body = render_page("redirecting",
                           "<p>Continue to <a href=\"%s\">%s</a>.</p>"
                           % (escape(location), escape(location)))
        self.respond(status, body, headers=tuple(headers) + (("Location", location),))

    def fail(self, status, message):
        self.respond(status, render_error(status, message))

    # ---- routes --------------------------------------------------------- #

    def do_GET(self):
        self.dispatch()

    def do_HEAD(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def do_PATCH(self):
        self.dispatch()

    def do_DELETE(self):
        self.dispatch()

    def dispatch(self):
        """Route one request, turning any failure into a proper HTTP response."""
        try:
            parsed = urlsplit(self.path)
            segments = [unquote(part) for part in parsed.path.split("/") if part]
            query = parse_qs(parsed.query)

            if self.command in ANNOTATION_METHODS:
                # The body is always consumed, whatever the route decides, so a
                # kept alive connection stays in sync for the next request.
                body = self.read_body()
                if self.command == "POST" and not segments:
                    return self.handle_open(parse_qs(body.decode("utf-8",
                                                                "replace")))
                if segments[:1] == ["catalog"] and len(segments) == 4:
                    return self.handle_annotation(segments[1:], body)
                return self.fail(404, "unknown path")

            if not segments:
                return self.handle_landing(query)
            if segments == [STYLE_PATH.lstrip("/")]:
                return self.respond(200, STYLE, "text/css; charset=utf-8")
            if segments[0] == "catalog" and len(segments) >= 2:
                return self.handle_catalog(segments[1:], query)
            if segments[0] == VAULT_ROUTE:
                return self.handle_vault(segments[1:])
            return self.fail(404, "unknown path")
        except Exception:
            # Never leak a traceback to the browser.
            self.fail(500, "the viewer could not handle this request")

    def handle_landing(self, query):
        cookie = self.headers.get("Cookie")
        missing, clear = take_missing_vault(cookie)
        missing = missing or (query.get("missing") or [None])[0]
        headers = (("Set-Cookie", clear),) if clear else ()
        self.respond(200,
                     render_landing(recent_links(decode_recent_cookie(cookie)),
                                    missing),
                     headers=headers)

    def read_body(self):
        """Consume and return the raw bytes of a request body."""
        encoding = (self.headers.get("Transfer-Encoding") or "").strip().lower()
        if encoding:
            if encoding != "chunked":
                # An encoding the viewer cannot undo would leave unread bytes
                # behind, so the connection ends with this reply.
                self.close_connection = True
                return b""
            return self.read_chunked_body()

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        return self.rfile.read(length) if length > 0 else b""

    def read_chunked_body(self):
        """Reassemble a ``Transfer-Encoding: chunked`` request body."""
        chunks = []
        while True:
            line = self.rfile.readline(MAX_CHUNK_LINE)
            if not line:
                break
            try:
                size = int(line.split(b";")[0].strip() or b"0", 16)
            except ValueError:
                self.close_connection = True
                break
            if size <= 0:
                break
            chunks.append(self.rfile.read(size))
            self.rfile.read(2)  # the CRLF closing this chunk

        # Trailers, when present, end at the blank line after the last chunk.
        while True:
            line = self.rfile.readline(MAX_CHUNK_LINE)
            if not line or line in (b"\r\n", b"\n"):
                break
        return b"".join(chunks)

    def handle_open(self, fields):
        """``POST /``: send the submitted vault name to its catalog page."""
        values = fields.get("catalog") or []
        name = values[0].strip() if values else ""
        if not name:
            return self.redirect("/", status=303)
        return self.redirect(viewer_path("catalog", name), status=303)

    def handle_catalog(self, segments, query=None):
        name = segments[0]
        query = query or {}
        try:
            if not safe_vault_name(name):
                raise MvaultError("vault %r does not exist" % name)
            catalog, version = load_raw_catalog(name)
        except MvaultError:
            return self.redirect("/", headers=(("Set-Cookie",
                                                note_missing_vault(name)),))

        # Reaching a real vault through the viewer makes it a recent vault.
        recent = touch_recent(name, decode_recent_cookie(self.headers.get("Cookie")))
        headers = (("Set-Cookie", encode_recent_cookie(recent)),)

        fallback = viewer_path("catalog", name, default_category(version))
        if len(segments) == 1:
            return self.redirect(fallback, headers=headers)

        category = segments[1]
        if category not in valid_categories(version):
            if len(segments) == 3:
                # A retired category - a version 1 route surviving an
                # auto-migration - still leads to the entry it named.
                moved = self.moved_entry(name, catalog, version, segments[2],
                                         query)
                if moved:
                    return self.redirect(moved, headers=headers)
            return self.redirect(fallback, headers=headers)
        if len(segments) > 3:
            return self.fail(404, "unknown path")

        if len(segments) == 3:
            return self.handle_entry(name, catalog, version, category,
                                     segments[2], headers, seek_seconds(query))

        body = render_listing(name, version, category,
                              category_entries(catalog, version, category),
                              media_filenames(name))
        self.respond(200, body, headers=headers)

    def handle_entry(self, name, catalog, version, category, entry_id, headers,
                     seek=None):
        """``GET /catalog/<name>/<category>/<id>``: one entry in full."""
        entry = find_entry(catalog, version, category, entry_id)
        if entry is None:
            return self.fail(404, "no entry %s in category %s of vault %s"
                                  % (entry_id, category, name))

        body = render_detail(
            name, version, category, entry,
            entry_source_link(name, catalog, version, entry_id),
            matching_filename(media_filenames(name), entry_id),
            matching_filename(preview_filenames(name), entry_id),
            seek)
        self.respond(200, body, headers=headers)

    def moved_entry(self, name, catalog, version, entry_id, query):
        """Canonical viewer path of an entry addressed by a retired category."""
        for category in valid_categories(version):
            if find_entry(catalog, version, category, entry_id) is None:
                continue
            target = viewer_path("catalog", name, category, entry_id)
            seek = seek_seconds(query)
            if seek is not None:
                target += "?%s=%d" % (TIMECODE_PARAM, seek)
            return target
        return None

    def handle_annotation(self, segments, body):
        """``POST``/``PATCH``/``DELETE`` on an entry: manage its annotations.

        A successful mutation answers with a redirect to the entry detail page
        of the category the entry lives in once the request has been applied,
        which is not the category the request named when the vault migrated.
        """
        name, category, entry_id = segments[0], segments[1], segments[2]
        try:
            if not safe_vault_name(name) or not os.path.isdir(name):
                raise ViewerError(404, "vault %s does not exist" % name)
            plan = annotation_plan(self.command, annotation_payload(body))
            target, query = annotate_entry(name, category, entry_id, plan)
        except ViewerError as exc:
            return self.fail(exc.status, exc.message)
        except MvaultError as exc:
            # A catalog that cannot be read or migrated is left exactly as is.
            return self.fail(500, str(exc))

        location = viewer_path("catalog", name, target, entry_id)
        if query:
            location += "?" + query
        return self.redirect(location, status=303)

    # ---- static vault files --------------------------------------------- #

    def handle_vault(self, segments):
        """``GET /vault/<name>/media|preview/...``: serve a stored asset."""
        if len(segments) < 3:
            return self.fail(404, "unknown path")

        name, kind, rest = segments[0], segments[1], segments[2:]
        if ".." in name or os.path.isabs(name) or name.startswith("~"):
            # A traversal attempt never reaches the filesystem.
            return self.fail(403, "forbidden path")
        if not safe_vault_name(name) or not os.path.isdir(name):
            return self.redirect("/", headers=(("Set-Cookie",
                                                note_missing_vault(name)),))

        if kind == MEDIA_ROUTE:
            return self.serve_media(name, rest)
        if kind == PREVIEW_ROUTE:
            return self.serve_preview(name, rest)
        return self.fail(404, "unknown path")

    def serve_media(self, name, rest):
        """Serve ``<vault>/media/<file>`` exactly as it was saved."""
        relative = safe_relative_path(rest)
        if relative is None:
            return self.fail(403, "forbidden path")
        directory = os.path.join(name, MEDIA_DIRNAME)
        target = contained_path(directory, relative)
        if target is None:
            return self.fail(403, "forbidden path")
        return self.serve_file(target, content_type_for(os.path.basename(target)))

    def serve_preview(self, name, rest):
        """Serve the preview image saved for an entry id."""
        relative = safe_relative_path(rest)
        if relative is None:
            return self.fail(403, "forbidden path")
        if os.sep in relative or "/" in relative:
            return self.fail(404, "no preview for this entry")

        stored = matching_filename(preview_filenames(name), relative)
        if stored is None:
            return self.fail(404, "no preview for this entry")

        directory = os.path.join(name, PREVIEW_DIRNAME)
        target = contained_path(directory, stored)
        if target is None:
            return self.fail(403, "forbidden path")
        return self.serve_file(target, image_content_type(stored))

    def serve_file(self, target, content_type):
        """Send one file from disk, or a 404 when it is not readable."""
        if not os.path.isfile(target):
            return self.fail(404, "file not found")
        try:
            with open(target, "rb") as handle:
                payload = handle.read()
        except OSError:
            return self.fail(404, "file not found")
        self.respond(200, payload, content_type)


def browser_host(host):
    """Host a browser on this machine should use to reach ``host``."""
    if not host or host in ("0.0.0.0", "::", "*"):
        return VIEWER_HOST
    return host


def start_path(name):
    """Path ``serve`` opens the browser at."""
    if not name:
        return "/"
    try:
        _catalog, version = load_raw_catalog(name)
    except MvaultError:
        # An unknown vault still resolves through the catalog route, which
        # sends the browser back to the landing page with a notice.
        return viewer_path("catalog", name)
    return viewer_path("catalog", name, default_category(version))


def open_browser(url):
    """Open ``url`` in the default browser without blocking the server."""
    def run():
        try:
            webbrowser.open(url)
        except Exception:
            pass  # a headless machine simply gets no browser window

    threading.Thread(target=run, daemon=True).start()


def parse_port(value):
    text = value.strip()
    if not text.isdigit():
        raise MvaultError("option --port expects a port number (got %r)" % value)
    port = int(text, 10)
    if port > 65535:
        raise MvaultError("option --port expects a port number (got %r)" % value)
    return port


def parse_serve_args(args):
    """Return ``(name, options)`` for the serve subcommand."""
    options = {"host": VIEWER_HOST, "port": VIEWER_PORT, "browser": True}
    positional = []

    for arg in args:
        if not arg.startswith("-") or arg == "-":
            positional.append(arg)
            continue
        if not arg.startswith("--"):
            raise MvaultError("unrecognized option %r" % arg)

        name, sep, value = arg[2:].partition("=")
        key = name.replace("-", "_")
        if key == "host" and sep:
            if not value.strip():
                raise MvaultError("option --host expects a host name")
            options["host"] = value.strip()
        elif key == "port" and sep:
            options["port"] = parse_port(value)
        elif key == "no_browser" and not sep:
            options["browser"] = False
        else:
            raise MvaultError("unrecognized option %r" % arg)

    if len(positional) > 1:
        raise MvaultError("usage: mvault.py serve [<name>] [--host=<host>] "
                          "[--port=<port>]")
    return (positional[0] if positional else None), options


def command_serve(args):
    name, options = parse_serve_args(args)

    try:
        server = ThreadingHTTPServer((options["host"], options["port"]),
                                     ViewerHandler)
    except OSError as exc:
        raise MvaultError("cannot serve on %s:%s (%s)"
                          % (options["host"], options["port"], exc))
    server.daemon_threads = True

    host = browser_host(options["host"])
    port = server.server_address[1]
    url = "%s://%s:%d%s" % (VIEWER_SCHEME, host, port, start_path(name))

    browse = options["browser"] and not os.environ.get("MVAULT_NO_BROWSER")
    print("serving vault viewer at %s://%s:%d/" % (VIEWER_SCHEME, host, port))
    print("%s %s" % ("opening" if browse else "entry point:", url))
    sys.stdout.flush()

    if browse:
        open_browser(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


COMMANDS = {"init": command_init, "sync": command_sync,
            "migrate": command_migrate, "digest": command_digest,
            "serve": command_serve}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv:
        sys.stderr.write(USAGE)
        return 2

    subcommand, args = argv[0], argv[1:]

    if subcommand in ("-h", "--help", "help"):
        sys.stdout.write(USAGE)
        return 0

    handler = COMMANDS.get(subcommand)
    if handler is None:
        sys.stderr.write("error: unknown subcommand %r\n\n" % subcommand)
        sys.stderr.write(USAGE)
        return 2

    if any(arg in ("-h", "--help") for arg in args):
        sys.stdout.write(USAGE)
        return 0

    try:
        return handler(args)
    except MvaultError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
