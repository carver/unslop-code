"""The local browser viewer for vaults of any supported catalog version.

The viewer reads a vault in the version it is stored in, so browsing a legacy
vault never migrates it, and never writes to it at all.
"""

from .server import serve

__all__ = ["serve"]
