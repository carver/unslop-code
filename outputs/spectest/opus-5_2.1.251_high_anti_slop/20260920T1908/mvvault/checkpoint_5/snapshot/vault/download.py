"""Retrieving the media and preview files of catalog entries.

A vault keeps its media under ``media/`` and its preview images under
``previews/``, both named after the entry they belong to. Presence of a media
file is what marks an entry as already downloaded, so the entries still
missing one are the candidates of the next run.
"""

import mimetypes
import sys
import time
from pathlib import Path

import requests

from .schema import CATEGORIES

MEDIA_DIR = "media"
PREVIEW_DIR = "previews"
PARTIAL_SUFFIX = ".part"
DEFAULT_EXTENSION = ".bin"

REQUEST_TIMEOUT = 30
CHUNK_SIZE = 64 * 1024
ATTEMPTS = 3
RETRY_PAUSE = 0.5


def download_assets(
    vault_dir: Path, catalog: dict, limits: dict[str, int | None], media_format: str | None = None
) -> None:
    """Download the media and preview file of entries that have no media yet.

    Candidates are taken in catalog order, at most ``limits[category]`` per
    category and all of them where the category has no limit. A file that
    cannot be fetched is reported on stderr and skipped, so one unavailable
    entry does not stop the rest of the run.
    """
    media_dir = vault_dir / MEDIA_DIR
    preview_dir = vault_dir / PREVIEW_DIR
    media_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)
    source = catalog["source"]
    extension = f".{media_format}" if media_format else None
    for category in CATEGORIES:
        for entry in _candidates(catalog[category], media_dir, limits.get(category)):
            entry_id = entry["id"]
            _download(f"{source}/media/{entry_id}{extension or ''}", media_dir, entry_id, extension)
            _download(f"{source}/preview/{entry_id}", preview_dir, entry_id)


def _candidates(entries: list, media_dir: Path, limit: int | None) -> list:
    """The entries of one category that still need downloading, up to ``limit``."""
    downloaded = _downloaded_ids(media_dir)
    missing = [entry for entry in entries if entry["id"] not in downloaded]
    return missing if limit is None else missing[:limit]


def _downloaded_ids(media_dir: Path) -> set[str]:
    """Entry ids that already have a media file.

    A download that was interrupted leaves a partial file, which names no id
    and so leaves its entry a candidate for the next run.
    """
    return {
        path.name.split(".")[0]
        for path in media_dir.iterdir()
        if path.is_file() and not path.name.endswith(PARTIAL_SUFFIX)
    }


def _download(url: str, directory: Path, name: str, extension: str | None = None) -> None:
    """Store ``url`` as ``<directory>/<name><extension>``, retrying temporary failures.

    Without an extension the file takes the one implied by the response's
    ``Content-Type``. Content that turns out to be permanently unavailable, and
    content still unreachable once the retries run out, is reported on stderr
    and left for a later run.
    """
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with requests.get(url, timeout=REQUEST_TIMEOUT, stream=True) as response:
                response.raise_for_status()
                _save(response, directory / f"{name}{extension or _extension(response)}")
            return
        except requests.HTTPError as error:
            if error.response.status_code < 500:
                _warn(f"{url} is unavailable ({error.response.status_code}), skipping it")
                return
            failure = error
        except (requests.RequestException, OSError) as error:
            failure = error
        if attempt < ATTEMPTS:
            time.sleep(RETRY_PAUSE * attempt)
    _warn(f"{url} could not be downloaded in {ATTEMPTS} attempts: {failure}")


def _save(response: requests.Response, path: Path) -> None:
    """Write the response body next to its target, then move it into place.

    A download that dies half way leaves a partial file behind rather than a
    truncated one that the next run would take for a finished download.
    """
    partial = path.with_name(path.name + PARTIAL_SUFFIX)
    with partial.open("wb") as handle:
        for chunk in response.iter_content(CHUNK_SIZE):
            handle.write(chunk)
    partial.replace(path)


def _extension(response: requests.Response) -> str:
    """Read the file extension a response's ``Content-Type`` calls for."""
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
    return mimetypes.guess_extension(content_type) or DEFAULT_EXTENSION


def _warn(message: str) -> None:
    print(f"mvault: {message}", file=sys.stderr)
