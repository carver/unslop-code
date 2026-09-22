"""The viewer's shared rules: categories, routes and entry links.

The HTTP server, `digest` and the post-sync summary all have to agree on which
categories a catalog version presents, which of them a bare vault link lands
on, and what a link to a single entry looks like. Those three answers live
here so no caller has to restate them.
"""

from urllib.parse import quote

from .source import CATEGORIES

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8840
SCHEME = "http"

V1_CATEGORIES = ("entries",)


def categories_for(version):
    """The categories `version` files its entries under."""
    return V1_CATEGORIES if version == 1 else CATEGORIES


def default_category(version):
    """The category a bare vault link opens: the first this version has."""
    return categories_for(version)[0]


def catalog_route(name, category=None):
    """The viewer path of a vault, or of one of its categories."""
    path = f"/catalog/{quote(name, safe='')}"
    return f"{path}/{category}" if category else path


def default_route(name, version):
    """The path `/catalog/<name>` redirects to for a vault at `version`."""
    return catalog_route(name, default_category(version))


def entry_route(name, category, entry_id):
    """The viewer path of one entry inside a category."""
    return f"{catalog_route(name, category)}/{quote(entry_id, safe='')}"


def viewer_link(name, category, entry_id, host=DEFAULT_HOST, port=DEFAULT_PORT):
    """The absolute link a change report prints beside an entry's title."""
    return f"{SCHEME}://{host}:{port}{entry_route(name, category, entry_id)}"
