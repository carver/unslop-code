"""The `init`, `sync` and `migrate` subcommands."""

from .catalog import CATEGORIES
from .entries import apply_observation
from .history import newest_timestamp
from .source import fetch_entries
from .timestamps import allocate_sync_timestamp
from .vault import Vault


def init_vault(name, url):
    """Create `<name>/` with an empty catalog pointing at `url`."""
    Vault(name).create(url)


def sync_vault(name):
    """Fetch the vault's source and record what changed since the last sync.

    A v1 or v2 vault is migrated in memory first, so the single write at the end
    stores a v3 catalog and backs up the original, pre-migration one.

    The vault and the source metadata are both fully validated before anything
    is written, so a failure of either leaves the vault exactly as it was.
    """
    vault = Vault(name)
    catalog, _ = vault.load()
    observed = fetch_entries(catalog["source"])

    stored = [entry for category in CATEGORIES for entry in catalog[category]]
    apply_observation(catalog, observed, allocate_sync_timestamp(newest_timestamp(stored)))
    vault.save(catalog)


def migrate_vault(name):
    """Convert a v1 or v2 catalog to v3 on disk; a v3 vault is left untouched."""
    vault = Vault(name)
    catalog, migrated = vault.load()
    if migrated:
        vault.save(catalog)
