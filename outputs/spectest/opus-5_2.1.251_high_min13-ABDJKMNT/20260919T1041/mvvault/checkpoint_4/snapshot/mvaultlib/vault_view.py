"""Reading a vault at its declared version, without migrating it on disk.

Each supported version presents its entries differently: version 1 keeps one
flat `entries` list keyed by UNIX epoch seconds, versions 2 and 3 use the three
native categories keyed by ISO 8601 datetimes, and only version 3 carries the
`removed` field. A :class:`VaultView` holds those differences, so `digest` and
the browser viewer can read any supported vault through one shape.
"""

from dataclasses import dataclass

from . import catalog as catalog_module
from . import versions
from .history import SOURCE_TRACKED_FIELDS, TRACKED_FIELDS
from .schema import CATEGORIES, VERSION

#: The single category a version 1 catalog, which has no categories, presents.
V1_CATEGORY = "entries"


@dataclass(frozen=True)
class VaultView:
    """One vault read at its declared version.

    `categories` pairs each category name with its entries in catalog order,
    `tracked` names the tracked fields that version stores, `key_order` sorts
    history keys, and `detect_removals` says whether the version has `removed`.
    """

    version: int
    source: str
    categories: tuple
    tracked: tuple
    key_order: object
    detect_removals: bool

    @property
    def default_category(self):
        """The category a bare reference to the vault resolves to."""
        return self.categories[0][0]

    def entries_of(self, category):
        """The entries of `category`, or `None` if this version has no such category."""
        return dict(self.categories).get(category)


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
        categories=((V1_CATEGORY, versions.array_field(raw, "entries", name)),),
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
        categories=tuple((category, versions.array_field(raw, category, name)) for category in CATEGORIES),
        tracked=TRACKED_FIELDS if native else SOURCE_TRACKED_FIELDS,
        key_order=str,
        detect_removals=native,
    )


def ordered_values(entry, field, view):
    """One history's values, oldest first under this version's key order."""
    history = entry[field]
    return [history[key] for key in sorted(history, key=view.key_order)]


def latest_value(entry, field, view):
    """The value at the entry's newest key for `field`."""
    return ordered_values(entry, field, view)[-1]


def current_title(entry, view):
    """The entry's title as of its latest `title` history key."""
    return latest_value(entry, "title", view)


def is_removed(entry, view):
    """Whether the vault's version knows the entry as removed right now."""
    return view.detect_removals and latest_value(entry, "removed", view) is True
