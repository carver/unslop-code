"""Reading, validating and persisting `<vault>/catalog.json`."""

import json
import shutil
from operator import itemgetter
from pathlib import Path

from . import versions
from .errors import VaultError
from .schema import CATEGORIES, VERSION

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


def load(name):
    """Read the catalog of `name` as a native catalog, whatever its version.

    Returns the catalog together with a flag saying whether it had to be
    upgraded from an older layout. The file on disk is left as it is, so a
    read-only command never rewrites a legacy catalog.
    """
    return versions.to_native(read_raw(name), name)


def migrate(name):
    """Upgrade the vault's catalog on disk; return whether it was rewritten."""
    catalog, upgraded = load(name)
    if upgraded:
        write(name, catalog)
    return upgraded


def write(name, catalog):
    """Persist `catalog`, backing up any existing file to `catalog.bak` first.

    Entries are ordered newest `published` first, ties broken by smaller `id`.
    """
    for category in CATEGORIES:
        catalog[category] = _ordered(catalog[category])

    path = catalog_path(name)
    if path.exists():
        _back_up(name, path)
    path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")


def read_raw(name):
    """The catalog of `name` as plain JSON data, at whatever version it declares."""
    try:
        text = catalog_path(name).read_text(encoding="utf-8")
    except OSError:
        raise VaultError(f"vault '{name}' does not exist or has no {CATALOG_NAME}") from None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise VaultError(f"vault '{name}' has an unreadable {CATALOG_NAME}") from None


def _back_up(name, path):
    """Copy the pre-write catalog aside; a failure here cancels the write."""
    try:
        shutil.copyfile(path, path.with_name(BACKUP_NAME))
    except OSError:
        raise VaultError(f"vault '{name}' could not be backed up to {BACKUP_NAME}") from None


def _ordered(entries):
    """Newest `published` first; equal publication dates sort by `id`."""
    by_id = sorted(entries, key=itemgetter("id"))
    return sorted(by_id, key=itemgetter("published"), reverse=True)
