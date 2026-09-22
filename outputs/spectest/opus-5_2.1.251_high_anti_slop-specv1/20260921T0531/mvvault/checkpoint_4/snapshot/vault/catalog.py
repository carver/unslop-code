"""Creating, reading, ordering and writing a vault's ``catalog.json``."""

import json
import shutil
from collections import namedtuple
from operator import itemgetter
from pathlib import Path

from . import versions
from .errors import VaultError
from .source import CATEGORIES

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"

LoadedCatalog = namedtuple("LoadedCatalog", "catalog upgraded")


def create(name, url):
    """Create the vault directory ``name`` holding an empty catalog for ``url``."""
    directory = Path(name)
    if directory.exists():
        raise VaultError(f"vault {name} already exists")
    directory.mkdir(parents=True)
    empty = {"version": versions.VERSION, "source": url}
    empty.update({category: [] for category in CATEGORIES})
    save(name, empty)


def read(name):
    """Return the catalog of the vault ``name`` exactly as it is stored.

    The result keeps its own schema version; commands that work on legacy
    layouts directly start here instead of at :func:`load`.
    """
    path = Path(name) / CATALOG_NAME
    if not path.is_file():
        raise VaultError(f"vault {name} does not exist")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise VaultError(f"vault {name} has an unreadable catalog: {error}") from error


def load(name):
    """Read the catalog of the vault ``name`` as a :class:`LoadedCatalog`.

    ``catalog`` is always in the native version; ``upgraded`` says whether it
    is the in-memory upgrade of a legacy one, and so differs from what is on
    disk. Loading never writes: a read-only command leaves the vault as it
    found it.
    """
    stored = read(name)
    if versions.detect(name, stored) != versions.VERSION:
        return LoadedCatalog(versions.upgrade(name, stored), True)
    _check_shape(name, stored)
    return LoadedCatalog(stored, False)


def _check_shape(name, catalog):
    """Reject native catalogs that do not match the documented root schema."""
    if not isinstance(catalog.get("source"), str):
        raise VaultError(f"vault {name} has no source URL")
    missing = [category for category in CATEGORIES if not isinstance(catalog.get(category), list)]
    if missing:
        raise VaultError(f"vault {name} is missing the {', '.join(missing)} array(s)")


def save(name, catalog):
    """Write ``catalog``, backing up any existing catalog to ``catalog.bak`` first.

    A backup that cannot be written aborts the save, leaving the stored catalog
    as it was.
    """
    path = Path(name) / CATALOG_NAME
    if path.exists():
        try:
            shutil.copyfile(path, path.with_name(BACKUP_NAME))
        except OSError as error:
            raise VaultError(f"vault {name} could not be backed up: {error}") from error
    path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sort_entries(entries):
    """Order entries newest ``published`` first, ties by smaller ``id`` first."""
    by_id = sorted(entries, key=itemgetter("id"))
    return sorted(by_id, key=itemgetter("published"), reverse=True)
