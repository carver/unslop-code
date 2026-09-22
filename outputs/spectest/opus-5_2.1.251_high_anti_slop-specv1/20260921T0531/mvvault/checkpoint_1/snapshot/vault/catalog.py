"""Creating, reading, ordering and writing a vault's ``catalog.json``."""

import json
import shutil
from operator import itemgetter
from pathlib import Path

from .source import CATEGORIES

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"
VERSION = 3


class VaultError(Exception):
    """Raised when a vault directory is missing, occupied, or unusable."""


def create(name, url):
    """Create the vault directory ``name`` holding an empty catalog for ``url``."""
    directory = Path(name)
    if directory.exists():
        raise VaultError(f"vault {name} already exists")
    directory.mkdir(parents=True)
    empty = {"version": VERSION, "source": url}
    empty.update({category: [] for category in CATEGORIES})
    save(name, empty)


def load(name):
    """Read and validate the catalog of the vault ``name``."""
    path = Path(name) / CATALOG_NAME
    if not path.is_file():
        raise VaultError(f"vault {name} does not exist")
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise VaultError(f"vault {name} has an unreadable catalog: {error}") from error
    _check_shape(name, catalog)
    return catalog


def _check_shape(name, catalog):
    """Reject catalogs that do not match the documented root schema."""
    if not isinstance(catalog, dict) or catalog.get("version") != VERSION:
        raise VaultError(f"vault {name} has an invalid catalog version")
    if not isinstance(catalog.get("source"), str):
        raise VaultError(f"vault {name} has no source URL")
    missing = [category for category in CATEGORIES if not isinstance(catalog.get(category), list)]
    if missing:
        raise VaultError(f"vault {name} is missing the {', '.join(missing)} array(s)")


def save(name, catalog):
    """Write ``catalog``, backing up any existing catalog to ``catalog.bak`` first."""
    path = Path(name) / CATALOG_NAME
    if path.exists():
        shutil.copyfile(path, path.with_name(BACKUP_NAME))
    path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sort_entries(entries):
    """Order entries newest ``published`` first, ties by smaller ``id`` first."""
    by_id = sorted(entries, key=itemgetter("id"))
    return sorted(by_id, key=itemgetter("published"), reverse=True)
