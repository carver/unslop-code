"""Reading a stored catalog in the version it was written in.

``digest`` summarizes a vault without migrating it, so it needs the stored
layout rather than the current one. A :class:`CatalogView` states the three
things that layout decides: how entries are grouped, which tracked fields are
present, and how history keys order.
"""

from dataclasses import dataclass
from pathlib import Path

from .catalog import read_stored
from .errors import VaultError
from .migration import LEGACY_SOURCE_PREFIX
from .schema import CATEGORIES, TRACKED_FIELDS, VERSION

V1_GROUP = "Entries"
REMOVED_FIELD = "removed"

_LEGACY_FIELDS = tuple(TRACKED_FIELDS)
_CURRENT_FIELDS = _LEGACY_FIELDS + (REMOVED_FIELD,)


@dataclass(frozen=True)
class CatalogView:
    """One stored catalog, described in the terms of its own version."""

    version: int
    source: str
    groups: tuple[tuple[str, list], ...]
    tracked_fields: tuple[str, ...]
    epoch_keys: bool

    @property
    def removals_tracked(self) -> bool:
        """Whether entries carry the ``removed`` history that marks a removal."""
        return REMOVED_FIELD in self.tracked_fields

    def ordered_values(self, history: dict) -> list:
        """Values of a history, oldest key first.

        Version 1 keys are UNIX epoch seconds, which only order correctly as
        numbers; later versions use ISO 8601 text, which orders as text.
        """
        return [history[key] for key in sorted(history, key=self._key_order)]

    def _key_order(self, key: str):
        return int(key) if self.epoch_keys else key


def read_view(vault_dir: Path) -> CatalogView:
    """Describe the catalog stored in ``vault_dir`` without changing anything."""
    stored = read_stored(vault_dir)
    version = stored.get("version")
    if version not in _READERS:
        raise VaultError(
            f"vault '{vault_dir}' has catalog version {version!r}, "
            f"which cannot be read; {VERSION} is the newest supported"
        )
    view = _READERS[version](stored, vault_dir)
    _check_entries(view, vault_dir)
    return view


def _view_1(stored: dict, vault_dir: Path) -> CatalogView:
    """A version 1 catalog: a derived source URL and one flat entry list."""
    source_id = stored.get("source_id")
    if not isinstance(source_id, str):
        raise VaultError(f"vault '{vault_dir}' has a version 1 catalog without a 'source_id'")
    groups = ((V1_GROUP, _entry_list(stored, "entries", vault_dir)),)
    return CatalogView(1, LEGACY_SOURCE_PREFIX + source_id, groups, _LEGACY_FIELDS, True)


def _view_2(stored: dict, vault_dir: Path) -> CatalogView:
    """A version 2 catalog: categories and ISO 8601 keys, but no ``removed``."""
    return _categorized_view(stored, vault_dir, 2, _LEGACY_FIELDS)


def _view_3(stored: dict, vault_dir: Path) -> CatalogView:
    """A version 3 catalog, the layout mvault writes."""
    return _categorized_view(stored, vault_dir, VERSION, _CURRENT_FIELDS)


_READERS = {1: _view_1, 2: _view_2, VERSION: _view_3}


def _categorized_view(stored: dict, vault_dir: Path, version: int, fields: tuple) -> CatalogView:
    """Describe a catalog that already stores a source URL and the categories."""
    source = stored.get("source")
    if not isinstance(source, str):
        raise VaultError(f"vault '{vault_dir}' has a catalog without a source URL")
    groups = tuple(
        (category.capitalize(), _entry_list(stored, category, vault_dir))
        for category in CATEGORIES
    )
    return CatalogView(version, source, groups, fields, False)


def _entry_list(stored: dict, key: str, vault_dir: Path) -> list:
    entries = stored.get(key)
    if not isinstance(entries, list):
        raise VaultError(f"vault '{vault_dir}' has a catalog without a '{key}' array")
    return entries


def _check_entries(view: CatalogView, vault_dir: Path) -> None:
    """Reject entries a summary could not name, before any of them is read."""
    for label, entries in view.groups:
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("title"), dict):
                raise VaultError(
                    f"vault '{vault_dir}' has an item in '{label}' without a 'title' history"
                )
            if not entry["title"]:
                raise VaultError(
                    f"vault '{vault_dir}' has an item in '{label}' with an empty 'title' history"
                )
