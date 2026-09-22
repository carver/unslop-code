"""The read model behind the viewer's pages: vault lookup and category listings.

The viewer reads a catalog exactly as stored, whatever version it declares, so
browsing a v1 or v2 vault never migrates it. Anything that makes a vault
unshowable -- a name that is not there, a catalog that will not parse, an entry
without a title -- surfaces as `VaultNotFound`, because from the browser's point
of view they are the same thing: there is no vault to show.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from .formats import catalog_format
from .history import is_text
from .vault import CATALOG_FILENAME, MEDIA_DIRNAME


class VaultNotFound(Exception):
    """No vault the viewer can show; the argument says why, for diagnostics."""


@dataclass(frozen=True)
class EntryRow:
    """One entry as a listing shows it."""

    entry_id: str
    title: str
    downloaded: bool
    removed: bool


@dataclass(frozen=True)
class Listing:
    """One category page: where it came from, and the rows it shows."""

    name: str
    version: int
    categories: tuple
    category: str
    rows: tuple


def vault_path(root, name):
    """`name` resolved under `root`, refusing any name that escapes it."""
    path = Path(root, name).resolve()
    if Path(root).resolve() not in path.parents:
        raise VaultNotFound(f"{name!r} is not a vault name")
    return path


def open_vault(root, name):
    """The stored catalog of `name` and its version's reading rules."""
    try:
        data = json.loads((vault_path(root, name) / CATALOG_FILENAME).read_text())
        return data, catalog_format(data)
    except (OSError, ValueError) as error:
        raise VaultNotFound(f"{name!r}: {error}") from error


def category_rows(root, name, data, form, category):
    """The rows of one category, in the order the catalog stores them."""
    filenames = _media_filenames(vault_path(root, name) / MEDIA_DIRNAME)
    return tuple(_row(entry, form, filenames) for entry in _entries(data, category))


def _row(entry, form, filenames):
    """One entry's title, whether its media is here, and whether it is gone."""
    if not isinstance(entry, dict):
        raise VaultNotFound("catalog holds an entry that is not an object")
    entry_id = entry.get("id")
    if not is_text(entry_id):
        raise VaultNotFound("catalog holds an entry without a usable 'id'")

    return EntryRow(
        entry_id=entry_id,
        title=_current(entry, "title", form),
        downloaded=any(entry_id in filename for filename in filenames),
        removed=form.detects_removal and _current(entry, "removed", form) is True,
    )


def _current(entry, field, form):
    """The latest value of one tracked history, by the version's key order."""
    history = entry.get(field)
    if not isinstance(history, dict) or not history:
        raise VaultNotFound(f"entry {entry.get('id')!r} has no {field!r} history")
    try:
        return history[max(history, key=form.key)]
    except ValueError as error:
        raise VaultNotFound(f"entry {entry.get('id')!r} has an unorderable history") from error


def _entries(data, category):
    """One category's stored entries."""
    entries = data.get(category)
    if not isinstance(entries, list):
        raise VaultNotFound(f"catalog field {category!r} is missing or not an array")
    return entries


def _media_filenames(media_path):
    """The names of the files a vault has downloaded, if it has downloaded any."""
    return [path.name for path in media_path.iterdir()] if media_path.is_dir() else []
