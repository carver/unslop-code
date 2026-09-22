"""Catalog schema, on-disk layout, ordering and persistence."""

import json
import shutil
from pathlib import Path

from .errors import InvalidVaultError, VaultWriteError

VERSION = 3
CATEGORIES = ("episodes", "streams", "clips")
CATALOG_NAME = "catalog.json"
BACKUP_NAME = "catalog.bak"

#: Fields copied verbatim from the source and never versioned.
STATIC_FIELDS = {"id": str, "published": str, "width": int, "height": int}
#: Fields whose values come from the source and are kept as history objects.
TRACKED_FIELDS = ("title", "description", "views", "likes", "preview")
#: Every history-backed field, including the locally maintained removal flag.
HISTORY_FIELDS = TRACKED_FIELDS + ("removed",)


def catalog_path(name):
    """Path of the catalog file of the vault called ``name``."""
    return Path(name) / CATALOG_NAME


def new_catalog(source_url):
    """Build the catalog of a freshly initialized vault."""
    return {
        "version": VERSION,
        "source": source_url,
        "episodes": [],
        "streams": [],
        "clips": [],
    }


def read_document(name):
    """Read the catalog of the vault called ``name`` as a raw JSON object of any version."""
    path = catalog_path(name)
    if not path.is_file():
        raise InvalidVaultError(f"vault '{name}' does not exist or has no {CATALOG_NAME}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise InvalidVaultError(f"vault '{name}' has an unreadable {CATALOG_NAME}: {error}") from error
    if not isinstance(document, dict):
        raise InvalidVaultError(f"vault '{name}' has a {CATALOG_NAME} that is not an object")
    return document


def save(name, catalog):
    """Write the catalog, first copying any existing one to ``catalog.bak``."""
    path = catalog_path(name)
    if path.exists():
        try:
            shutil.copyfile(path, path.with_name(BACKUP_NAME))
        except OSError as error:
            raise VaultWriteError(
                f"vault '{name}' could not be backed up to {BACKUP_NAME}: {error}"
            ) from error
    path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")


def sort_entries(entries):
    """Order entries by newest ``published`` first, ties broken by smaller ``id``."""
    by_id = sorted(entries, key=lambda entry: entry["id"])
    return sorted(by_id, key=lambda entry: entry["published"], reverse=True)


def validate(catalog, name):
    """Check that a catalog in the native version matches the vault schema."""
    if catalog.get("version") != VERSION:
        raise InvalidVaultError(f"vault '{name}' has an unsupported catalog version")
    if not isinstance(catalog.get("source"), str):
        raise InvalidVaultError(f"vault '{name}' has no source URL")
    for category in CATEGORIES:
        if not isinstance(catalog.get(category), list):
            raise InvalidVaultError(f"vault '{name}' has no '{category}' list")
        for entry in catalog[category]:
            validate_entry(entry, name, category, HISTORY_FIELDS)


def validate_entry(entry, name, category, history_fields):
    """Check that a stored entry carries its static fields and the given history objects."""
    if not isinstance(entry, dict):
        raise InvalidVaultError(f"vault '{name}' has a malformed {category} entry")
    for field, expected in STATIC_FIELDS.items():
        if not isinstance(entry.get(field), expected):
            raise InvalidVaultError(f"vault '{name}' has a {category} entry without a valid '{field}'")
    for field in history_fields:
        if not isinstance(entry.get(field), dict) or not entry[field]:
            raise InvalidVaultError(
                f"vault '{name}' has a {category} entry without a '{field}' history"
            )
    if not isinstance(entry.get("annotations", []), list):
        raise InvalidVaultError(f"vault '{name}' has a {category} entry with invalid 'annotations'")
