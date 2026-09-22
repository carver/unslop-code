"""Viewer links, category routes and listing rows shared by the server and the reports.

A vault is browsed under the categories its own version defines: version 1 keeps
a single ``entries`` category, later versions keep the native ones. The rules
here are the ones both the HTTP routes and the change reports have to agree on,
so a link printed by ``digest`` resolves to the page the server serves.
"""

from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

from . import catalog, versions
from .downloads import MEDIA_DIR, PARTIAL_SUFFIX
from .errors import InvalidVaultError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8840
SCHEME = "http"
#: Single category a version 1 catalog is browsed under.
V1_CATEGORY = "entries"
#: First segment of the routes serving the files a vault has downloaded.
VAULT_ROOT = "vault"
#: Segments naming which downloaded asset a static route serves.
MEDIA_ROUTE = "media"
PREVIEW_ROUTE = "preview"


class EntryRow(NamedTuple):
    """What a category listing shows about one entry, in catalog order."""

    id: str
    title: str
    downloaded: bool
    removed: bool


def categories_for(version):
    """Category routes a vault of ``version`` can be browsed under, the default one first."""
    return (V1_CATEGORY,) if version == 1 else catalog.CATEGORIES


def default_category(version):
    """Category a vault of ``version`` opens on when no category is given."""
    return categories_for(version)[0]


def route_category(version, category):
    """Route the native ``category`` is browsed under in a vault of ``version``."""
    return V1_CATEGORY if version == 1 else category


def is_contained(segment):
    """Tell whether a request segment names one entry inside the working directory.

    Anything that would step outside it, a traversal sequence or a path of its
    own, is refused here rather than resolved.
    """
    return bool(segment) and Path(segment).name == segment


def vault_path(name):
    """Path of the vault route, which redirects to the vault's default category."""
    return f"/catalog/{quote(name)}"


def category_path(name, category):
    """Path of one category listing page."""
    return f"{vault_path(name)}/{category}"


def entry_path(name, category, entry_id):
    """Path of the page a viewer link points at."""
    return f"{category_path(name, category)}/{quote(entry_id)}"


def media_path(name, filename):
    """Path of the static endpoint serving one downloaded media file."""
    return f"/{VAULT_ROOT}/{quote(name)}/{MEDIA_ROUTE}/{quote(filename)}"


def preview_path(name, entry_id):
    """Path of the static endpoint serving the preview image downloaded for an entry."""
    return f"/{VAULT_ROOT}/{quote(name)}/{PREVIEW_ROUTE}/{quote(entry_id)}"


def entry_link(name, category, entry_id, host=DEFAULT_HOST, port=DEFAULT_PORT):
    """Absolute viewer URL of one entry, as printed in the human-facing change reports."""
    return f"{SCHEME}://{host}:{port}{entry_path(name, category, entry_id)}"


def load_view(name):
    """Read a vault in its own version's shape.

    Returns ``None`` when ``name`` does not address a vault directory beside the
    working directory, or when its catalog cannot be read, so that the viewer can
    answer with a redirect instead of an error.
    """
    if not is_contained(name):
        return None
    try:
        return versions.view(catalog.read_document(name), name)
    except InvalidVaultError:
        return None


def default_path(name):
    """Path the vault route resolves to, or ``None`` when the vault is no longer readable."""
    loaded = load_view(name)
    return category_path(name, default_category(loaded.version)) if loaded else None


def category_entries(loaded, category):
    """Entries a category route lists, or ``None`` when the route is not valid here."""
    listed = (entries for _, _, entries in loaded.categories)
    return dict(zip(categories_for(loaded.version), listed)).get(category)


def listing_rows(name, loaded, entries):
    """Build the rows of a category listing, in catalog order."""
    filenames = _media_filenames(name)
    return [
        EntryRow(
            entry["id"],
            versions.latest_value(entry["title"], loaded.key_order),
            match_filename(filenames, entry["id"]) is not None,
            _is_removed(entry, loaded),
        )
        for entry in entries
    ]


def downloaded_media(name, entry_id):
    """Media file the vault holds for ``entry_id``, or ``None`` while none is stored."""
    return match_filename(_media_filenames(name), entry_id)


def match_filename(filenames, entry_id):
    """First saved filename containing ``entry_id``; an interrupted download is not one."""
    matching = sorted(
        filename
        for filename in filenames
        if entry_id in filename and not filename.endswith(PARTIAL_SUFFIX)
    )
    return matching[0] if matching else None


def _media_filenames(name):
    """Names of the media files the vault has downloaded so far."""
    directory = Path(name) / MEDIA_DIR
    return [path.name for path in directory.iterdir()] if directory.is_dir() else []


def _is_removed(entry, loaded):
    """Tell whether the entry's latest removal observation took it out of the source.

    Versions without a ``removed`` history never report an entry as removed.
    """
    if catalog.REMOVED_FIELD not in loaded.fields:
        return False
    return versions.latest_value(entry[catalog.REMOVED_FIELD], loaded.key_order) is True
