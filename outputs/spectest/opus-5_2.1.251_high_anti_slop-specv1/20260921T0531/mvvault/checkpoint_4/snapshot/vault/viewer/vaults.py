"""The viewer's version-aware view of the vaults below its root directory.

A version 1 vault offers the single ``entries`` category, later versions the
three category arrays; both are read where they lie, through the same
:class:`~vault.digest.CatalogView` a digest reads.
"""

from collections import namedtuple
from pathlib import Path

from .. import digest, history, media
from ..entries import REMOVED_FIELD
from ..errors import VaultError

#: One listed entry: the title it currently holds and the states it is in.
Row = namedtuple("Row", "identifier title downloaded removed")

#: One category page: the vault it belongs to and the rows it lists.
Listing = namedtuple("Listing", "name version category categories rows")


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
    group = next(found for found in view.groups if found.category == category)
    stored = media.stored_names(Path(root) / name)
    rows = [_row(view, entry, stored) for entry in group.entries]
    return Listing(name, view.version, category, categories(view), rows)


def _row(view, entry, stored):
    """Read one entry as the viewer lists it."""
    identifier = entry["id"]
    return Row(
        identifier,
        history.latest_value(entry["title"], view.ordering) or identifier,
        media.is_stored(identifier, stored),
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
