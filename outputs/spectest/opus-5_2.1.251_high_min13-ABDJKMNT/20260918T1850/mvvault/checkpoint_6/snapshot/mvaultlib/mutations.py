"""Applying an annotation mutation to a vault on disk.

An annotation needs the v3 `annotations` field, so a v1 or v2 catalog is
migrated in memory first and stored together with the annotation in a single
backed-up write -- which leaves `catalog.bak` holding the state before both
changes. A request that is refused writes nothing at all, so a rejected
mutation never migrates a vault as a side effect.
"""

from .annotations import (
    AnnotationError,
    AnnotationNotFound,
    create,
    delete,
    request_fields,
    update,
)
from .catalog import CATEGORIES
from .formats import V1_CATEGORIES
from .legacy import load_catalog
from .links import entry_path, timecode_path
from .vault import Vault
from .viewer import entries_in, open_vault

#: What each annotation method does to one entry's annotation list.
EDITS = {"POST": create, "PATCH": update, "DELETE": delete}

#: Where a v1 vault's categories end up once its catalog is migrated: a v1
#: request names `entries`, but the entry itself lands in `episodes`.
MIGRATED_CATEGORIES = dict(zip(V1_CATEGORIES, CATEGORIES))


class MigrationFailed(AnnotationError):
    """The catalog cannot be brought to v3, so no annotation can be stored."""

    status = 500


def apply_annotation(root, name, category, entry_id, method, body):
    """Store one annotation mutation and return where the browser should go.

    Raises VaultNotFound when `name` is not a readable vault, and
    AnnotationError -- carrying the status to answer with -- for a request this
    vault cannot satisfy.
    """
    fields = request_fields(body)
    stored, form = open_vault(root, name)
    if category not in form.categories:
        raise AnnotationNotFound(f"Vault {name!r} has no category {category!r}.")

    catalog = _version_3(name, stored)
    migrated = MIGRATED_CATEGORIES.get(category, category)
    timecode = EDITS[method](_entry(catalog, migrated, entry_id), fields)
    Vault(name, root).save(catalog)
    return _destination(name, migrated, entry_id, timecode)


def _version_3(name, stored):
    """The catalog as v3, migrating a legacy one in memory and nowhere else."""
    try:
        return load_catalog(stored)[0]
    except ValueError as error:
        raise MigrationFailed(f"Vault {name!r} cannot be migrated: {error}") from error


def _entry(catalog, category, entry_id):
    """The entry an annotation route names, in its post-migration category."""
    for entry in entries_in(catalog, category):
        if entry.get("id") == entry_id:
            return entry
    raise AnnotationNotFound(f"Category {category!r} holds no entry {entry_id!r}.")


def _destination(name, category, entry_id, timecode):
    """The entry's page, told where to start playback when one was created."""
    if timecode is None:
        return entry_path(name, category, entry_id)
    return timecode_path(name, category, entry_id, timecode)
