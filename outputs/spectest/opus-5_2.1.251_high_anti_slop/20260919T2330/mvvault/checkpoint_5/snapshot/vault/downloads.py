"""Downloading the media and preview files of catalog entries into a vault.

Only entries whose media file is still missing are candidates, taken in catalog
order and capped per category by the ``sync`` limits. A download is written to a
``.part`` file and renamed once complete, so an interrupted run leaves nothing
that a later run would mistake for stored media.
"""

import mimetypes
import sys
import time
from pathlib import Path

import requests

from .catalog import CATEGORIES

MEDIA_DIR = "media"
PREVIEW_DIR = "previews"
REQUEST_TIMEOUT = 60
CHUNK_SIZE = 64 * 1024
#: Total number of tries per asset, including the first, before giving up.
ATTEMPTS = 3
#: Seconds to wait before a retry, multiplied by the number of tries so far.
RETRY_DELAY = 0.2
PARTIAL_SUFFIX = ".part"
#: Extension used when the response carries no usable ``Content-Type``.
FALLBACK_EXTENSION = "bin"
#: Status codes that are worth retrying even though the server answered.
RETRYABLE_STATUSES = (408, 429)


def run(name, catalog, limits, media_format):
    """Download the missing media, and the matching previews, of the vault ``name``.

    ``limits`` caps the number of media downloads per category, with ``None``
    meaning no cap; ``media_format`` overrides both the requested format and the
    stored extension. Entries that cannot be fetched are reported on stderr and
    skipped, leaving the rest of the run untouched.
    """
    media_dir = _prepared(Path(name) / MEDIA_DIR)
    preview_dir = _prepared(Path(name) / PREVIEW_DIR)
    base = catalog["source"].rstrip("/")
    requested = f".{media_format}" if media_format else ""
    for category in CATEGORIES:
        for entry in _candidates(catalog[category], media_dir, limits[category]):
            entry_id = entry["id"]
            _download(f"{base}/media/{entry_id}{requested}", media_dir, entry_id, media_format)
            if entry_id not in _stored_ids(preview_dir):
                _download(f"{base}/preview/{entry_id}", preview_dir, entry_id, None)


def _prepared(directory):
    """Return a vault subdirectory, creating it when the vault has never downloaded."""
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _candidates(entries, media_dir, limit):
    """Pick the entries with no stored media, in catalog order, up to ``limit`` of them."""
    stored = _stored_ids(media_dir)
    missing = [entry for entry in entries if entry["id"] not in stored]
    return missing if limit is None else missing[:limit]


def _stored_ids(directory):
    """Entry ids that already have a file in ``directory``; ``.part`` files do not count."""
    return {path.stem for path in directory.iterdir() if path.suffix != PARTIAL_SUFFIX}


def _download(url, directory, entry_id, extension):
    """Fetch ``url`` into ``directory``, retrying transient failures before warning."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
            response.raise_for_status()
        except requests.RequestException as error:
            if _is_permanent(error):
                _warn(f"skipping {url}: {error}")
                return
            if attempt == ATTEMPTS:
                _warn(f"skipping {url} after {ATTEMPTS} attempts: {error}")
                return
            time.sleep(RETRY_DELAY * attempt)
            continue
        _store(response, directory, entry_id, extension)
        return


def _is_permanent(error):
    """Tell whether a failed request states a problem that a retry cannot fix."""
    response = getattr(error, "response", None)
    if response is None:
        return False
    return 400 <= response.status_code < 500 and response.status_code not in RETRYABLE_STATUSES


def _store(response, directory, entry_id, extension):
    """Stream a response to ``<entry_id>.<extension>``, via a ``.part`` file."""
    suffix = extension or _extension_for(response.headers.get("Content-Type"))
    target = directory / f"{entry_id}.{suffix}"
    partial = target.with_name(target.name + PARTIAL_SUFFIX)
    with partial.open("wb") as handle:
        for chunk in response.iter_content(CHUNK_SIZE):
            handle.write(chunk)
    partial.replace(target)


def _extension_for(content_type):
    """Derive a file extension from a ``Content-Type`` header, without its parameters."""
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    return guessed[1:] if guessed else FALLBACK_EXTENSION


def _warn(message):
    """Report a skipped download on stderr without ending the run."""
    print(f"mvault.py: warning: {message}", file=sys.stderr)
