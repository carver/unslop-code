"""The URLs of the local viewer.

Reports print viewer links for the entries they name, and the viewer itself
builds the paths it redirects and links to, so both start from here. A link
points at the default bind address unless the viewer was moved elsewhere.
"""

from urllib.parse import quote, urlencode

SCHEME = "http"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8840

ROOT = "/"
CATALOG_ROOT = "/catalog"
#: Query field naming the vault a redirect to the landing page could not find.
MISSING_FIELD = "missing"


def catalog_path(name):
    """Path of a vault's catalog, which resolves to its default category."""
    return f"{CATALOG_ROOT}/{_segment(name)}"


def category_path(name, category):
    """Path of one category listing of a vault."""
    return f"{catalog_path(name)}/{_segment(category)}"


def entry_path(name, category, identifier):
    """Path of the viewer page that surfaces one entry."""
    return f"{category_path(name, category)}/{_segment(identifier)}"


def entry_url(name, category, identifier, host=DEFAULT_HOST, port=DEFAULT_PORT):
    """Absolute viewer link to one entry, as reports print it."""
    return f"{SCHEME}://{host}:{port}{entry_path(name, category, identifier)}"


def missing_path(name):
    """Path of the landing page telling the browser ``name`` is not a vault."""
    return f"{ROOT}?{urlencode({MISSING_FIELD: name})}"


def _segment(text):
    """Escape one path segment, which may hold anything a vault name may."""
    return quote(str(text), safe="")
