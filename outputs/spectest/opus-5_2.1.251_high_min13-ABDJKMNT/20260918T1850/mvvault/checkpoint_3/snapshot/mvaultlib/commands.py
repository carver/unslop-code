"""The `init`, `sync`, `migrate` and `digest` subcommands."""

from dataclasses import dataclass, field
from datetime import datetime

from .catalog import CATEGORIES
from .digest import catalog_format, collect_changes
from .download import download_assets
from .entries import apply_observation
from .errors import MvaultError
from .history import newest_timestamp
from .report import render_digest, render_sync_summary
from .source import fetch_entries
from .timestamps import allocate_sync_timestamp, format_datetime
from .vault import Vault


@dataclass(frozen=True)
class SyncOptions:
    """Everything the `sync` options control, as the command sees it.

    `limits` maps each category to its maximum number of media downloads, with
    None standing for no limit at all.
    """

    limits: dict = field(default_factory=lambda: dict.fromkeys(CATEGORIES))
    media_format: str = None
    skip_metadata: bool = False
    skip_download: bool = False


def init_vault(name, url):
    """Create `<name>/` with an empty catalog pointing at `url`."""
    Vault(name).create(url)


def sync_vault(name, options):
    """Update a vault's metadata, then download the media it is still missing.

    The two phases are independent: either can be skipped, and the metadata is
    persisted before the download phase begins, so download failures -- which
    only warn -- can never cost the run its metadata.
    """
    vault = Vault(name)
    catalog, _ = vault.load()

    changes = None if options.skip_metadata else _update_metadata(vault, catalog)
    if not options.skip_download:
        download_assets(vault, catalog, options.limits, options.media_format)
    if changes is not None:
        print(render_sync_summary(changes))


def _update_metadata(vault, catalog):
    """The metadata phase: fetch the source, record what changed, and save.

    A v1 or v2 vault was migrated in memory by the load, so the single write
    here stores a v3 catalog and backs up the original, pre-migration one.
    """
    observed = fetch_entries(catalog["source"])
    stored = [entry for category in CATEGORIES for entry in catalog[category]]
    timestamp = allocate_sync_timestamp(newest_timestamp(stored))

    changes = apply_observation(catalog, observed, timestamp)
    vault.save(catalog)
    return changes


def migrate_vault(name):
    """Convert a v1 or v2 catalog to v3 on disk; a v3 vault is left untouched."""
    vault = Vault(name)
    catalog, migrated = vault.load()
    if migrated:
        vault.save(catalog)


def digest_vault(name):
    """Summarize a vault's notable changes, reading its catalog exactly as stored."""
    data = Vault(name).read()
    try:
        form = catalog_format(data)
        document = render_digest(
            name,
            form.version,
            form.source(data),
            collect_changes(data, form),
            format_datetime(datetime.now()),
        )
    except ValueError as error:
        raise MvaultError(f"vault {name!r} is not valid: {error}") from error
    print(document)
