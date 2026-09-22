"""The download phase of `sync`: media and preview files for catalog entries.

Every asset is fetched into a `.part` file and renamed into place only once the
body is complete, so an interrupted run never leaves something that looks like a
finished download. A failure here is reported and stepped over: the metadata the
run already persisted is worth keeping even when the media is unavailable.
"""

import sys
import time

import requests

from .catalog import CATEGORIES

REQUEST_TIMEOUT = 60

#: Attempts made for one asset before a transient failure is given up on.
MAX_ATTEMPTS = 3

#: Pause between attempts, long enough to outlast a momentary server hiccup.
RETRY_DELAY = 0.25

#: Suffix an in-progress download occupies; never mistaken for a finished file.
PARTIAL_SUFFIX = ".part"

#: Statuses that describe a temporary condition rather than a missing asset.
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})

#: Media types whose conventional extension is not simply their subtype.
EXTENSION_OVERRIDES = {
    "image/jpeg": "jpg",
    "audio/mpeg": "mp3",
    "video/quicktime": "mov",
    "text/plain": "txt",
    "application/octet-stream": "bin",
}

DEFAULT_EXTENSION = "bin"


class DownloadError(Exception):
    """One asset could not be retrieved; `transient` says whether a retry may help."""

    def __init__(self, message, transient):
        super().__init__(message)
        self.transient = transient


def download_assets(vault, catalog, limits, media_format):
    """Fetch the media and preview files the vault is still missing.

    `limits` maps each category to its maximum number of media downloads, or to
    None for no limit. `media_format` overrides both the remote media path and
    the stored extension when it is given.
    """
    source = catalog["source"].rstrip("/")
    for category in CATEGORIES:
        for entry in _candidates(vault.media_path, catalog[category], limits[category]):
            entry_id = entry["id"]
            _download(vault.media_path, _media_url(source, entry_id, media_format), entry_id, media_format)
            _download(vault.previews_path, f"{source}/preview/{entry_id}", entry_id)


def _candidates(media_path, entries, limit):
    """Entries that have no media file yet, in catalog order, capped at `limit`."""
    downloaded = _downloaded_ids(media_path)
    missing = [entry for entry in entries if entry["id"] not in downloaded]
    return missing if limit is None else missing[:limit]


def _downloaded_ids(media_path):
    """Entry ids that already own a finished media file."""
    if not media_path.is_dir():
        return frozenset()
    return frozenset(path.stem for path in media_path.iterdir() if path.suffix != PARTIAL_SUFFIX)


def _media_url(source, entry_id, media_format):
    """The media URL; a format override becomes part of the remote path."""
    extension = f".{media_format}" if media_format else ""
    return f"{source}/media/{entry_id}{extension}"


def _download(directory, url, entry_id, extension=None):
    """Store one asset, warning on stderr rather than failing the run."""
    try:
        _store(directory, url, entry_id, extension)
    except DownloadError as error:
        print(f"mvault: warning: entry {entry_id!r}: {error}", file=sys.stderr)


def _store(directory, url, entry_id, extension):
    """Write the asset at `url` into `directory` under the entry's id.

    Without an explicit `extension` the response's `Content-Type` supplies one.
    """
    response = _retrieve(url)
    directory.mkdir(parents=True, exist_ok=True)
    partial = directory / f"{entry_id}{PARTIAL_SUFFIX}"
    partial.write_bytes(response.content)
    partial.replace(directory / f"{entry_id}.{extension or extension_for(response)}")


def _retrieve(url):
    """GET `url`, retrying transient failures until the attempts are spent."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _get(url)
        except DownloadError as error:
            if not error.transient or attempt == MAX_ATTEMPTS:
                raise
            time.sleep(RETRY_DELAY)


def _get(url):
    """One GET attempt, raising DownloadError with its transience on failure."""
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as error:
        raise DownloadError(f"{url}: {error}", transient=True) from error

    if not response.ok:
        raise DownloadError(
            f"{url}: HTTP {response.status_code}",
            transient=response.status_code in RETRY_STATUSES,
        )
    return response


def extension_for(response):
    """The file extension a response's `Content-Type` implies."""
    media_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if media_type in EXTENSION_OVERRIDES:
        return EXTENSION_OVERRIDES[media_type]
    return media_type.rpartition("/")[2] or DEFAULT_EXTENSION
