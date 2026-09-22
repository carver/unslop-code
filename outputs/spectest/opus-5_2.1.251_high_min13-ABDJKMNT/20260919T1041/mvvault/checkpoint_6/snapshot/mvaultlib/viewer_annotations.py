"""Applying one annotation request to a vault, migrating it first when it must be.

The catalog is read at whatever version it declares and converted to the native
layout in memory, so a version 1 or 2 vault is migrated and annotated by the one
write at the end: `catalog.bak` then holds the state from before both changes,
and a request that is rejected on the way leaves the vault exactly as it was.
"""

import json

from . import annotations
from . import catalog as catalog_module
from . import versions, viewer_links
from .annotations import BAD_REQUEST, NOT_FOUND, AnnotationError
from .errors import MvaultError
from .schema import CATEGORIES
from .vault_view import V1_CATEGORY

SERVER_ERROR = 500

#: The category a version 1 vault's entries live in once it has been migrated.
MIGRATED_CATEGORY = CATEGORIES[0]

#: What each annotation method does to the addressed entry.
METHODS = {"POST": annotations.create, "PATCH": annotations.update, "DELETE": annotations.delete}


def mutate(method, name, category, entry_id, body):
    """Apply one annotation method to an entry and return where to send the client.

    Raises :class:`annotations.AnnotationError` for every request the vault
    cannot answer; the catalog is written only once the mutation has succeeded.
    """
    payload = _payload(body)
    raw, version = _declared(name)
    catalog = _native(raw, name)
    category = _migrated_category(version, category)

    annotation = METHODS[method](_entry(catalog, category, entry_id), payload)
    _persist(name, catalog)

    route = viewer_links.catalog_route(name, category, entry_id)
    return f"{route}?timecode={annotation['timecode']}" if method == "POST" else route


def _payload(body):
    """The JSON object the request body carries."""
    try:
        payload = json.loads(body)
    except ValueError:
        raise AnnotationError(BAD_REQUEST, "The request body is not valid JSON.") from None

    if not isinstance(payload, dict):
        raise AnnotationError(BAD_REQUEST, "The request body is not a JSON object.")
    return payload


def _declared(name):
    """The vault's catalog data and the version it declares."""
    try:
        raw = catalog_module.read_raw(name)
        return raw, versions.declared_version(raw, name)
    except MvaultError:
        raise AnnotationError(NOT_FOUND, f"Vault '{name}' could not be read.") from None


def _native(raw, name):
    """The catalog in native form; a conversion that fails annotates nothing."""
    try:
        return versions.to_native(raw, name)[0]
    except MvaultError as problem:
        raise AnnotationError(SERVER_ERROR, f"Migration failed: {problem}") from None


def _migrated_category(version, category):
    """Where the request's category lives after migration.

    Version 1 is addressed by its own `entries` category and migrates into
    `episodes`; the native categories keep their names across the migration.
    """
    if category not in ((V1_CATEGORY,) if version == 1 else CATEGORIES):
        raise AnnotationError(NOT_FOUND, "This vault has no such category.")
    return MIGRATED_CATEGORY if version == 1 else category


def _entry(catalog, category, entry_id):
    """The entry the request addresses, looked up in that one category."""
    entry = next((row for row in catalog[category] if row["id"] == entry_id), None)
    if entry is None:
        raise AnnotationError(NOT_FOUND, "No such entry in this category.")
    return entry


def _persist(name, catalog):
    """The single write, which backs up the catalog as it was before the request."""
    try:
        catalog_module.write(name, catalog)
    except MvaultError as problem:
        raise AnnotationError(SERVER_ERROR, str(problem)) from None
