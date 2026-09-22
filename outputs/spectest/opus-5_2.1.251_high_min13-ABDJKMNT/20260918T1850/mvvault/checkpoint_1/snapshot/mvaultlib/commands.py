"""The `init` and `sync` subcommands."""

from .catalog import CATEGORIES, Vault
from .entries import apply_observation
from .history import newest_timestamp
from .source import fetch_entries
from .timestamps import allocate_sync_timestamp


def init_vault(name, url):
    """Create `<name>/` with an empty catalog pointing at `url`."""
    Vault(name).create(url)


def sync_vault(name):
    """Fetch the vault's source and record what changed since the last sync.

    The vault and the source metadata are both fully validated before anything
    is written, so a failure of either leaves the vault exactly as it was.
    """
    vault = Vault(name)
    catalog = vault.load()
    observed = fetch_entries(catalog["source"])

    stored = [entry for category in CATEGORIES for entry in catalog[category]]
    apply_observation(catalog, observed, allocate_sync_timestamp(newest_timestamp(stored)))
    vault.save(catalog)
