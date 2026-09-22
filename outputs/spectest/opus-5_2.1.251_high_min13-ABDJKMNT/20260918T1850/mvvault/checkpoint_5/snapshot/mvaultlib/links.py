"""Viewer URLs: the paths the local server answers and the links reports print.

Reports name the viewer by its default address, because that is where `serve`
puts it unless the user moves it.
"""

from urllib.parse import quote

#: Scheme, host and port a viewer link points at, and `serve` binds by default.
VIEWER_SCHEME = "http"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8840

#: The landing page, and the query field that names a vault it could not find.
LANDING_PATH = "/"
MISSING_FIELD = "missing"

#: Route prefixes: the catalog pages, and the files a vault has downloaded.
CATALOG_PREFIX = "catalog"
ASSET_PREFIX = "vault"


def catalog_path(name):
    """A vault's catalog route, which redirects to its default category page."""
    return f"/{CATALOG_PREFIX}/{quote(name, safe='')}"


def category_path(name, category):
    """One category listing of a vault."""
    return f"{catalog_path(name)}/{quote(category, safe='')}"


def entry_path(name, category, entry_id):
    """The viewer link target of a single entry."""
    return f"{category_path(name, category)}/{quote(entry_id, safe='')}"


def media_path(name, filename):
    """The static endpoint serving one downloaded media file."""
    return f"/{ASSET_PREFIX}/{quote(name, safe='')}/media/{quote(filename, safe='')}"


def preview_path(name, entry_id):
    """The static endpoint serving the preview image saved for one entry."""
    return f"/{ASSET_PREFIX}/{quote(name, safe='')}/preview/{quote(entry_id, safe='')}"


def missing_path(name):
    """The landing page, told which vault the viewer was asked for in vain."""
    return f"{LANDING_PATH}?{MISSING_FIELD}={quote(name, safe='')}"


def viewer_url(path, host=DEFAULT_HOST, port=DEFAULT_PORT):
    """An absolute URL for a viewer path."""
    return f"{VIEWER_SCHEME}://{host}:{port}{path}"


def entry_link(name, category, entry_id):
    """The viewer link a change report prints beside an entry's title."""
    return viewer_url(entry_path(name, category, entry_id))
