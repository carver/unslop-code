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


def load(vault: Path, name: str) -> Catalog:
    """Read and structurally validate the catalog of the vault called ``name``."""
    try:
        catalog = json.loads(catalog_path(vault).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise MvaultError(f"Vault '{name}' does not exist or has no {CATALOG_FILENAME}") from None
    except json.JSONDecodeError as error:
        raise MvaultError(f"Vault '{name}' has an unreadable catalog: {error}") from error
    well_formed = (
        isinstance(catalog, dict)
        and catalog.get("version") == CATALOG_VERSION
        and isinstance(catalog.get("source"), str)
        and all(isinstance(catalog.get(category), list) for category in CATEGORIES)
    )
    if not well_formed:
        raise MvaultError(f"Vault '{name}' has an invalid catalog")
    return catalog


def save(vault: Path, catalog: Catalog) -> None:
    """Write ``catalog``, backing up any catalog already on disk first."""
    path = catalog_path(vault)
    if path.exists():
        shutil.copyfile(path, vault / BACKUP_FILENAME)
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
