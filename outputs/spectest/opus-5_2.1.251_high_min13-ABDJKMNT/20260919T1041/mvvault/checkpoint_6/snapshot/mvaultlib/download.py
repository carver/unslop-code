"""The download phase of `sync`: media and preview files for pending entries.

Downloads never fail a run. Each asset that cannot be retrieved produces one
warning on stderr, and the phase moves on to the next entry.
"""

import mimetypes
import sys
import time
from pathlib import Path

import requests

from .schema import CATEGORIES

MEDIA_DIR = "media"
PREVIEW_DIR = "previews"

#: Suffix of the file an in-flight download writes to before it is renamed.
PARTIAL_SUFFIX = ".part"

#: Extension used when the response carries no recognizable `Content-Type`.
DEFAULT_EXTENSION = ".bin"

REQUEST_TIMEOUT = 30
ATTEMPTS = 3
RETRY_DELAY = 0.25

#: Statuses worth retrying; every other unsuccessful status is permanent.
TRANSIENT_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


def run(name, catalog, limits, media_format):
    """Download the media and preview file of every pending catalog entry.

    `limits` maps each category to its maximum number of media downloads, or to
    `None` for no limit. `media_format` overrides both the remote media path and
    the stored extension.
    """
    media_dir = _prepared(Path(name) / MEDIA_DIR)
    preview_dir = _prepared(Path(name) / PREVIEW_DIR)
    source = catalog["source"].rstrip("/")

    for category in CATEGORIES:
        for entry in _candidates(catalog[category], media_dir, limits[category]):
            entry_id = entry["id"]
            _store(f"{source}/media/{_remote_media_name(entry_id, media_format)}", media_dir, entry_id, media_format)
            _store(f"{source}/preview/{entry_id}", preview_dir, entry_id, None)


def _prepared(directory):
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _candidates(entries, media_dir, limit):
    """Entries still missing their media file, in catalog order, capped at `limit`."""
    stored = _stored_ids(media_dir)
    pending = [entry for entry in entries if entry["id"] not in stored]
    return pending if limit is None else pending[:limit]


def _stored_ids(directory):
    """Entry ids that already have a finished file; partial artifacts do not count."""
    return {path.name.split(".", 1)[0] for path in directory.iterdir() if path.suffix != PARTIAL_SUFFIX}


def _store(url, directory, entry_id, extension_override):
    """Download `url` into `directory` as `<entry_id>.<extension>`, if it can be had.

    The body is written to a partial file first and renamed into place once it
    is complete, so an interrupted run never leaves a file that later looks like
    a finished download.
    """
    response = _fetch(url)
    if response is None:
        return
    partial = directory / (entry_id + PARTIAL_SUFFIX)
    partial.write_bytes(response.content)
    partial.replace(directory / (entry_id + _extension(response, extension_override)))


def _fetch(url):
    """GET `url`, retrying transient failures; warn and return `None` on failure."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            problem, transient = exc, True
        else:
            if response.ok:
                return response
            problem, transient = f"HTTP {response.status_code}", response.status_code in TRANSIENT_STATUSES

        if not transient:
            break
        if attempt < ATTEMPTS:
            time.sleep(RETRY_DELAY)

    print(f"mvault: warning: could not download {url}: {problem}", file=sys.stderr)
    return None


def _extension(response, override):
    """The stored extension: the override, or the response's own media type."""
    if override:
        return "." + override
    media_type = response.headers.get("Content-Type", "").split(";")[0].strip()
    return mimetypes.guess_extension(media_type) or DEFAULT_EXTENSION


def _remote_media_name(entry_id, media_format):
    """The last path segment of the remote media URL."""
    return f"{entry_id}.{media_format}" if media_format else entry_id
