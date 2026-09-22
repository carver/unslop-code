"""Annotation requests, which are the one thing the viewer writes.

Because ``annotations`` is a version 3 field, a request against a legacy vault
migrates the whole catalog first, by the rules the ``migrate`` command follows,
and stores the migration together with the annotation in a single write — so
the backup holds the vault as it was before both. A version 1 vault is asked
for under the category it has now, ``entries``, but its entries land in
``episodes``, which is where the browser is sent back to.
"""

import json
from collections import namedtuple

from .. import annotations, catalog, digest, versions
from ..source import CATEGORIES

#: What one applied request changed: the category the entry resides in now,
#: and the annotation that was created, if the request created one.
Applied = namedtuple("Applied", "category annotation")

V1_DESTINATION = CATEGORIES[0]


def apply(vault, requested, identifier, body, change):
    """Run ``change`` on one entry of ``vault`` and store the result.

    ``change`` takes the entry and the parsed request body and returns the
    annotation it created, if any. The catalog reaches it in the current
    version whatever it is stored in, so a change never has to know which one
    that was.
    """
    request = _parse(body)
    stored = catalog.read(vault)
    version = versions.detect(vault, stored)
    current = stored if version == versions.VERSION else versions.upgrade(vault, stored)
    category = _destination(version, requested)
    annotation = change(_find(current, category, identifier), request)
    catalog.save(vault, current)
    return Applied(category, annotation)


def _destination(version, requested):
    """The category the requested entry resides in once the catalog is current.

    The flat ``entries`` of a version 1 vault all become episodes; later
    versions already name the category the entry stays in. A name no version
    offers is passed through, and simply matches no entry.
    """
    if version == 1 and requested == digest.V1_CATEGORY:
        return V1_DESTINATION
    return requested


def _find(current, category, identifier):
    """The entry of ``category`` with this id, which the catalog has to hold."""
    found = next(
        (entry for entry in current.get(category, []) if entry["id"] == identifier), None
    )
    if found is None:
        raise annotations.NotFound(f"{category} holds no entry {identifier}")
    return found


def _parse(body):
    """The JSON object a request carries, refused if it is not one."""
    try:
        request = json.loads(body.decode("utf-8"))
    except ValueError as error:
        raise annotations.AnnotationError(f"the request body is not JSON: {error}") from error
    if not isinstance(request, dict):
        raise annotations.AnnotationError("the request body is not a JSON object")
    return request
