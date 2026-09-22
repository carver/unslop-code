"""The read model behind an entry detail page.

Lookup is scoped to the one category the route names, so the same id stored in
another category is a different entry and does not answer here. What the page
then shows -- current title and description, the entry's static metadata, its
source-platform link and its chart data -- is resolved through the vault's own
version rules, leaving the page itself version-blind.
"""

from dataclasses import dataclass

from .charts import chart_series
from .entries import STATIC_VALIDATORS
from .formats import source_link
from .vault import MEDIA_DIRNAME, PREVIEWS_DIRNAME
from .viewer import VaultNotFound, entries_in, latest_value, matching_file, vault_path


class EntryNotFound(Exception):
    """The named category holds no entry with the requested id."""


@dataclass(frozen=True)
class Detail:
    """One entry as its detail page shows it.

    `media_file` is the saved filename the media endpoint should be asked for,
    or None when nothing in `media/` matches the entry; `has_preview` says
    whether `previews/` holds a match, which the preview endpoint finds by id.
    `charts` maps each charted field to its points.
    """

    name: str
    category: str
    entry_id: str
    title: str
    description: str
    published: str
    width: int
    height: int
    source: str
    media_file: str | None
    has_preview: bool
    charts: dict


def entry_detail(root, name, data, form, category, entry_id):
    """Everything the detail page of `entry_id` in `category` needs.

    Raises EntryNotFound when the category holds no such entry, and
    VaultNotFound when the entry it holds cannot be read as one.
    """
    entry = _checked(_lookup(data, category, entry_id), entry_id)
    vault = vault_path(root, name)
    return Detail(
        name=name,
        category=category,
        entry_id=entry_id,
        title=latest_value(entry, "title", form),
        description=latest_value(entry, "description", form),
        published=entry["published"],
        width=entry["width"],
        height=entry["height"],
        source=_source(data, form, entry_id),
        media_file=matching_file(vault / MEDIA_DIRNAME, entry_id),
        has_preview=matching_file(vault / PREVIEWS_DIRNAME, entry_id) is not None,
        charts=chart_series(entry, form),
    )


def _lookup(data, category, entry_id):
    """The entry `entry_id` names inside `category`, and nowhere else."""
    for entry in entries_in(data, category):
        if isinstance(entry, dict) and entry.get("id") == entry_id:
            return entry
    raise EntryNotFound(f"Category {category!r} holds no entry {entry_id!r}.")


def _checked(entry, entry_id):
    """The entry, once it carries the static fields the page displays."""
    for field, is_valid in STATIC_VALIDATORS.items():
        if not is_valid(entry.get(field)):
            raise VaultNotFound(f"entry {entry_id!r} has no usable {field!r}")
    return entry


def _source(data, form, entry_id):
    """The entry's source-platform URL; a vault without a source cannot show one."""
    try:
        return source_link(data, form, entry_id)
    except ValueError as error:
        raise VaultNotFound(f"{entry_id!r}: {error}") from error
