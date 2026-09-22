"""Reading, validating, ordering and persisting `catalog.json`."""

import json
import shutil
from pathlib import Path

from .errors import VaultError
from .source import CATEGORIES

VERSION = 3
CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"


def catalog_path(vault):
    return Path(vault) / CATALOG_NAME


def empty_catalog(url):
    """The catalog layout a freshly initialised vault starts with."""
    return {"version": VERSION, "source": url, "episodes": [], "streams": [], "clips": []}


def load_catalog(name):
    """Read and validate the catalog of the vault directory `name`."""
    path = catalog_path(name)
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise VaultError(f"vault '{name}' is missing or unreadable: {exc}") from exc
    except ValueError as exc:
        raise VaultError(f"vault '{name}' has an unreadable catalog: {exc}") from exc

    validate_catalog(catalog, name)
    return catalog


def validate_catalog(catalog, name):
    """Check the catalog against the root schema."""
    if not isinstance(catalog, dict):
        raise VaultError(f"vault '{name}' has a catalog that is not a JSON object")
    if catalog.get("version") != VERSION:
        raise VaultError(f"vault '{name}' has a catalog that is not version {VERSION}")
    if not isinstance(catalog.get("source"), str):
        raise VaultError(f"vault '{name}' has a catalog without a source URL")
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise VaultError(f"vault '{name}' has a catalog without a '{category}' array")


def save_catalog(name, catalog):
    """Write the catalog, backing up any existing one byte-for-byte first."""
    path = catalog_path(name)
    if path.exists():
        shutil.copyfile(path, Path(name) / BACKUP_NAME)
    path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")


def sort_entries(entries):
    """Order entries newest `published` first, ties by smaller `id`.

    Sorting by `id` first and then stably by `published` yields the documented
    two-key order; `published` is stored in a fixed-width text format, so text
    order matches chronological order.
    """
    entries.sort(key=lambda entry: entry["id"])
    entries.sort(key=lambda entry: entry["published"], reverse=True)
