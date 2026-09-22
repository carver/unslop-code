"""Vault layout: creating, validating, loading and persisting `catalog.json`."""

import json
import shutil
from pathlib import Path

from mvaultlib.entries import validate_entry
from mvaultlib.errors import MvaultError

CATALOG_VERSION = 3
CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"
CATEGORIES = ("episodes", "streams", "clips")


def init_vault(name, url):
    """Create `<name>/` holding a catalog with the required empty layout."""
    vault_path = Path(name)
    if vault_path.exists():
        raise MvaultError(f"cannot create vault '{name}': path already exists")
    vault_path.mkdir(parents=True)
    catalog = {"version": CATALOG_VERSION, "source": url}
    catalog.update({category: [] for category in CATEGORIES})
    write_catalog(vault_path, catalog)


def load_catalog(name):
    """Return the vault path and its catalog, rejecting anything unusable."""
    vault_path = Path(name)
    catalog_path = vault_path / CATALOG_NAME
    if not catalog_path.is_file():
        raise MvaultError(f"vault '{name}' does not exist or has no {CATALOG_NAME}")
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MvaultError(f"vault '{name}' has an unreadable {CATALOG_NAME}: {error}") from error
    _validate_catalog(name, catalog)
    return vault_path, catalog


def write_catalog(vault_path, catalog):
    """Write the catalog, backing up any catalog it replaces."""
    catalog_path = vault_path / CATALOG_NAME
    if catalog_path.exists():
        shutil.copyfile(catalog_path, vault_path / BACKUP_NAME)
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")


def _validate_catalog(name, catalog):
    """Raise unless the catalog matches the documented root schema."""
    if not isinstance(catalog, dict):
        raise MvaultError(f"vault '{name}' has an invalid catalog: root is not an object")
    if catalog.get("version") != CATALOG_VERSION:
        raise MvaultError(f"vault '{name}' has an invalid catalog: version must be {CATALOG_VERSION}")
    if not isinstance(catalog.get("source"), str):
        raise MvaultError(f"vault '{name}' has an invalid catalog: 'source' must be a string")
    for category in CATEGORIES:
        entries = catalog.get(category)
        if not isinstance(entries, list):
            raise MvaultError(f"vault '{name}' has an invalid catalog: '{category}' must be an array")
        for entry in entries:
            validate_entry(entry, f"vault '{name}' invalid catalog: {category}")
