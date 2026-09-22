"""Vault layout: creating, validating, loading and persisting `catalog.json`."""

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from mvaultlib.entries import CATEGORIES, validate_entry
from mvaultlib.errors import MvaultError
from mvaultlib.timestamps import format_timestamp
from mvaultlib.versions import NATIVE_VERSION, upgrade_catalog

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"


@dataclass
class Vault:
    """A loaded vault: its directory, its v3 catalog and the version on disk."""

    path: Path
    catalog: dict
    stored_version: int


def init_vault(name, url):
    """Create `<name>/` holding a catalog with the required empty layout."""
    vault_path = Path(name)
    if vault_path.exists():
        raise MvaultError(f"cannot create vault '{name}': path already exists")
    vault_path.mkdir(parents=True)
    catalog = {"version": NATIVE_VERSION, "source": url}
    catalog.update({category: [] for category in CATEGORIES})
    write_catalog(vault_path, catalog)


def load_vault(name, now=None):
    """Load a vault of any supported version as a v3 catalog held in memory.

    Legacy catalogs are upgraded here rather than on disk, so a command that
    only reads a vault leaves its `catalog.json` exactly as it found it.
    """
    vault_path = Path(name)
    stored = read_raw_catalog(name)
    migration_timestamp = format_timestamp(now or datetime.now())
    version, catalog = upgrade_catalog(name, stored, migration_timestamp)
    _validate_catalog(name, catalog)
    return Vault(vault_path, catalog, version)


def write_catalog(vault_path, catalog):
    """Write the catalog, backing up any catalog it replaces."""
    catalog_path = vault_path / CATALOG_NAME
    if catalog_path.exists():
        _back_up(catalog_path, vault_path / BACKUP_NAME)
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")


def _back_up(catalog_path, backup_path):
    """Copy the catalog aside; a backup that cannot be written stops the write."""
    try:
        shutil.copyfile(catalog_path, backup_path)
    except OSError as error:
        raise MvaultError(f"could not write {BACKUP_NAME}: {error}") from error


def read_raw_catalog(name):
    """Parse `<name>/catalog.json` without interpreting or upgrading its contents."""
    catalog_path = Path(name) / CATALOG_NAME
    if not catalog_path.is_file():
        raise MvaultError(f"vault '{name}' does not exist or has no {CATALOG_NAME}")
    try:
        return json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MvaultError(f"vault '{name}' has an unreadable {CATALOG_NAME}: {error}") from error


def _validate_catalog(name, catalog):
    """Raise unless the loaded catalog matches the native root schema."""
    if not isinstance(catalog.get("source"), str):
        raise MvaultError(f"vault '{name}' has an invalid catalog: 'source' must be a string")
    for category in CATEGORIES:
        entries = catalog.get(category)
        if not isinstance(entries, list):
            raise MvaultError(f"vault '{name}' has an invalid catalog: '{category}' must be an array")
        for entry in entries:
            validate_entry(entry, f"vault '{name}' invalid catalog: {category}")
