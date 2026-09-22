"""The ``init``, ``sync`` and ``migrate`` operations on a vault directory."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import catalogs
import downloads
import merging
import migrations
import source
import viewer
from errors import MvaultError
from timestamps import format_timestamp, next_second


@dataclass(frozen=True)
class SyncOptions:
    """What one ``sync`` run should do, as asked for on the command line."""

    limits: downloads.Limits = field(default_factory=dict)
    media_format: Optional[str] = None
    skip_metadata: bool = False
    skip_download: bool = False


def init_vault(name: str, url: str) -> str:
    """Create vault ``name`` holding an empty catalog pointed at ``url``."""
    vault = Path(name)
    if vault.exists():
        raise MvaultError(f"Vault '{name}' already exists")
    vault.mkdir(parents=True)
    catalogs.save(vault, catalogs.empty_catalog(url))
    return f"Initialized vault '{name}' from {url}"


def sync_vault(name: str, options: SyncOptions = SyncOptions()) -> str:
    """Bring vault ``name`` up to date with its source, metadata then media.

    The metadata phase is persisted before any file is downloaded, so media
    that turns out to be unreachable never costs the vault what it learned.
    A legacy catalog is upgraded on the way in and written back in the native
    version, so the backup keeps the vault exactly as it was before the sync.
    """
    vault = Path(name)
    catalog = migrations.upgrade(catalogs.read(vault, name), name)
    report = []
    if not options.skip_metadata:
        report.append(record_source_state(vault, catalog, name))
    if not options.skip_download:
        report.append(
            downloads.download_entries(vault, catalog, options.limits, options.media_format)
        )
    return "\n".join(report) or f"Nothing to do for vault '{name}'"


def record_source_state(vault: Path, catalog: catalogs.Catalog, name: str) -> str:
    """Fetch the source, fold it into ``catalog`` and save the result.

    The summary counts what the merge did and then names every entry it
    touched, each beside the viewer address it can be read at.
    """
    data = source.fetch(catalog["source"])
    timestamp = sync_timestamp(catalog, datetime.now())
    summary = merging.merge(catalog, data, timestamp)
    catalogs.save(vault, catalog)
    lines = [f"Synced vault '{name}' at {timestamp}", f"Recorded {summary}"]
    lines.extend(_change_line(name, change) for change in summary.changes)
    return "\n".join(lines)


def _change_line(name: str, change: merging.EntryChange) -> str:
    """Report one entry a sync touched, under the vault it was synced in."""
    url = viewer.entry_url(name, change.category, change.identifier)
    return f"  {change.kind}: {change.title} {url}"


def migrate_vault(name: str) -> str:
    """Rewrite the catalog of vault ``name`` in the native version."""
    vault = Path(name)
    stored = catalogs.read(vault, name)
    catalog = migrations.upgrade(stored, name)
    if migrations.is_native(stored):
        return f"Vault '{name}' already uses catalog version {catalogs.CATALOG_VERSION}"
    catalogs.save(vault, catalog)
    return f"Migrated vault '{name}' to catalog version {catalogs.CATALOG_VERSION}"


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
