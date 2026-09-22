"""Writing an annotation into the vault the viewer is browsing.

Annotations are the one thing the viewer changes about a vault, and they live
in a field that only version 3 entries carry.  A change asked of a legacy
vault therefore upgrades the whole catalog first, exactly the way ``migrate``
would, and the upgrade and the annotation reach the disk in a single save: the
backup that save leaves behind holds the vault as it stood before either of
them, and a request that cannot be served writes nothing at all.

A request names its entry the way the stored version addresses it, so a
version 1 vault is annotated under ``entries`` and answers with the
``episodes`` the entry has moved to.
"""

import json
from http import HTTPStatus
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlencode

import catalogs
import migrations
import responses
import viewer
from catalogs import Catalog, Entry
from errors import MvaultError, RequestError
from responses import Response

#: Applies one requested change to an entry, answering the second the visitor
#: should be sent back to when the change marks one.
Change = Callable[[Entry, dict], Optional[int]]


def annotate(directory: Path, segments: list[str], body: str, change: Change) -> Response:
    """Answer one annotation request against ``<name>/<category>/<id>``.

    A vault the viewer cannot read is answered the way every other route
    answers it, and everything the request itself gets wrong is answered with
    the status that fits it.
    """
    name, category, identifier = segments
    vault = directory / name
    try:
        stored = catalogs.read(vault, name)
        version = migrations.version_of(stored, name)
    except MvaultError:
        return responses.missing(name)
    try:
        request = _request(body)
        catalog = _upgraded(stored, name)
        migrated = _category(version, category, name)
        seconds = change(_entry(catalog, migrated, identifier, name), request)
        catalogs.save(vault, catalog)
        return responses.redirect(_detail(name, migrated, identifier, seconds))
    except RequestError as refused:
        return responses.refusal(refused.status, str(refused))


def _request(body: str) -> dict:
    """Read the JSON object an annotation request carries."""
    try:
        request = json.loads(body)
    except ValueError as error:
        raise RequestError(
            HTTPStatus.BAD_REQUEST, f"Unreadable annotation request: {error}"
        ) from error
    if not isinstance(request, dict):
        raise RequestError(HTTPStatus.BAD_REQUEST, "An annotation request is a JSON object")
    return request


def _upgraded(stored: Catalog, name: str) -> Catalog:
    """The catalog in the version annotations need, upgrading it if it is not.

    Nothing is written here, so a catalog the upgrade cannot make sense of
    leaves the vault exactly as it was.
    """
    try:
        return migrations.upgrade(stored, name)
    except MvaultError as error:
        raise RequestError(
            HTTPStatus.INTERNAL_SERVER_ERROR, f"Cannot migrate vault '{name}': {error}"
        ) from error


def _category(version: int, category: str, name: str) -> str:
    """Where the entries the request addresses live once the catalog is upgraded.

    A category the stored version does not address holds nothing to annotate.
    """
    migrated = migrations.migrated_category(version, category)
    if migrated is None:
        raise RequestError(
            HTTPStatus.NOT_FOUND, f"Vault '{name}' keeps no '{category}' to annotate"
        )
    return migrated


def _entry(catalog: Catalog, category: str, identifier: str, name: str) -> Entry:
    """The upgraded entry an annotation request names."""
    found = next((entry for entry in catalog[category] if entry["id"] == identifier), None)
    if found is None:
        raise RequestError(
            HTTPStatus.NOT_FOUND, f"No entry '{identifier}' to annotate in vault '{name}'"
        )
    return found


def _detail(name: str, category: str, identifier: str, seconds: Optional[int]) -> str:
    """The detail page a served request sends the visitor on to.

    A change that marks a moment sends the visitor to it, so a new annotation
    opens the page with its player already there.
    """
    path = viewer.catalog_path(name, category, identifier)
    if seconds is None:
        return path
    return f"{path}?{urlencode({viewer.TIMECODE_QUERY: seconds})}"
