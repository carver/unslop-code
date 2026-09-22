"""Reading, validating and persisting `<vault>/catalog.json`."""

import json
import shutil
from operator import itemgetter
from pathlib import Path

from .errors import VaultError
from .history import TRACKED_FIELDS

CATEGORIES = ("episodes", "streams", "clips")
VERSION = 3

STATIC_FIELD_TYPES = {"id": str, "published": str, "width": int, "height": int}

CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"


def catalog_path(name):
    return Path(name) / CATALOG_NAME


def create(name, source_url):
    """Create `<name>/` holding an empty catalog for `source_url`."""
    try:
        Path(name).mkdir(parents=True)
    except FileExistsError:
        raise VaultError(f"vault '{name}' already exists") from None
    write(name, {"version": VERSION, "source": source_url, "episodes": [], "streams": [], "clips": []})


def read(name):
    """Load and validate the catalog of the vault called `name`."""
    try:
        text = catalog_path(name).read_text(encoding="utf-8")
    except OSError:
        raise VaultError(f"vault '{name}' does not exist or has no {CATALOG_NAME}") from None

    try:
        catalog = json.loads(text)
    except json.JSONDecodeError:
        raise VaultError(f"vault '{name}' has an unreadable {CATALOG_NAME}") from None

    if not _is_valid(catalog):
        raise VaultError(f"vault '{name}' has an invalid {CATALOG_NAME}")
    return catalog


def write(name, catalog):
    """Persist `catalog`, backing up any existing file to `catalog.bak` first.

    Entries are ordered newest `published` first, ties broken by smaller `id`.
    """
    for category in CATEGORIES:
        catalog[category] = _ordered(catalog[category])

    path = catalog_path(name)
    if path.exists():
        shutil.copyfile(path, path.with_name(BACKUP_NAME))
    path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")


def _ordered(entries):
    """Newest `published` first; equal publication dates sort by `id`."""
    by_id = sorted(entries, key=itemgetter("id"))
    return sorted(by_id, key=itemgetter("published"), reverse=True)


def _is_valid(catalog):
    return (
        isinstance(catalog, dict)
        and catalog.get("version") == VERSION
        and isinstance(catalog.get("source"), str)
        and all(isinstance(catalog.get(category), list) for category in CATEGORIES)
        and all(_is_valid_entry(entry) for category in CATEGORIES for entry in catalog[category])
    )


def _is_valid_entry(entry):
    """An entry needs its static fields plus six non-empty history objects."""
    return (
        isinstance(entry, dict)
        and all(isinstance(entry.get(field), kind) for field, kind in STATIC_FIELD_TYPES.items())
        and all(isinstance(entry.get(field), dict) and entry[field] for field in TRACKED_FIELDS)
    )
