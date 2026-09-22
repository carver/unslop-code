"""Downloading the media and preview files of catalog entries.

The download phase is best effort: an asset that cannot be fetched is reported
on stderr and the remaining entries are still tried, so one dead item never
costs a sync its other downloads.
"""

import http.client
import mimetypes
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .source import CATEGORIES

MEDIA_PATH = "media"
PREVIEW_PATH = "preview"
MEDIA_DIRECTORY = "media"
PREVIEW_DIRECTORY = "previews"
PARTIAL_SUFFIX = ".part"
ATTEMPTS = 3
RETRY_PAUSE_SECONDS = 0.5


def run(name, stored, limits, media_format):
    """Download what the vault ``name`` is missing from its source.

    ``limits`` caps how many entries of each category are downloaded; a
    ``None`` limit downloads every candidate. ``media_format`` overrides both
    the requested media format and the stored extension when it is given.
    """
    vault = Path(name)
    for category in CATEGORIES:
        for entry in _candidates(stored[category], vault / MEDIA_DIRECTORY, limits[category]):
            _download_entry(vault, stored["source"], entry["id"], media_format)


def _download_entry(vault, source, identifier, media_format):
    """Fetch one entry's media file and its preview image.

    A format override asks the source for that format and stores the media
    under it; without one the source picks, and its content type names the
    extension the file is stored under.
    """
    requested = f"{identifier}.{media_format}" if media_format else identifier
    _store_asset(
        _asset_url(source, MEDIA_PATH, requested),
        vault / MEDIA_DIRECTORY,
        identifier,
        f".{media_format}" if media_format else None,
    )
    _store_asset(
        _asset_url(source, PREVIEW_PATH, identifier),
        vault / PREVIEW_DIRECTORY,
        identifier,
        None,
    )


def _candidates(entries, media_directory, limit):
    """The first ``limit`` entries, in catalog order, that have no media yet.

    A media file counts as stored when its name contains the entry id. The
    partial file of an interrupted download does not count, so a stale one
    leaves its entry a candidate.
    """
    stored = [
        path.name
        for path in media_directory.glob("*")
        if not path.name.endswith(PARTIAL_SUFFIX)
    ]
    missing = [entry for entry in entries if not any(entry["id"] in name for name in stored)]
    return missing if limit is None else missing[:limit]


def _asset_url(source, path, name):
    """URL of one asset below the vault's source URL."""
    return f"{source.rstrip('/')}/{path}/{name}"


def _store_asset(url, directory, identifier, extension):
    """Fetch ``url`` into ``directory``, warning instead of failing the sync.

    Transient failures are retried; a permanent one, or a transient one that
    outlives the retries, leaves a warning on stderr and nothing on disk.
    """
    for attempts_left in reversed(range(ATTEMPTS)):
        try:
            _fetch(url, directory, identifier, extension)
            return
        except (OSError, http.client.HTTPException) as error:
            if not attempts_left or not _is_transient(error):
                print(f"mvault: could not download {url}: {error}", file=sys.stderr)
                return
            time.sleep(RETRY_PAUSE_SECONDS)


def _fetch(url, directory, identifier, extension):
    """Download ``url`` once, naming the file after ``identifier``.

    The body is written to a partial file that is renamed only once the
    transfer finished, so a half-written file is never mistaken for an asset.
    """
    directory.mkdir(parents=True, exist_ok=True)
    partial = directory / (identifier + PARTIAL_SUFFIX)
    with urllib.request.urlopen(url) as response:
        suffix = extension or _content_extension(response.headers.get_content_type())
        with partial.open("wb") as sink:
            shutil.copyfileobj(response, sink)
    partial.replace(directory / (identifier + suffix))


def _content_extension(content_type):
    """Extension for a response's content type, empty when it names none."""
    return mimetypes.guess_extension(content_type) or ""


def _is_transient(error):
    """Whether a failure is worth retrying rather than reporting straight away.

    A 4xx status says the content is not there to be had; a server status or a
    transport problem may well pass.
    """
    return not isinstance(error, urllib.error.HTTPError) or error.code >= 500
