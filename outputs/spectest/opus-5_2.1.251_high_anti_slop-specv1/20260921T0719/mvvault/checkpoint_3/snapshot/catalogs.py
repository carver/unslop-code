"""Reading, ordering and persisting ``catalog.json``."""

import json
import shutil
from pathlib import Path
from typing import Any

from errors import MvaultError

CATALOG_VERSION = 3
CATALOG_FILENAME = "catalog.json"
BACKUP_FILENAME = "catalog.bak"

#: Content categories, in the order they appear in a catalog.
CATEGORIES = ("episodes", "streams", "clips")

#: Entry fields copied once from the source and never given a history.
STATIC_FIELDS = ("id", "published", "width", "height")

#: Entry fields whose values come from the source and are tracked over time.
SOURCE_TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")

#: Every tracked field, including the locally maintained removal flag.
TRACKED_FIELDS = SOURCE_TRACKED_FIELDS + ("removed",)

#: Accepted Python types for the value of each field an entry carries.
FIELD_TYPES: dict[str, tuple[type, ...]] = {
    "id": (str,),
    "published": (str,),
    "width": (int,),
    "height": (int,),
    "title": (str,),
    "description": (str,),
    "views": (int,),
    "likes": (int, type(None)),
    "preview": (str,),
}

Catalog = dict[str, Any]
Entry = dict[str, Any]


def catalog_path(vault: Path) -> Path:
    """Path of the catalog inside ``vault``."""
    return vault / CATALOG_FILENAME


def empty_catalog(source: str) -> Catalog:
    """Build the catalog a freshly initialized vault starts with."""
    catalog: Catalog = {"version": CATALOG_VERSION, "source": source}
    catalog.update({category: [] for category in CATEGORIES})
    return catalog


def read(vault: Path, name: str) -> Any:
    """Parse the catalog of the vault called ``name`` as stored on disk.

    The result keeps whatever version the file declares; :mod:`migrations`
    turns it into a catalog the rest of mvault can work with.
    """
    try:
        return json.loads(catalog_path(vault).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise MvaultError(f"Vault '{name}' does not exist or has no {CATALOG_FILENAME}") from None
    except json.JSONDecodeError as error:
        raise MvaultError(f"Vault '{name}' has an unreadable catalog: {error}") from error


def save(vault: Path, catalog: Catalog) -> None:
    """Write ``catalog``, backing up any catalog already on disk first.

    A backup that cannot be written aborts the write, so the catalog on disk is
    never replaced without a copy of what it held.
    """
    path = catalog_path(vault)
    if path.exists():
        try:
            shutil.copyfile(path, vault / BACKUP_FILENAME)
        except OSError as error:
            raise MvaultError(f"Cannot back up the catalog of '{vault}': {error}") from error
    path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sort_entries(entries: list[Entry]) -> list[Entry]:
    """Order entries by newest publication first, ties broken by smaller id."""
    by_id = sorted(entries, key=lambda entry: entry["id"])
    return sorted(by_id, key=lambda entry: entry["published"], reverse=True)


def latest_timestamp(catalog: Catalog) -> str:
    """Return the newest timestamp recorded anywhere in ``catalog``, or ``""``."""
    return max(
        (
            key
            for category in CATEGORIES
            for entry in catalog[category]
            for field in TRACKED_FIELDS
            for key in entry.get(field, {})
        ),
        default="",
    )
