"""The `migrate` command: store a legacy catalog in the native v3 shape."""

from mvaultlib.catalog import load_vault, write_catalog
from mvaultlib.versions import NATIVE_VERSION


def migrate_vault(name, now=None):
    """Convert a v1 or v2 catalog to v3 on disk; leave a v3 vault untouched."""
    vault = load_vault(name, now)
    if vault.stored_version != NATIVE_VERSION:
        write_catalog(vault.path, vault.catalog)
