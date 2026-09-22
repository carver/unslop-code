"""Applying one annotation edit to a vault on disk.

Annotations only exist in the native catalog version, so an edit on a version 1
or 2 vault migrates the whole catalog first, by the same rules as the ``migrate``
command, and then saves the migration and the annotation together: the
``catalog.bak`` left behind holds the catalog as it was before both changes.

The category in the request is the one the entry is browsed under *before* the
migration, so a version 1 entry is addressed as ``entries`` and the page the
edit redirects to is the native ``episodes`` it has moved to.
"""

from http import HTTPStatus
from urllib.parse import urlencode

from . import annotations, catalog, detail, versions, viewer
from .annotations import AnnotationError


def apply_edit(name, category, entry_id, edit, body):
    """Run one annotation ``edit`` of :mod:`vault.annotations` and return where to redirect.

    Nothing is written until the edit has been applied to the loaded catalog, so
    a refused request leaves the vault exactly as it was.
    """
    fields = annotations.payload(body)
    document = catalog.read_document(name)
    native = viewer.native_category(versions.view(document, name), category)
    if native is None:
        raise AnnotationError(
            HTTPStatus.NOT_FOUND, f"vault '{name}' is not browsed under '{category}'"
        )
    migrated = versions.to_current(document, name)[0]
    entry = detail.find_entry(migrated[native], entry_id)
    if entry is None:
        raise AnnotationError(HTTPStatus.NOT_FOUND, f"'{category}' holds no entry '{entry_id}'")
    created = edit(entry, fields)
    catalog.save(name, migrated)
    return _entry_location(name, native, entry_id, created)


def _entry_location(name, category, entry_id, created):
    """Entry page an applied edit sends the browser to, opened at a new annotation."""
    path = viewer.entry_path(name, category, entry_id)
    if created is None:
        return path
    return f"{path}?{urlencode({viewer.TIMECODE_PARAM: created['timecode']})}"
