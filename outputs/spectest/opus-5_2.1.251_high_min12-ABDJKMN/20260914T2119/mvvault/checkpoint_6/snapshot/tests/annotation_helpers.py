"""Helpers for the annotation spec tests.

Every mutation is a real HTTP request against a `mvault.py serve` subprocess;
every assertion about storage reads `catalog.json` back off disk.
"""
import json
import os
from urllib.parse import parse_qs, urlsplit

from conftest import read_json

JSON_HEADERS = {"Content-Type": "application/json"}


# --------------------------------------------------------------------------
# request helpers
# --------------------------------------------------------------------------
def detail_path(name="vault", category="episodes", entry_id="e1"):
    return "/catalog/%s/%s/%s" % (name, category, entry_id)


def mutate(server, method, payload=None, raw=None, name="vault",
           category="episodes", entry_id="e1", headers=None):
    """Send one annotation request; `raw` bypasses JSON encoding."""
    body = raw if raw is not None else json.dumps(payload or {})
    return server.request(method, detail_path(name, category, entry_id),
                          body=body,
                          headers=JSON_HEADERS if headers is None else headers)


_UNSET = object()


def create(server, title=_UNSET, timecode=_UNSET, body=_UNSET, **kwargs):
    """`POST` an annotation; omitted keyword = field absent from the JSON."""
    payload = {}
    if title is not _UNSET:
        payload["title"] = title
    if timecode is not _UNSET:
        payload["timecode"] = timecode
    if body is not _UNSET:
        payload["body"] = body
    return mutate(server, "POST", payload, **kwargs)


def update(server, id=_UNSET, title=_UNSET, body=_UNSET, **kwargs):
    payload = {}
    if id is not _UNSET:
        payload["id"] = id
    if title is not _UNSET:
        payload["title"] = title
    if body is not _UNSET:
        payload["body"] = body
    return mutate(server, "PATCH", payload, **kwargs)


def remove(server, id=_UNSET, **kwargs):
    payload = {} if id is _UNSET else {"id": id}
    return mutate(server, "DELETE", payload, **kwargs)


# --------------------------------------------------------------------------
# response helpers
# --------------------------------------------------------------------------
def redirect_path(response):
    """Path part of a redirect `Location`, with the query stripped."""
    assert response.is_redirect, response
    return urlsplit(response.location).path


def redirect_query(response):
    assert response.is_redirect, response
    return parse_qs(urlsplit(response.location).query)


def redirect_timecode(response):
    """The single `timecode` query value of a redirect, or None."""
    values = redirect_query(response).get("timecode")
    return values[0] if values else None


def assert_clean(response):
    """No raw exception or stack trace escapes into the response."""
    lowered = response.body.lower()
    for needle in ("traceback (most recent call last)", "  file \"",
                   "stack trace"):
        assert needle not in lowered, response.body


# --------------------------------------------------------------------------
# storage helpers
# --------------------------------------------------------------------------
def catalog_file(root, name="vault"):
    return os.path.join(str(root), name, "catalog.json")


def backup_file(root, name="vault"):
    return os.path.join(str(root), name, "catalog.bak")


def stored_catalog(root, name="vault"):
    return read_json(catalog_file(root, name))


def stored_backup(root, name="vault"):
    return read_json(backup_file(root, name))


def entry_of(catalog, category="episodes", entry_id="e1"):
    bucket = catalog.get(category)
    if not isinstance(bucket, list):
        return None
    for item in bucket:
        if isinstance(item, dict) and item.get("id") == entry_id:
            return item
    return None


def stored_annotations(root, name="vault", category="episodes",
                       entry_id="e1"):
    """The `annotations` value stored for one entry (may be missing/None)."""
    entry = entry_of(stored_catalog(root, name), category, entry_id)
    assert entry is not None, "entry %r not in %r" % (entry_id, category)
    return entry.get("annotations")


def annotation_titles(root, **kwargs):
    return [item.get("title") for item in stored_annotations(root, **kwargs)]


def only_annotation(root, **kwargs):
    stored = stored_annotations(root, **kwargs)
    assert isinstance(stored, list) and len(stored) == 1, stored
    return stored[0]


def created_id(server, root, title="Note", timecode="90", body=_UNSET,
               name="vault", category="episodes", entry_id="e1",
               stored_category=None):
    """Create one annotation and hand back its stored id."""
    response = create(server, title=title, timecode=timecode, body=body,
                      name=name, category=category, entry_id=entry_id)
    assert response.is_redirect, response
    stored = stored_annotations(root, name=name,
                                category=stored_category or category,
                                entry_id=entry_id)
    assert stored, "no annotation was stored"
    return stored[-1]["id"]
