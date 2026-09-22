"""Applying an annotation mutation to a stored vault.

Annotations only exist in the version 3 catalog shape, so a mutation against a
v1 or v2 vault migrates the whole catalog first, by the same rules the
`migrate` command uses, and then persists the migration and the annotation in a
single write -- which leaves `catalog.bak` holding the catalog as it was before
either change.

A v1 request addresses its entry through the pre-migration `entries` category;
everything after the lookup, including the redirect, speaks in the `episodes`
the entry migrates into.
"""

import json
from datetime import datetime
from http import HTTPStatus

from mvaultlib.annotations import (
    AnnotationError,
    create_annotation,
    delete_annotation,
    update_annotation,
)
from mvaultlib.catalog import read_raw_catalog, write_catalog
from mvaultlib.errors import MvaultError
from mvaultlib.timestamps import format_timestamp
from mvaultlib.versions import NATIVE_VERSION, detect_version, upgrade_catalog
from mvaultlib.viewer.links import (
    MODERN_DEFAULT_CATEGORY,
    V1_CATEGORY,
    catalog_path,
    valid_categories,
)

#: The change each annotation method applies to an entry's annotation list. A
#: create reports the seconds its redirect carries; the others report nothing.
MUTATIONS = {"POST": create_annotation, "PATCH": update_annotation, "DELETE": delete_annotation}


def json_payload(raw):
    """The JSON object an annotation request body has to be."""
    try:
        payload = json.loads(raw)
    except ValueError as error:
        raise AnnotationError(HTTPStatus.BAD_REQUEST, f"malformed JSON body: {error}") from error
    if not isinstance(payload, dict):
        raise AnnotationError(HTTPStatus.BAD_REQUEST, "request body must be a JSON object")
    return payload


def apply_annotation(method, vault_path, name, category, entry_id, payload, now=None):
    """Apply one annotation mutation and return the path to redirect to."""
    catalog = _stored_catalog(vault_path, name)
    version = _stored_version(catalog, name)
    target = _target_category(version, category)
    if version != NATIVE_VERSION:
        catalog = _migrated(catalog, name, now)

    annotations = _entry(catalog, target, entry_id).setdefault("annotations", [])
    seek = MUTATIONS[method](annotations, payload)
    write_catalog(vault_path, catalog)
    return _detail_path(name, target, entry_id, seek)


def _stored_catalog(vault_path, name):
    """The catalog on disk, exactly as written, or a `404` when there is none."""
    try:
        return read_raw_catalog(str(vault_path))
    except MvaultError as error:
        raise AnnotationError(HTTPStatus.NOT_FOUND, f"no vault '{name}' to annotate") from error


def _stored_version(catalog, name):
    """The version on disk; one the viewer cannot read is not a vault to write."""
    try:
        return detect_version(name, catalog)
    except MvaultError as error:
        raise AnnotationError(HTTPStatus.NOT_FOUND, str(error)) from error


def _target_category(version, category):
    """The v3 category holding the entry a URL names in the version on disk."""
    if category not in valid_categories(version):
        raise AnnotationError(HTTPStatus.NOT_FOUND, f"no category '{category}' in this vault")
    return MODERN_DEFAULT_CATEGORY if category == V1_CATEGORY else category


def _migrated(catalog, name, now):
    """The whole catalog in v3 shape; a failure here leaves the vault as it is."""
    timestamp = format_timestamp(now or datetime.now())
    try:
        return upgrade_catalog(name, catalog, timestamp)[1]
    except MvaultError as error:
        raise AnnotationError(
            HTTPStatus.INTERNAL_SERVER_ERROR, f"could not migrate vault '{name}': {error}"
        ) from error


def _entry(catalog, category, entry_id):
    """The entry to annotate, looked up inside its category alone."""
    found = [entry for entry in catalog.get(category, []) if entry.get("id") == entry_id]
    if not found:
        raise AnnotationError(HTTPStatus.NOT_FOUND, f"no entry '{entry_id}' in '{category}'")
    return found[0]


def _detail_path(name, category, entry_id, seek):
    """The entry's detail page, carrying the seconds a create asks it to seek to."""
    path = catalog_path(name, category, entry_id)
    return path if seek is None else f"{path}?timecode={seek}"
