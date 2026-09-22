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
  serve [<name>]      browse vaults in a local web viewer and open a browser

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
ul.entries li.highlight { outline: 3px solid #f5c211; background: #fdf6d3; }
.badge { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em;
         border-radius: 999px; padding: 0.1rem 0.5rem; margin-left: 0.4rem; }
.state-downloaded { background: #2ec27e; color: #06281a; }
.state-missing { background: #deddda; color: #3d3846; }
.state-removed { background: #c01c28; color: #fff; }
nav.categories a { margin-right: 0.75rem; }
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


def render_entry_item(name, version, category, entry, media_names, highlight):
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

    current = highlight is not None and entry_id == highlight
    if current:
        classes.append("highlight")

    return ("<li class=\"%s\" id=\"entry-%s\"%s><a class=\"title\" href=\"%s\">%s</a>"
            " <span class=\"eid\">%s</span>%s</li>"
            % (" ".join(classes), escape(entry_id),
               " aria-current=\"true\"" if current else "",
               escape(viewer_path("catalog", name, category, entry_id)),
               escape(entry_title(entry, version)), escape(entry_id),
               "".join(badges)))


def render_listing(name, version, category, entries, media_names, highlight=None):
    """Category listing page, optionally surfacing one entry."""
    nav = " ".join(
        "<a href=\"%s\">%s</a>" % (escape(viewer_path("catalog", name, known)),
                                   escape(known))
        for known in valid_categories(version))

    parts = ["<h1>%s</h1>" % escape(name),
             "<p class=\"crumbs\"><a href=\"/\">all vaults</a> &middot; "
             "category <strong>%s</strong> &middot; catalog version %d</p>"
             % (escape(category), version),
             "<nav class=\"categories\">%s</nav>" % nav]

    if highlight is not None:
        parts.append("<p class=\"selected\">Showing entry <code>%s</code></p>"
                     % escape(highlight))

    if entries:
        items = "\n".join(
            render_entry_item(name, version, category, entry, media_names, highlight)
            for entry in entries)
        parts.append("<ul class=\"entries\">\n%s\n</ul>" % items)
    else:
        parts.append("<p class=\"empty\">No entries in this category.</p>")

    return render_page("%s / %s" % (name, category), "\n".join(parts))


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

    def dispatch(self):
        """Route one request, turning any failure into a proper HTTP response."""
        try:
            parsed = urlsplit(self.path)
            segments = [unquote(part) for part in parsed.path.split("/") if part]
            query = parse_qs(parsed.query)

            if self.command == "POST":
                fields = self.read_form()
                if segments:
                    return self.fail(404, "unknown path")
                return self.handle_open(fields)

            if not segments:
                return self.handle_landing(query)
            if segments == [STYLE_PATH.lstrip("/")]:
                return self.respond(200, STYLE, "text/css; charset=utf-8")
            if segments[0] == "catalog" and len(segments) >= 2:
                return self.handle_catalog(segments[1:])
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

    def read_form(self):
        """Consume and decode a form-encoded request body.

        The body is always read, even for routes that ignore it, so a kept
        alive connection stays in sync for the next request.
        """
        if self.headers.get("Transfer-Encoding"):
            # Only length-delimited bodies are understood; anything else would
            # leave unread bytes behind, so the connection ends with the reply.
            self.close_connection = True
            return {}

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        return parse_qs(raw.decode("utf-8", "replace"))

    def handle_open(self, fields):
        """``POST /``: send the submitted vault name to its catalog page."""
        values = fields.get("catalog") or []
        name = values[0].strip() if values else ""
        if not name:
            return self.redirect("/", status=303)
        return self.redirect(viewer_path("catalog", name), status=303)

    def handle_catalog(self, segments):
        name = segments[0]
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
            return self.redirect(fallback, headers=headers)
        if len(segments) > 3:
            return self.fail(404, "unknown path")

        highlight = segments[2] if len(segments) == 3 else None
        body = render_listing(name, version, category,
                              category_entries(catalog, version, category),
                              media_filenames(name), highlight)
        self.respond(200, body, headers=headers)


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
