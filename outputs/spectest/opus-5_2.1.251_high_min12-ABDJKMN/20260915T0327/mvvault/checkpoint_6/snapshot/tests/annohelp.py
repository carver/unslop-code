"""Helpers for the annotation spec tests.

The annotation methods are JSON-bodied requests against the entry detail
route; the helpers here build those URLs, read the stored `annotations`
list back out of `catalog.json`, and pull annotation ids out of a response
so a create can be chained into an update or a delete.
"""
import json
import os
import urllib.parse

from conftest import read_catalog

REDIRECTS = (301, 302, 303, 307, 308)


def entry_path(name, category, eid):
    """The entry detail route every annotation method targets."""
    return "/catalog/%s/%s/%s" % (
        urllib.parse.quote(name, safe=""),
        urllib.parse.quote(category, safe=""),
        urllib.parse.quote(eid, safe=""),
    )


def stored_entry(tmp_path, eid, category="episodes", name="vault"):
    """One entry as it currently sits in `catalog.json`."""
    catalog = read_catalog(tmp_path, name)
    for item in catalog.get(category, []):
        if item.get("id") == eid:
            return item
    return None


def stored_annotations(tmp_path, eid, category="episodes", name="vault"):
    """The stored `annotations` list of one entry, in catalog order."""
    item = stored_entry(tmp_path, eid, category, name)
    assert item is not None, "no entry %r in %r" % (eid, category)
    return item.get("annotations")


def annotation_ids(tmp_path, eid, category="episodes", name="vault"):
    return [item["id"] for item in stored_annotations(tmp_path, eid, category,
                                                      name)]


def by_id(tmp_path, eid, aid, category="episodes", name="vault"):
    for item in stored_annotations(tmp_path, eid, category, name):
        if item.get("id") == aid:
            return item
    return None


def create(client, tmp_path, name, category, eid, **fields):
    """`POST` one annotation and return `(response, stored annotation)`."""
    before = set()
    stored = stored_annotations(tmp_path, eid, category, name)
    if stored:
        before = {item.get("id") for item in stored}
    response = client.create(entry_path(name, category, eid), fields)
    return response, _fresh(tmp_path, eid, category, name, before)


def _fresh(tmp_path, eid, category, name, before):
    """The annotation that appeared since `before`, if the create landed."""
    try:
        stored = stored_annotations(tmp_path, eid, category, name)
    except AssertionError:
        # A v1 vault moves its entry to `episodes` when it auto-migrates.
        stored = stored_annotations(tmp_path, eid, "episodes", name)
    for item in stored or []:
        if item.get("id") not in before:
            return item
    return None


def location_path(response):
    """The path part of a redirect `Location`, without its query string."""
    location = response.location or ""
    return urllib.parse.urlsplit(location).path


def location_query(response):
    """The redirect `Location` query as a `{name: [value]}` mapping."""
    location = response.location or ""
    return urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)


def timecode_param(response):
    """The single `timecode` query value of a create redirect, or None."""
    values = location_query(response).get("timecode") or []
    return values[0] if values else None


def has_traceback(text):
    """Whether an HTTP body leaked a Python traceback."""
    lowered = text.lower()
    return "traceback (most recent call last)" in lowered or (
        "  file \"" in lowered and "line " in lowered
    )


def catalog_bytes(tmp_path, name="vault"):
    with open(os.path.join(str(tmp_path), name, "catalog.json"), "rb") as fh:
        return fh.read()


def backup_json(tmp_path, name="vault"):
    with open(os.path.join(str(tmp_path), name, "catalog.bak")) as fh:
        return json.load(fh)


def visible_text(html_text):
    """The page with tags stripped, so rendering can be asserted loosely."""
    import html as html_mod
    import re

    without = re.sub(r"<script\b.*?</script>", " ", html_text,
                     flags=re.S | re.I)
    without = re.sub(r"<[^>]+>", " ", without)
    return html_mod.unescape(without)
