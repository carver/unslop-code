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
    current_value,
    record_absence,
    record_observation,
    sort_entries,
)
from mvaultlib.source import fetch_source
from mvaultlib.timestamps import format_timestamp, next_timestamp, parse_timestamp
from mvaultlib.viewer.links import viewer_link

ADDED = "Added"
REMOVED = "Removed"
UPDATED = "Updated"


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


@dataclass(frozen=True)
class EntryChange:
    """One entry the metadata phase changed, as the summary reports it."""

    kind: str
    category: str
    entry_id: str
    title: str

    def render(self, name):
        """The entry's summary line, ending in its viewer link."""
        return f"{self.kind}: {self.title} {viewer_link(name, self.category, self.entry_id)}"


@dataclass
class SyncSummary:
    """What one metadata phase did: the entries it changed, and their counts."""

    changes: list = field(default_factory=list)

    def record(self, kind, category, entry):
        """Note that this run added, removed or updated one stored entry."""
        title = current_value(entry["title"])
        self.changes.append(EntryChange(kind, category, entry["id"], title))

    def count(self, kind):
        return sum(1 for change in self.changes if change.kind == kind)

    def render(self, name):
        """The changed entries, one per line, above the counts line."""
        lines = [change.render(name) for change in self.changes]
        lines.append(
            f"Added {self.count(ADDED)}, removed {self.count(REMOVED)}, "
            f"updated {self.count(UPDATED)}."
        )
        return "\n".join(lines)


def sync_vault(name, options=None, now=None, out=sys.stdout, warn=None):
    """Run the metadata phase, then the download phase, then report the changes."""
    options = options or SyncOptions()
    vault = load_vault(name, now)
    summary = None
    if not options.skip_metadata:
        summary = update_metadata(vault, now)
    if not options.skip_download:
        download_assets(vault.path, vault.catalog, options, warn or _warn)
    if summary is not None:
        print(summary.render(name), file=out)


def update_metadata(vault, now):
    """Merge the source into the catalog, persist it and summarize the changes."""
    catalog = vault.catalog
    source_categories = fetch_source(catalog["source"])
    timestamp = format_timestamp(next_timestamp(now or datetime.now(), _latest_timestamp(catalog)))
    summary = SyncSummary()
    for category in CATEGORIES:
        catalog[category] = _merge_category(
            catalog[category], source_categories[category], category, timestamp, summary
        )
    write_catalog(vault.path, catalog)
    return summary


def _merge_category(stored_entries, source_entries, category, timestamp, summary):
    """Apply one category of source entries to the stored entries of that category."""
    entries_by_id = {entry["id"]: entry for entry in stored_entries}
    for source_entry in source_entries:
        stored_entry = entries_by_id.get(source_entry["id"])
        if stored_entry is None:
            created = create_entry(source_entry, timestamp)
            entries_by_id[created["id"]] = created
            summary.record(ADDED, category, created)
        else:
            record_observation(stored_entry, source_entry, timestamp)
            if _recorded(stored_entry, timestamp):
                summary.record(UPDATED, category, stored_entry)

    offered_ids = {source_entry["id"] for source_entry in source_entries}
    for entry_id, entry in entries_by_id.items():
        if entry_id in offered_ids:
            continue
        record_absence(entry, timestamp)
        if _recorded(entry, timestamp):
            summary.record(REMOVED, category, entry)
    return sort_entries(entries_by_id.values())


def _recorded(entry, timestamp):
    """True when this run appended to any tracked history of `entry`."""
    return any(timestamp in entry[field] for field in TRACKED_FIELDS)


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
