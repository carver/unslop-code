"""Vault layout: catalog creation, validation, ordering and persistence."""

import json
import shutil
from pathlib import Path

CATEGORIES = ("episodes", "streams", "clips")
VERSION = 3
CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"


class VaultError(Exception):
    """Raised when a vault directory is missing, occupied or not usable."""


def new_catalog(source_url: str) -> dict:
    """Build the catalog a freshly initialized vault starts from."""
    catalog = {"version": VERSION, "source": source_url}
    catalog.update({category: [] for category in CATEGORIES})
    return catalog


def load_catalog(vault_dir: Path) -> dict:
    """Read and validate the catalog stored in ``vault_dir``."""
    path = vault_dir / CATALOG_NAME
    if not path.is_file():
        raise VaultError(f"vault '{vault_dir}' does not exist")
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VaultError(f"vault '{vault_dir}' has an unreadable catalog: {error}") from error
    _check_shape(vault_dir, catalog)
    return catalog


def save_catalog(vault_dir: Path, catalog: dict) -> None:
    """Order the catalog and write it, backing up any existing file first."""
    path = vault_dir / CATALOG_NAME
    if path.exists():
        shutil.copyfile(path, vault_dir / BACKUP_NAME)
    for category in CATEGORIES:
        sort_entries(catalog[category])
    path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")


def sort_entries(entries: list) -> None:
    """Order entries newest ``published`` first, ties by smaller ``id``.

    Publication text is normalized on the way in, so it sorts chronologically
    as plain text. The two stable passes give ``id`` the lower priority.
    """
    entries.sort(key=lambda entry: entry["id"])
    entries.sort(key=lambda entry: entry["published"], reverse=True)


def _check_shape(vault_dir: Path, catalog) -> None:
    """Reject catalogs mvault cannot safely update."""
    if not isinstance(catalog, dict):
        raise VaultError(f"vault '{vault_dir}' has a catalog that is not a JSON object")
    if catalog.get("version") != VERSION:
        raise VaultError(f"vault '{vault_dir}' has an unsupported catalog version")
    if not isinstance(catalog.get("source"), str):
        raise VaultError(f"vault '{vault_dir}' has a catalog without a source URL")
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise VaultError(f"vault '{vault_dir}' has a catalog without a '{category}' array")
