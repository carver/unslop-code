"""Vault layout: catalog creation, validation, ordering and persistence."""

import json
import shutil
from datetime import datetime
from pathlib import Path

from .errors import VaultError
from .migration import upgrade
from .schema import CATEGORIES, VERSION

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"


def new_catalog(source_url: str) -> dict:
    """Build the catalog a freshly initialized vault starts from."""
    catalog = {"version": VERSION, "source": source_url}
    catalog.update({category: [] for category in CATEGORIES})
    return catalog


def read_stored(vault_dir: Path) -> dict:
    """Return the catalog JSON of ``vault_dir`` exactly as it is on disk.

    Callers that need current-version data go through :func:`load_catalog`;
    this is for the ones that read an older layout on its own terms.
    """
    path = vault_dir / CATALOG_NAME
    if not path.is_file():
        raise VaultError(f"vault '{vault_dir}' does not exist")
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VaultError(f"vault '{vault_dir}' has an unreadable catalog: {error}") from error
    if not isinstance(stored, dict):
        raise VaultError(f"vault '{vault_dir}' has a catalog that is not a JSON object")
    return stored


def load_catalog(vault_dir: Path) -> tuple[dict, bool]:
    """Read the catalog stored in ``vault_dir`` as current-version data.

    Returns the catalog together with whether it came from an older version and
    so had to be upgraded. The upgrade happens in memory: the stored file is
    left alone until a caller saves the result.
    """
    stored = read_stored(vault_dir)
    catalog = upgrade(stored, datetime.now().replace(microsecond=0))
    _check_shape(vault_dir, catalog)
    return catalog, stored["version"] != VERSION


def save_catalog(vault_dir: Path, catalog: dict) -> None:
    """Order the catalog and write it, backing up any existing file first."""
    path = vault_dir / CATALOG_NAME
    if path.exists():
        _back_up(path, vault_dir / BACKUP_NAME)
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


def _back_up(path: Path, backup_path: Path) -> None:
    """Snapshot the stored catalog, leaving it untouched if the copy fails."""
    try:
        shutil.copyfile(path, backup_path)
    except OSError as error:
        raise VaultError(f"could not write '{backup_path}': {error}") from error


def _check_shape(vault_dir: Path, catalog: dict) -> None:
    """Reject catalogs mvault cannot safely update."""
    if not isinstance(catalog.get("source"), str):
        raise VaultError(f"vault '{vault_dir}' has a catalog without a source URL")
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise VaultError(f"vault '{vault_dir}' has a catalog without a '{category}' array")
