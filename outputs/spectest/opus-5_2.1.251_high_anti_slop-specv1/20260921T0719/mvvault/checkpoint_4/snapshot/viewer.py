"""Addresses of the local vault viewer.

The viewer serves the entries of a vault under ``/catalog/<name>/<category>``.
Change reports point at that address, and ``serve`` listens on it by default,
so a link printed by one command opens in the server started by another.
"""

from urllib.parse import quote

#: Where ``serve`` listens, and where printed viewer links point.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8840

#: First path segment of every vault page the viewer serves.
CATALOG_ROOT = "catalog"


def catalog_path(name: str, *rest: str) -> str:
    """The viewer path of vault ``name``, or of a category or entry in it."""
    return "/".join([f"/{CATALOG_ROOT}", *(quote(part, safe="") for part in (name, *rest))])


def entry_url(name: str, category: str, identifier: str) -> str:
    """The address a change report prints beside one entry."""
    return f"http://{DEFAULT_HOST}:{DEFAULT_PORT}{catalog_path(name, category, identifier)}"
