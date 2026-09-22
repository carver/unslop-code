"""Downloading the media and preview files of catalog entries.

The download phase of ``sync`` walks the catalog in order and retrieves what
the vault does not hold yet.  A download that fails is reported on stderr and
skipped: the metadata a sync recorded is worth keeping even when the media
behind it is temporarily or permanently out of reach.
"""

import mimetypes
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import IO, Mapping, Optional

import catalogs

#: Vault subdirectories the two kinds of file are stored in.
MEDIA_DIRECTORY = "media"
PREVIEW_DIRECTORY = "previews"

#: Suffix of a download still in progress, ignored when taking stock.
PARTIAL_SUFFIX = ".part"

#: Extension used when the response does not name a type mvault knows.
DEFAULT_EXTENSION = ".bin"

#: Attempts per file, and the pause between them, for transient failures.
ATTEMPTS = 3
RETRY_DELAY_SECONDS = 0.25

#: Client errors that are worth another attempt rather than a final failure.
RETRYABLE_STATUSES = frozenset({408, 429})

#: Per-category caps on media downloads; a missing category means no cap.
Limits = Mapping[str, Optional[int]]


def download_entries(
    vault: Path, catalog: catalogs.Catalog, limits: Limits, media_format: Optional[str]
) -> str:
    """Fetch the media and preview file of every entry the vault is missing.

    ``media_format`` asks the source for one specific format and names the
    file after it; without it the extension follows the response type.
    """
    media = vault / MEDIA_DIRECTORY
    candidates = [
        entry["id"]
        for category in catalogs.CATEGORIES
        for entry in _candidates(catalog[category], media, limits.get(category))
    ]
    source = catalog["source"].rstrip("/")
    outcomes = [
        outcome
        for identifier in candidates
        for outcome in _entry_files(vault, source, identifier, media_format)
    ]
    return f"Downloaded {outcomes.count(True)} of {len(outcomes)} files"


def _entry_files(
    vault: Path, source: str, identifier: str, media_format: Optional[str]
) -> list[bool]:
    """Fetch the two files of one entry, reporting how each one went."""
    override = f".{media_format}" if media_format else ""
    return [
        _download(
            f"{source}/{MEDIA_DIRECTORY}/{identifier}{override}",
            vault / MEDIA_DIRECTORY,
            identifier,
            override,
        ),
        _download(f"{source}/preview/{identifier}", vault / PREVIEW_DIRECTORY, identifier, ""),
    ]


def _candidates(
    entries: list[catalogs.Entry], media: Path, limit: Optional[int]
) -> list[catalogs.Entry]:
    """The first ``limit`` entries of a category that have no media file yet.

    An entry is held to be downloaded once a file naming it sits in the media
    directory.  Leftovers of an interrupted download name their entry too, so
    they are passed over here and overwritten by the next attempt.
    """
    held = [path.name for path in media.glob("*") if not path.name.endswith(PARTIAL_SUFFIX)]
    missing = [entry for entry in entries if not any(entry["id"] in name for name in held)]
    return missing if limit is None else missing[:limit]


def _download(url: str, directory: Path, name: str, extension: str) -> bool:
    """Store ``url`` in ``directory`` under ``name``, warning when it fails."""
    try:
        _save(url, directory, name, extension)
    except OSError as error:
        print(f"Warning: cannot download {url}: {error}", file=sys.stderr)
        return False
    return True


def _save(url: str, directory: Path, name: str, extension: str) -> None:
    """Write the body of ``url`` to a file, revealed only once complete."""
    with _open(url) as response:
        suffix = extension or _extension(response.headers.get("Content-Type"))
        directory.mkdir(parents=True, exist_ok=True)
        partial = directory / f"{name}{suffix}{PARTIAL_SUFFIX}"
        with partial.open("wb") as target:
            shutil.copyfileobj(response, target)
    partial.replace(directory / f"{name}{suffix}")


def _open(url: str) -> IO[bytes]:
    """Open ``url``, retrying a failure that may not be the last word.

    Content the source says is simply not there is not retried; anything else,
    from a refused connection to a server error, is tried again a few times
    before the failure is passed on.
    """
    for _ in range(ATTEMPTS - 1):
        try:
            return urllib.request.urlopen(url)
        except OSError as error:
            if _is_permanent(error):
                raise
            time.sleep(RETRY_DELAY_SECONDS)
    return urllib.request.urlopen(url)


def _is_permanent(error: OSError) -> bool:
    """True when retrying ``error`` cannot produce the content."""
    return (
        isinstance(error, urllib.error.HTTPError)
        and 400 <= error.code < 500
        and error.code not in RETRYABLE_STATUSES
    )


def _extension(content_type: Optional[str]) -> str:
    """Pick the file extension the response content type stands for."""
    media_type = (content_type or "").split(";")[0].strip()
    return mimetypes.guess_extension(media_type) or DEFAULT_EXTENSION
