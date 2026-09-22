"""Vault directory layout, catalog schema, ordering and backed-up writes."""

import json
from pathlib import Path

from .errors import MvaultError

#: The three content categories a catalog stores, in their canonical order.
CATEGORIES = ("episodes", "streams", "clips")

#: Catalog format this tool reads and writes.
VERSION = 3

CATALOG_FILENAME = "catalog.json"
BACKUP_FILENAME = "catalog.bak"


def new_catalog(source_url):
    """The exact layout a freshly initialized vault starts with."""
    return {"version": VERSION, "source": source_url, "episodes": [], "streams": [], "clips": []}


def sort_entries(entries):
    """Order entries newest `published` first, ties broken by smaller `id`.

    Both keys are compared as text: normalized `published` values are
    fixed-width, so lexicographic order is chronological order. Sorting by the
    tie-breaker first and relying on a stable sort keeps the two directions
    independent.
    """
    by_id = sorted(entries, key=lambda entry: entry["id"])
    return sorted(by_id, key=lambda entry: entry["published"], reverse=True)


def validate_catalog(data):
    """Raise ValueError if `data` is not a catalog this tool can sync.

    Checks the root schema only; entry contents are maintained exclusively by
    this tool and are not re-validated on load.
    """
    if not isinstance(data, dict):
        raise ValueError("catalog is not a JSON object")
    if data.get("version") != VERSION:
        raise ValueError(f"unsupported catalog version {data.get('version')!r}")
    if not isinstance(data.get("source"), str):
        raise ValueError("catalog has no usable source URL")
    for category in CATEGORIES:
        if not isinstance(data.get(category), list):
            raise ValueError(f"catalog field {category!r} is missing or not an array")


class Vault:
    """A vault directory holding `catalog.json` and its `catalog.bak` backup."""

    def __init__(self, name):
        self.name = name
        self.path = Path(name)
        self.catalog_path = self.path / CATALOG_FILENAME
        self.backup_path = self.path / BACKUP_FILENAME

    def create(self, source_url):
        """Create the vault directory with an empty catalog.

        Refuses to touch anything that already exists at the vault path.
        """
        if self.path.exists():
            raise MvaultError(f"vault {self.name!r} already exists")
        self.path.mkdir(parents=True)
        self._write(new_catalog(source_url))

    def load(self):
        """Read and validate `catalog.json`."""
        if not self.catalog_path.is_file():
            raise MvaultError(f"vault {self.name!r} is missing or has no {CATALOG_FILENAME}")
        try:
            catalog = json.loads(self.catalog_path.read_text())
            validate_catalog(catalog)
        except (OSError, ValueError) as error:
            raise MvaultError(f"vault {self.name!r} is not valid: {error}") from error
        return catalog

    def save(self, catalog):
        """Back up the existing catalog, then write the new one over it."""
        if self.catalog_path.is_file():
            self.backup_path.write_bytes(self.catalog_path.read_bytes())
        self._write(catalog)

    def _write(self, catalog):
        self.catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
