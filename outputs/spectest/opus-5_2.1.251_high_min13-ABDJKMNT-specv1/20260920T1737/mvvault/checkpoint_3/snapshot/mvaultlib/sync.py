"""The `sync` command: a metadata phase followed by a download phase.

The metadata phase merges the source document into the catalog and persists it.
The download phase then fetches missing media and previews. Either phase can be
skipped, and a download failure never costs the metadata the first phase saved.
"""

import sys
from dataclasses import dataclass, field
from datetime import datetime

from mvaultlib.catalog import load_vault, write_catalog
from mvaultlib.downloads import download_assets
from mvaultlib.entries import (
    CATEGORIES,
    TRACKED_FIELDS,
    create_entry,
    record_absence,
    record_observation,
    sort_entries,
)
from mvaultlib.source import fetch_source
from mvaultlib.timestamps import format_timestamp, next_timestamp, parse_timestamp


@dataclass
class SyncOptions:
    """The command line choices that shape one `sync` run."""

    #: Per-category cap on media downloads; a missing or None value means no cap.
    limits: dict = field(default_factory=dict)
    format_override: str = None
    skip_metadata: bool = False
    skip_download: bool = False

    @classmethod
    def from_args(cls, args):
        """Read the parsed `sync` arguments into options."""
        return cls(
            limits={category: getattr(args, category) for category in CATEGORIES},
            format_override=args.format_override,
            skip_metadata=args.skip_metadata,
            skip_download=args.skip_download,
        )


@dataclass
class ChangeCounts:
    """What one metadata phase did, as reported by the post-sync summary."""

    added: int = 0
    removed: int = 0
    updated: int = 0

    def __str__(self):
        return f"Added {self.added}, removed {self.removed}, updated {self.updated}."


def sync_vault(name, options=None, now=None, out=sys.stdout, warn=None):
    """Run the metadata phase, then the download phase, then report the changes."""
    options = options or SyncOptions()
    vault = load_vault(name, now)
    counts = None
    if not options.skip_metadata:
        counts = update_metadata(vault, now)
    if not options.skip_download:
        download_assets(vault.path, vault.catalog, options, warn or _warn)
    if counts is not None:
        print(counts, file=out)


def update_metadata(vault, now):
    """Merge the source into the catalog, persist it and return the change counts."""
    catalog = vault.catalog
    source_categories = fetch_source(catalog["source"])
    timestamp = format_timestamp(next_timestamp(now or datetime.now(), _latest_timestamp(catalog)))
    counts = ChangeCounts()
    for category in CATEGORIES:
        catalog[category] = _merge_category(catalog[category], source_categories[category], timestamp, counts)
    write_catalog(vault.path, catalog)
    return counts


def _merge_category(stored_entries, source_entries, timestamp, counts):
    """Apply one category of source entries to the stored entries of that category."""
    entries_by_id = {entry["id"]: entry for entry in stored_entries}
    for source_entry in source_entries:
        stored_entry = entries_by_id.get(source_entry["id"])
        if stored_entry is None:
            entries_by_id[source_entry["id"]] = create_entry(source_entry, timestamp)
            counts.added += 1
        else:
            record_observation(stored_entry, source_entry, timestamp)
            counts.updated += _recorded(stored_entry, timestamp)

    offered_ids = {source_entry["id"] for source_entry in source_entries}
    for entry_id, entry in entries_by_id.items():
        if entry_id not in offered_ids:
            record_absence(entry, timestamp)
            counts.removed += _recorded(entry, timestamp)
    return sort_entries(entries_by_id.values())


def _recorded(entry, timestamp):
    """1 when this run appended to any tracked history of `entry`, else 0."""
    return int(any(timestamp in entry[field] for field in TRACKED_FIELDS))


def _latest_timestamp(catalog):
    """The newest history key anywhere in the catalog, or None when it is empty."""
    keys = [
        key
        for category in CATEGORIES
        for entry in catalog[category]
        for field in TRACKED_FIELDS
        for key in entry[field]
    ]
    if not keys:
        return None
    return max(parse_timestamp(key) for key in keys)


def _warn(message):
    """Report a skipped download without failing the run."""
    print(f"mvault: warning: {message}", file=sys.stderr)
