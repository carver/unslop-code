"""The ``init`` and ``sync`` operations on a vault directory."""

from datetime import datetime
from pathlib import Path
from typing import Any

import catalogs
import history
import source
from errors import MvaultError
from timestamps import format_timestamp, next_second, normalize_published


def init_vault(name: str, url: str) -> str:
    """Create vault ``name`` holding an empty catalog pointed at ``url``."""
    vault = Path(name)
    if vault.exists():
        raise MvaultError(f"Vault '{name}' already exists")
    vault.mkdir(parents=True)
    catalogs.save(vault, catalogs.empty_catalog(url))
    return f"Initialized vault '{name}' from {url}"


def sync_vault(name: str) -> str:
    """Record the current state of the vault source in the vault catalog."""
    vault = Path(name)
    catalog = catalogs.load(vault, name)
    data = source.fetch(catalog["source"])
    timestamp = sync_timestamp(catalog, datetime.now())
    for category in catalogs.CATEGORIES:
        catalog[category] = merge_category(catalog[category], data[category], timestamp)
    catalogs.save(vault, catalog)
    return f"Synced vault '{name}' at {timestamp}"


def sync_timestamp(catalog: catalogs.Catalog, moment: datetime) -> str:
    """Timestamp for this sync: execution time, kept newer than every record.

    Syncs repeated within one second still produce strictly increasing
    timestamps, so appended history keys never collide or go backwards.
    """
    timestamp = format_timestamp(moment)
    newest = catalogs.latest_timestamp(catalog)
    if timestamp <= newest:
        return next_second(newest)
    return timestamp


def merge_category(
    entries: list[catalogs.Entry], items: list[dict[str, Any]], timestamp: str
) -> list[catalogs.Entry]:
    """Fold the source entries of one category into the stored ones."""
    stored = {entry["id"]: entry for entry in entries}
    for item in items:
        entry = stored.get(item["id"])
        if entry is None:
            entries.append(new_entry(item, timestamp))
        else:
            observe(entry, item, timestamp)
    listed = {item["id"] for item in items}
    for entry in entries:
        if entry["id"] not in listed:
            history.record(entry["removed"], timestamp, True)
    return catalogs.sort_entries(entries)


def new_entry(item: dict[str, Any], timestamp: str) -> catalogs.Entry:
    """Build the stored entry for an identifier seen for the first time."""
    entry = {field: item[field] for field in catalogs.STATIC_FIELDS}
    entry["published"] = normalize_published(item["published"])
    entry.update(
        {
            field: history.start(timestamp, item[field])
            for field in catalogs.SOURCE_TRACKED_FIELDS
        }
    )
    entry["removed"] = history.start(timestamp, False)
    return entry


def observe(entry: catalogs.Entry, item: dict[str, Any], timestamp: str) -> None:
    """Extend the histories of a stored entry with its current source values.

    Fields still holding their previous value gain no record, and an entry that
    had been marked removed is restored by the same rule.
    """
    for field in catalogs.SOURCE_TRACKED_FIELDS:
        history.record(entry[field], timestamp, item[field])
    history.record(entry["removed"], timestamp, False)
