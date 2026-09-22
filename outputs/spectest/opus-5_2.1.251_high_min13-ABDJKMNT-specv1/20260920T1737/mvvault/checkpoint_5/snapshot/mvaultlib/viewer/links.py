"""Viewer addresses: the default endpoint, and the version-aware catalog routes.

Both the HTTP server and the links printed by `digest` and `sync` build their
paths here, so a route and the link that points at it can never disagree.
"""

from urllib.parse import quote

from mvaultlib.entries import CATEGORIES

DEFAULT_SCHEME = "http"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8840

#: Leading segment of the catalog pages and of the static asset endpoints.
CATALOG_PREFIX = "catalog"
VAULT_PREFIX = "vault"

#: The `/vault` endpoints serving stored media files and preview images.
MEDIA_ENDPOINT = "media"
PREVIEW_ENDPOINT = "preview"

#: The single category of a version 1 vault, which has no per-category arrays.
V1_CATEGORY = "entries"

#: The category a version 2 or version 3 vault opens on.
MODERN_DEFAULT_CATEGORY = "episodes"


def default_category(version):
    """The category `/catalog/<name>` redirects to for a vault of `version`."""
    return V1_CATEGORY if version == 1 else MODERN_DEFAULT_CATEGORY


def valid_categories(version):
    """The categories a vault of `version` lists, in catalog order."""
    return (V1_CATEGORY,) if version == 1 else CATEGORIES


def catalog_path(name, category=None, entry_id=None):
    """The viewer path of a vault, one of its categories or one of its entries."""
    tail = [part for part in (category, entry_id) if part is not None]
    return _path(CATALOG_PREFIX, name, *tail)


def asset_path(name, endpoint, tail):
    """The static path serving one stored asset of a vault.

    `endpoint` is `media`, whose `tail` is a saved file name, or `preview`,
    whose `tail` is an entry id.
    """
    return _path(VAULT_PREFIX, name, endpoint, tail)


def _path(*parts):
    """A viewer path whose segments carry any character the caller passed."""
    return "/" + "/".join(quote(part, safe="") for part in parts)


def viewer_link(name, category, entry_id, host=DEFAULT_HOST, port=DEFAULT_PORT):
    """The absolute link a change report prints for one entry."""
    return f"{DEFAULT_SCHEME}://{host}:{port}{catalog_path(name, category, entry_id)}"
