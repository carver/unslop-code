"""The viewer's version-aware view of the vaults below its root directory.

A version 1 vault offers the single ``entries`` category, later versions the
three category arrays; both are read where they lie, through the same
:class:`~vault.digest.CatalogView` a digest reads. Whatever the version, an
entry reads the same from here: its current tracked values resolved by that
version's key format, and its charts normalized to ISO 8601 timestamps.
"""

from collections import namedtuple
from pathlib import Path

from .. import digest, history, media, source
from ..entries import REMOVED_FIELD
from ..errors import VaultError
from . import charts

#: One listed entry: the title it currently holds and the states it is in.
Row = namedtuple("Row", "identifier title downloaded removed")

#: One category page: the vault it belongs to and the rows it lists.
Listing = namedtuple("Listing", "name version category categories rows")

#: One entry page: what the entry currently says of itself, the files the
#: vault stores for it, and the chart data of its count histories.
Detail = namedtuple(
    "Detail",
    "name version category identifier title description published width height"
    " source_url media_file preview charts",
)


def read(root, name):
    """Return the vault ``name`` below ``root``, or ``None`` if it cannot be read.

    ``name`` is one URL path segment and has to stay one directory name: a
    name that reaches outside ``root`` is no vault at all. Neither is one
    whose catalog is missing or unreadable, which the viewer answers with its
    vault-not-found page rather than an error.
    """
    if name != Path(name).name:
        return None
    try:
        return digest.load(str(Path(root) / name))
    except VaultError:
        return None


def categories(view):
    """The category names a vault of this version can be listed under."""
    return tuple(group.category for group in view.groups)


def default_category(view):
    """The category the vault's catalog page resolves to."""
    return view.groups[0].category


def listing(root, name, view, category):
    """Build the ``category`` page of the vault ``name``, in catalog order."""
    stored = media.stored_names(Path(root) / name)
    rows = [_row(view, entry, stored) for entry in _group(view, category).entries]
    return Listing(name, view.version, category, categories(view), rows)


def detail(root, name, view, category, identifier):
    """Build the page of one entry of ``category``, or ``None`` if it holds none.

    The lookup stays inside the named category, so an id that belongs to
    another one is not found here, and a version 3 entry the source dropped is
    still a page of its own.
    """
    entry = _find(_group(view, category), identifier)
    if entry is None:
        return None
    vault = Path(root) / name
    return Detail(
        name,
        view.version,
        category,
        identifier,
        history.latest_value(entry["title"], view.ordering) or identifier,
        history.latest_value(entry["description"], view.ordering) or "",
        entry["published"],
        entry["width"],
        entry["height"],
        source.resource_url(view.source, source.ENTRY_PATH, identifier),
        media.stored_file(identifier, media.stored_names(vault)),
        media.stored_file(identifier, media.stored_names(vault, media.PREVIEW_DIRECTORY)),
        charts.series(view, entry),
    )


def _group(view, category):
    """The catalog group of ``category``, which the route checked exists."""
    return next(found for found in view.groups if found.category == category)


def _find(group, identifier):
    """The entry of ``group`` with this id, or ``None`` if it has no such entry."""
    return next((entry for entry in group.entries if entry["id"] == identifier), None)


def _row(view, entry, stored):
    """Read one entry as the viewer lists it."""
    identifier = entry["id"]
    return Row(
        identifier,
        history.latest_value(entry["title"], view.ordering) or identifier,
        media.stored_file(identifier, stored) is not None,
        _is_removed(view, entry),
    )


def _is_removed(view, entry):
    """Whether the entry's newest ``removed`` point says the source dropped it.

    Only version 3 records removals; earlier versions have no removed state to
    show.
    """
    if REMOVED_FIELD not in view.tracked:
        return False
    return history.latest_value(entry[REMOVED_FIELD], view.ordering) is True
