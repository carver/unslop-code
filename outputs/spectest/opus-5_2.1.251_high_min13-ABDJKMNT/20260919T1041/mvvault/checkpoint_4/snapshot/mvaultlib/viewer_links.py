"""The URLs the viewer serves and the reports link to."""

from urllib.parse import quote

SCHEME = "http"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8840

CATALOG_SEGMENT = "catalog"
CATALOG_ROOT = f"/{CATALOG_SEGMENT}"


def catalog_route(name, *segments):
    """The viewer path of a vault, one of its categories, or one entry."""
    path = "/".join(quote(str(segment), safe="") for segment in (name, *segments))
    return f"{CATALOG_ROOT}/{path}"


def entry_url(name, category, entry_id, host=DEFAULT_HOST, port=DEFAULT_PORT):
    """The absolute link a change report appends to an entry's line."""
    return f"{SCHEME}://{host}:{port}{catalog_route(name, category, entry_id)}"
