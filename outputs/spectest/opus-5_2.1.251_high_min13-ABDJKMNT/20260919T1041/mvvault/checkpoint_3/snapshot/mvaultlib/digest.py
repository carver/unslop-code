"""Reading a vault at its own version and classifying its notable changes.

`digest` never migrates, so each supported version gets a :class:`VaultView`
describing how that version groups entries, which tracked fields it stores and
how its history keys are ordered. Everything else works off that view.
"""

from dataclasses import dataclass

from . import catalog as catalog_module
from . import versions
from .history import SOURCE_TRACKED_FIELDS, TRACKED_FIELDS
from .schema import CATEGORIES, VERSION

#: The change groups, in the precedence order an entry is tested against.
REMOVED, ADDED, UPDATED = "Removed", "Added", "Updated"
GROUPS = (REMOVED, ADDED, UPDATED)

#: The single group a version 1 catalog, which has no categories, is shown under.
V1_GROUP = "Entries"


@dataclass(frozen=True)
class VaultView:
    """One vault read at its declared version.

    `groups` pairs each category label with its entries, `tracked` names the
    tracked fields that version stores, `key_order` sorts history keys, and
    `detect_removals` says whether the version carries a `removed` field.
    """

    version: int
    source: str
    groups: tuple
    tracked: tuple
    key_order: object
    detect_removals: bool


def load_view(name):
    """Read the vault `name` as the view its declared version calls for."""
    raw = catalog_module.read_raw(name)
    version = versions.declared_version(raw, name)
    return _v1_view(raw, name) if version == 1 else _category_view(raw, name, version)


def _v1_view(raw, name):
    """Version 1: one flat entry list, a derived source and epoch history keys."""
    source_id = versions.text_field(raw, "source_id", name)
    return VaultView(
        version=1,
        source=versions.V1_SOURCE_TEMPLATE.format(source_id=source_id),
        groups=((V1_GROUP, versions.array_field(raw, "entries", name)),),
        tracked=SOURCE_TRACKED_FIELDS,
        key_order=int,
        detect_removals=False,
    )


def _category_view(raw, name, version):
    """Versions 2 and 3: three categories and ISO 8601 history keys.

    Only version 3 stores `removed`, so only it can report removals and count
    `removed` among the tracked fields.
    """
    native = version == VERSION
    return VaultView(
        version=version,
        source=versions.text_field(raw, "source", name),
        groups=tuple((category.capitalize(), versions.array_field(raw, category, name)) for category in CATEGORIES),
        tracked=TRACKED_FIELDS if native else SOURCE_TRACKED_FIELDS,
        key_order=str,
        detect_removals=native,
    )


def classify(entry, view):
    """The group `entry` belongs to and its changed fields, or `None`.

    The groups are tested in precedence order, so an entry that would qualify
    for several of them is reported only as the first one that matches.
    """
    if view.detect_removals and _is_removal(entry, view):
        return REMOVED, ()
    if all(len(entry[field]) < 2 for field in view.tracked):
        return ADDED, ()
    changed = _changed_fields(entry, view)
    return (UPDATED, changed) if changed else None


def current_title(entry, view):
    """The entry's title as of its latest `title` history key."""
    return _ordered_values(entry, "title", view)[-1]


def _is_removal(entry, view):
    """Whether `removed` has just turned true, a first observation included."""
    values = _ordered_values(entry, "removed", view)
    return values[-1] is True and (len(values) == 1 or values[-2] is False)


def _changed_fields(entry, view):
    """Tracked fields with at least two observations whose latest two differ."""
    changed = []
    for field in view.tracked:
        values = _ordered_values(entry, field, view)
        if len(values) > 1 and values[-1] != values[-2]:
            changed.append(field)
    return tuple(changed)


def _ordered_values(entry, field, view):
    """One history's values, oldest first under this version's key order."""
    history = entry[field]
    return [history[key] for key in sorted(history, key=view.key_order)]
