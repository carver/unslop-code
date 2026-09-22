"""The `sync` download phase: fetching media and preview files into the vault.

Downloads never fail a run. Each asset is fetched independently, transient
failures are retried, and anything that still cannot be fetched is reported as a
warning so the remaining entries are still attempted.
"""

import mimetypes
import urllib.error
import urllib.request

from mvaultlib.entries import CATEGORIES

MEDIA_DIR = "media"
PREVIEW_DIR = "previews"

#: Suffix written for an in-progress download.
PARTIAL_SUFFIX = ".part"

#: Suffixes that mark a partial-download artifact rather than stored media.
PARTIAL_SUFFIXES = (PARTIAL_SUFFIX, ".partial", ".tmp", ".download", ".crdownload")

#: Attempts made for one asset before a transient failure is reported.
RETRY_ATTEMPTS = 3

#: Statuses at or above this are treated as transient and retried.
TRANSIENT_STATUS_FLOOR = 500

FALLBACK_EXTENSION = "bin"


class DownloadFailure(Exception):
    """One asset could not be fetched; the rest of the run continues."""


def download_assets(vault_path, catalog, options, warn):
    """Fetch media and previews for the candidate entries of every category."""
    media_dir = vault_path / MEDIA_DIR
    source = catalog["source"].rstrip("/")
    for category in CATEGORIES:
        for entry in candidates(catalog[category], media_dir, options.limits.get(category)):
            _download_entry(vault_path, source, entry["id"], options.format_override, warn)


def candidates(entries, media_dir, limit):
    """Entries with no stored media yet, in catalog order, capped at `limit`."""
    stored = stored_asset_names(media_dir)
    pending = [entry for entry in entries if matching_asset(entry["id"], stored) is None]
    return pending if limit is None else pending[:limit]


def stored_asset_names(directory):
    """Names of finished assets in `directory`; partial downloads are ignored."""
    if not directory.is_dir():
        return []
    return sorted(
        path.name for path in directory.iterdir() if not path.name.endswith(PARTIAL_SUFFIXES)
    )


def matching_asset(entry_id, stored_names):
    """The first stored file name containing `entry_id`, or None when none does.

    Names are compared in sorted order, so an entry with several stored files
    always resolves to the same one.
    """
    matches = [name for name in stored_names if entry_id in name]
    return matches[0] if matches else None


def _download_entry(vault_path, source, entry_id, format_override, warn):
    """Fetch the media file and the preview file of one entry."""
    remote_media = f"{entry_id}.{format_override}" if format_override else entry_id
    _store(f"{source}/media/{remote_media}", vault_path / MEDIA_DIR, entry_id, format_override, warn)
    _store(f"{source}/preview/{entry_id}", vault_path / PREVIEW_DIR, entry_id, None, warn)


def _store(url, directory, entry_id, extension, warn):
    """Fetch one asset into `<directory>/<entry_id>.<extension>`, warning on failure.

    The payload lands on a partial file first, so an interrupted write can never
    be mistaken for a stored asset.
    """
    try:
        content_type, payload = _fetch(url)
    except DownloadFailure as failure:
        warn(f"entry '{entry_id}': {failure}")
        return
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{entry_id}.{extension or _extension(content_type)}"
    partial = target.with_name(target.name + PARTIAL_SUFFIX)
    partial.write_bytes(payload)
    partial.replace(target)


def _fetch(url):
    """GET `url`, retrying transient failures, and return its type and payload."""
    detail = None
    for _ in range(RETRY_ATTEMPTS):
        try:
            with urllib.request.urlopen(url) as response:
                return response.headers.get_content_type(), response.read()
        except urllib.error.HTTPError as error:
            if error.code < TRANSIENT_STATUS_FLOOR:
                raise DownloadFailure(f"{url} is unavailable (status {error.code})") from error
            detail = f"status {error.code}"
        except (urllib.error.URLError, OSError) as error:
            detail = str(error)
    raise DownloadFailure(f"{url} still failed after {RETRY_ATTEMPTS} attempts ({detail})")


def _extension(content_type):
    """The file extension a response `Content-Type` implies."""
    guessed = mimetypes.guess_extension(content_type)
    return guessed.lstrip(".") if guessed else FALLBACK_EXTENSION
