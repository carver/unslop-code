"""The viewer's shared rules: categories, routes and entry links.

The HTTP server, `digest` and the post-sync summary all have to agree on which
categories a catalog version presents, which of them a bare vault link lands
on, and what a link to a single entry or a saved file looks like. Those answers
live here so no caller has to restate them.
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


def storage_category(category, version):
    """The v3 category the entries of a request category live in, or `None`.

    An annotation works on the version 3 upgrade of a catalog, and a v1 vault is
    routed under `entries`, whose entries the upgrade files under the first v3
    category; every other version already names its own v3 categories.
    """
    if category not in categories_for(version):
        return None
    return CATEGORIES[0] if version == 1 else category


def catalog_route(name, category=None):
    """The viewer path of a vault, or of one of its categories."""
    path = f"/catalog/{quote(name, safe='')}"
    return f"{path}/{category}" if category else path


def default_route(name, version):
    """The path `/catalog/<name>` redirects to for a vault at `version`."""
    return catalog_route(name, default_category(version))


def entry_route(name, category, entry_id, timecode=None):
    """The viewer path of one entry inside a category.

    A `timecode` asks the detail page to seek playback to that second, which is
    how a created annotation hands the browser back to its entry.
    """
    path = f"{catalog_route(name, category)}/{quote(entry_id, safe='')}"
    return path if timecode is None else f"{path}?timecode={timecode}"


def asset_route(name, kind, leaf):
    """The viewer path that serves one saved file of a vault.

    `kind` is `media`, addressed by saved filename, or `preview`, addressed by
    the id of the entry the image belongs to.
    """
    return f"/vault/{quote(name, safe='')}/{kind}/{quote(leaf, safe='')}"


def viewer_link(name, category, entry_id, host=DEFAULT_HOST, port=DEFAULT_PORT):
    """The absolute link a change report prints beside an entry's title."""
    return f"{SCHEME}://{host}:{port}{entry_route(name, category, entry_id)}"
