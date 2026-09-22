"""Reading a stored catalog in the version it was written in.

``digest`` summarizes a vault without migrating it, and the viewer browses
one without migrating it either, so both need the stored layout rather than the
current one. A :class:`CatalogView` states the three things that layout
decides: which categories entries are grouped into, which tracked fields are
present, and how history keys order.
"""

from dataclasses import dataclass
from pathlib import Path

from .catalog import read_stored
from .errors import VaultError
from .migration import LEGACY_SOURCE_PREFIX
from .schema import CATEGORIES, REMOVED_FIELD, TRACKED_FIELDS, VERSION
from .timestamps import format_epoch

V1_CATEGORY = "entries"
ENTRY_SEGMENT = "entry"

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
    def categories(self) -> tuple[str, ...]:
        """The category names this version stores, in their catalog order."""
        return tuple(category for category, _ in self.groups)

    @property
    def default_category(self) -> str:
        """The category a viewer shows when none was asked for."""
        return self.categories[0]

    def entries_in(self, category: str) -> list | None:
        """Entries of one category, or ``None`` when this version has no such category."""
        return dict(self.groups).get(category)

    @property
    def removals_tracked(self) -> bool:
        """Whether entries carry the ``removed`` history that marks a removal."""
        return REMOVED_FIELD in self.tracked_fields

    def entry_url(self, entry_id: str) -> str:
        """Where one entry lives on the source platform.

        Every version resolves to ``<source>/entry/<id>``; a version 1
        catalog gets there through the source URL derived from its
        ``source_id``.
        """
        return f"{self.source}/{ENTRY_SEGMENT}/{entry_id}"

    def is_removed(self, entry: dict) -> bool:
        """Whether the source has dropped an entry, which only version 3 records."""
        return self.removals_tracked and self.current_value(entry.get(REMOVED_FIELD, {})) is True

    def current_value(self, history: dict, default=None):
        """The value under the latest key of a history, or ``default`` when it has none."""
        keys = self._ordered_keys(history)
        return history[keys[-1]] if keys else default

    def ordered_values(self, history: dict) -> list:
        """Values of a history, oldest key first."""
        return [history[key] for key in self._ordered_keys(history)]

    def ordered_points(self, history: dict) -> list[tuple[str, object]]:
        """A history as ``(timestamp, value)`` pairs, oldest first.

        The timestamps read the same whatever version stored them: version 1
        keys are UNIX epoch seconds, which are rendered as the moment in UTC
        they name, and later versions already carry ISO 8601 text.
        """
        return [(self._key_text(key), history[key]) for key in self._ordered_keys(history)]

    def _ordered_keys(self, history: dict) -> list[str]:
        """History keys, chronologically.

        Version 1 keys are UNIX epoch seconds, which only order correctly as
        numbers; later versions use ISO 8601 text, which orders as text.
        """
        return sorted(history, key=self._key_order)

    def _key_order(self, key: str):
        return int(key) if self.epoch_keys else key

    def _key_text(self, key: str) -> str:
        return format_epoch(key) if self.epoch_keys else key


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
    groups = ((V1_CATEGORY, _entry_list(stored, V1_CATEGORY, vault_dir)),)
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
        (category, _entry_list(stored, category, vault_dir)) for category in CATEGORIES
    )
    return CatalogView(version, source, groups, fields, False)


def _entry_list(stored: dict, key: str, vault_dir: Path) -> list:
    entries = stored.get(key)
    if not isinstance(entries, list):
        raise VaultError(f"vault '{vault_dir}' has a catalog without a '{key}' array")
    return entries


def _check_entries(view: CatalogView, vault_dir: Path) -> None:
    """Reject entries a summary could neither name nor link to, before any is read."""
    for category, entries in view.groups:
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                raise VaultError(
                    f"vault '{vault_dir}' has an item in '{category}' without an 'id'"
                )
            if not isinstance(entry.get("title"), dict):
                raise VaultError(
                    f"vault '{vault_dir}' has an item in '{category}' without a 'title' history"
                )
            if not entry["title"]:
                raise VaultError(
                    f"vault '{vault_dir}' has an item in '{category}' with an empty 'title' history"
                )
