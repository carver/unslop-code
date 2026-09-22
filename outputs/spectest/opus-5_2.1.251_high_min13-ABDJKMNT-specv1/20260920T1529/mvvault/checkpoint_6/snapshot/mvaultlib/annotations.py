"""User-managed annotations on an entry: the `timecode` grammar, the records the
catalog stores, and the write that persists one mutation.

An annotation needs the version 3 entry shape, so every mutation works on the
catalog `load_catalog` upgrades in memory and persists the result in a single
write: a legacy vault is migrated and annotated by one `save_catalog` call, whose
backup therefore holds the state from before both changes. A refused mutation
writes nothing at all, so the catalog it was aimed at is left as it was.
"""

import json
import re
from http import HTTPStatus
from itertools import count

from .catalog import load_catalog, save_catalog
from .errors import AnnotationError
from .vault import migrated
from .versions import VERSION
from .viewer import storage_category

ANNOTATIONS_FIELD = "annotations"

#: `SS`, `MM:SS` or `HH:MM:SS`: one to three non-negative integer components.
TIMECODE = re.compile(r"[0-9]+(?::[0-9]+){0,2}")
COMPONENT_SECONDS = 60

#: The fields an update may replace; a request has to carry at least one.
EDITABLE_FIELDS = ("title", "body")


def annotate(vault, category, entry_id, method, request):
    """Apply one annotation mutation to `vault`, persisting it in a single write.

    Returns the `(category, timecode)` the caller redirects to: the category the
    entry lives in once the catalog is version 3, and the whole seconds of a
    created annotation, or `None` for a mutation that creates none.
    """
    catalog, version = load_catalog(vault)
    stored = storage_category(category, version)
    if stored is None:
        raise AnnotationError(HTTPStatus.NOT_FOUND, f"this vault has no '{category}' category")

    entry = next((item for item in catalog[stored] if item["id"] == entry_id), None)
    if entry is None:
        raise AnnotationError(HTTPStatus.NOT_FOUND, f"that category holds no entry '{entry_id}'")

    timecode = MUTATIONS[method](entry, request)
    save_catalog(vault, catalog if version == VERSION else migrated(catalog))
    return stored, timecode


def create(entry, request):
    """Append one annotation to the entry; returns its whole seconds."""
    timecode = parse_timecode(required(request, "timecode"))
    title = required(request, "title")

    annotations = entry.setdefault(ANNOTATIONS_FIELD, [])
    annotations.append(
        {
            "id": next_id(annotations),
            "timecode": timecode,
            "title": title,
            "body": request.get("body"),
        }
    )
    return timecode


def update(entry, request):
    """Replace the fields the request carries, leaving the omitted ones alone."""
    annotation = named(entry, request)
    replacements = {field: request[field] for field in EDITABLE_FIELDS if field in request}
    if not replacements:
        raise AnnotationError(
            HTTPStatus.BAD_REQUEST, "an annotation update must carry 'title' or 'body'"
        )
    annotation.update(replacements)


def delete(entry, request):
    """Drop the annotation the request names."""
    entry[ANNOTATIONS_FIELD].remove(named(entry, request))


MUTATIONS = {"POST": create, "PATCH": update, "DELETE": delete}


def named(entry, request):
    """The annotation this entry files under the request's `id`."""
    annotation_id = required(request, "id")
    stored = entry.get(ANNOTATIONS_FIELD, [])
    found = next((item for item in stored if item["id"] == annotation_id), None)
    if found is None:
        raise AnnotationError(
            HTTPStatus.NOT_FOUND, f"this entry has no annotation '{annotation_id}'"
        )
    return found


def required(request, field):
    """One string field an annotation request must carry."""
    value = request.get(field)
    if not isinstance(value, str):
        raise AnnotationError(
            HTTPStatus.BAD_REQUEST, f"the annotation request is missing '{field}'"
        )
    return value


def next_id(annotations):
    """The first `a<n>` identifier no annotation of this entry holds."""
    taken = {annotation["id"] for annotation in annotations}
    return next(f"a{number}" for number in count(1) if f"a{number}" not in taken)


def parse_timecode(text):
    """`SS`, `MM:SS` or `HH:MM:SS` as whole seconds.

    Components are non-negative integers, leading zeros included, and are not
    held to conventional clock bounds, so `"90:00"` is 5400 seconds. Anything
    outside the grammar is a format error.
    """
    if not TIMECODE.fullmatch(text):
        raise AnnotationError(
            HTTPStatus.BAD_REQUEST,
            f"the annotation timecode {text!r} is not in SS, MM:SS or HH:MM:SS format",
        )

    seconds = 0
    for component in text.split(":"):
        seconds = seconds * COMPONENT_SECONDS + int(component)
    return seconds


def annotation_request(body):
    """The JSON object an annotation request carries as its body."""
    try:
        request = json.loads(body)
    except ValueError as exc:
        raise AnnotationError(
            HTTPStatus.BAD_REQUEST, f"the annotation request body is not valid JSON: {exc}"
        ) from exc

    if not isinstance(request, dict):
        raise AnnotationError(
            HTTPStatus.BAD_REQUEST, "the annotation request body is not a JSON object"
        )
    return request
