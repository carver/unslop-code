"""Addresses of the local vault viewer.

The viewer serves the entries of a vault under ``/catalog/<name>/<category>``
and the files it downloaded for them under ``/vault/<name>``.  Change reports
point at the first of those, and ``serve`` listens on it by default, so a link
printed by one command opens in the server started by another.
"""

from urllib.parse import quote

#: Where ``serve`` listens, and where printed viewer links point.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8840

#: First path segment of every vault page the viewer serves.
CATALOG_ROOT = "catalog"

#: First path segment of every stored file the viewer serves.
VAULT_ROOT = "vault"

#: Query a detail page seeks its player to, in whole seconds.
TIMECODE_QUERY = "timecode"

#: The two kinds of stored file, as the paths serving them name them.
MEDIA_ROUTE = "media"
PREVIEW_ROUTE = "preview"


def catalog_path(name: str, *rest: str) -> str:
    """The viewer path of vault ``name``, or of a category or entry in it."""
    return _path(CATALOG_ROOT, name, *rest)


def vault_path(name: str, kind: str, target: str) -> str:
    """The viewer path of one file vault ``name`` downloaded.

    A media file is named by the filename the vault stored it under; a preview
    image is named by the entry it belongs to.
    """
    return _path(VAULT_ROOT, name, kind, target)


def entry_url(name: str, category: str, identifier: str) -> str:
    """The address a change report prints beside one entry."""
    return f"http://{DEFAULT_HOST}:{DEFAULT_PORT}{catalog_path(name, category, identifier)}"


def _path(root: str, *parts: str) -> str:
    """Join path segments under one root, escaping each of them."""
    return "/".join([f"/{root}", *(quote(part, safe="") for part in parts)])
