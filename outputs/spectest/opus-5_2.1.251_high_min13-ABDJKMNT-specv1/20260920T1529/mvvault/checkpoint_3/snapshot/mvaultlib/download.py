"""The download phase of `sync`: media and preview files for catalog entries.

Downloads never fail a run. Each asset is fetched on its own, transient
failures are retried, and anything that still does not arrive is reported as a
warning so the remaining entries keep their turn.
"""

import mimetypes
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .source import CATEGORIES

MEDIA_DIR = "media"
PREVIEW_DIR = "previews"

# Downloads land under a partial name first; a leftover partial is a stale
# artifact rather than a finished file, and never satisfies an entry.
PARTIAL_SUFFIX = ".part"
PARTIAL_SUFFIXES = (PARTIAL_SUFFIX, ".partial", ".tmp", ".download", ".crdownload")

ATTEMPTS = 3
# Client statuses that mean "later, maybe"; every other 4xx is permanent.
TRANSIENT_STATUSES = (408, 425, 429)


class DownloadFailure(Exception):
    """One asset did not arrive; the sync run continues without it."""


def download_assets(name, catalog, limits, media_format):
    """Fetch media and previews for the entries that have no media file yet."""
    vault = Path(name)
    extension = f".{media_format.lstrip('.')}" if media_format else None

    for category in CATEGORIES:
        candidates = select_candidates(catalog[category], vault / MEDIA_DIR, limits.get(category))
        for entry in candidates:
            fetch_entry(catalog["source"], vault, entry["id"], extension)


def select_candidates(entries, media_dir, limit):
    """Entries with no media file yet, in catalog order, capped at `limit`."""
    stored = stored_names(media_dir)
    candidates = [entry for entry in entries if not is_stored(entry["id"], stored)]
    return candidates if limit is None else candidates[:limit]


def stored_names(media_dir):
    """The names in `<vault>/media/` that count as finished downloads."""
    if not media_dir.is_dir():
        return []
    return [path.name for path in media_dir.iterdir() if not path.name.endswith(PARTIAL_SUFFIXES)]


def is_stored(entry_id, stored):
    """Whether any stored media file name contains `entry_id`."""
    return any(entry_id in name for name in stored)


def fetch_entry(source, vault, entry_id, extension):
    """Download one entry's media and preview from `source`."""
    base = source.rstrip("/")
    media_name = f"{entry_id}{extension}" if extension else entry_id
    retrieve(f"{base}/media/{media_name}", vault / MEDIA_DIR, entry_id, extension, "media")
    retrieve(f"{base}/preview/{entry_id}", vault / PREVIEW_DIR, entry_id, None, "preview")


def retrieve(url, directory, entry_id, extension, label):
    """Fetch one asset into `directory`, or warn on stderr and move on."""
    try:
        content_type, body = get(url)
    except DownloadFailure as failure:
        print(f"warning: no {label} downloaded for '{entry_id}': {failure}", file=sys.stderr)
        return
    store(directory, entry_id, extension or extension_for(content_type), body)


def get(url):
    """Fetch `url` as `(content type, body)`, retrying transient failures."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url) as response:
                return response.headers.get_content_type(), response.read()
        except urllib.error.HTTPError as error:
            if attempt == ATTEMPTS or not is_transient(error.code):
                raise DownloadFailure(f"{url}: HTTP {error.code}") from error
        except OSError as error:
            if attempt == ATTEMPTS:
                raise DownloadFailure(f"{url}: {error}") from error


def is_transient(status):
    """Whether an HTTP status is worth retrying."""
    return status >= 500 or status in TRANSIENT_STATUSES


def extension_for(content_type):
    """The file extension a response's `Content-Type` implies, if any."""
    return mimetypes.guess_extension(content_type) or ""


def store(directory, entry_id, extension, body):
    """Write the body to its partial name, then rename it into place."""
    directory.mkdir(parents=True, exist_ok=True)
    partial = directory / f"{entry_id}{PARTIAL_SUFFIX}"
    partial.write_bytes(body)
    partial.replace(directory / f"{entry_id}{extension}")
