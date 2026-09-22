"""User-managed annotations of a catalog entry.

An annotation marks one moment of an entry's media: a ``timecode`` in whole
seconds, a ``title`` and an optional ``body``. An entry keeps them in its
``annotations`` list in creation order, each under an id unique within that
entry.

The edits here work on one already-loaded entry and never touch the disk; the
vault-level flow, including the migration a legacy catalog needs first, lives in
:mod:`vault.edits`. A request the rules refuse raises an :class:`AnnotationError`
carrying the status the viewer answers with, so nothing is written on the way.
"""

import json
import re
from functools import reduce
from http import HTTPStatus
from itertools import count

from .catalog import ANNOTATIONS_FIELD

#: Fields a patch request may replace, leaving the ones it omits as they are.
EDITABLE_FIELDS = ("title", "body")
#: ``SS``, ``MM:SS`` or ``HH:MM:SS``, each component a non-negative integer.
TIMECODE_PATTERN = re.compile(r"\d+(?::\d+){0,2}")
#: Factor between two neighbouring timecode components.
COMPONENT_FACTOR = 60


class AnnotationError(Exception):
    """An annotation request refused with a status of its own and a reason to show."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def payload(body):
    """Read a request body as the JSON object an annotation request carries."""
    try:
        fields = json.loads(body)
    except ValueError as error:
        raise AnnotationError(
            HTTPStatus.BAD_REQUEST, f"the request body is not valid JSON: {error}"
        ) from error
    if not isinstance(fields, dict):
        raise AnnotationError(HTTPStatus.BAD_REQUEST, "the request body is not a JSON object")
    return fields


def create(entry, fields):
    """Append the annotation ``fields`` describes and return it, so its page can seek to it."""
    existing = entry.setdefault(ANNOTATIONS_FIELD, [])
    annotation = {
        "id": _unused_id(existing),
        "timecode": parse_timecode(_required(fields, "timecode")),
        "title": _required(fields, "title"),
        "body": fields.get("body"),
    }
    existing.append(annotation)
    return annotation


def update(entry, fields):
    """Replace the title, the body or both of the annotation ``fields`` names."""
    annotation = _named(entry, fields)
    replaced = {field: fields[field] for field in EDITABLE_FIELDS if field in fields}
    if not replaced:
        raise AnnotationError(
            HTTPStatus.BAD_REQUEST, "an annotation update needs a 'title' or a 'body'"
        )
    annotation.update(replaced)


def delete(entry, fields):
    """Drop the annotation ``fields`` names, leaving the others in their order."""
    entry[ANNOTATIONS_FIELD].remove(_named(entry, fields))


def parse_timecode(text):
    """Whole seconds the timecode ``text`` names, as ``SS``, ``MM:SS`` or ``HH:MM:SS``.

    Components carry no clock bounds and may have leading zeros, so ``"90:00"``
    reads as ninety minutes.
    """
    if not TIMECODE_PATTERN.fullmatch(text):
        raise AnnotationError(
            HTTPStatus.BAD_REQUEST, f"'{text}' is not an SS, MM:SS or HH:MM:SS timecode"
        )
    return reduce(lambda seconds, part: seconds * COMPONENT_FACTOR + int(part), text.split(":"), 0)


def format_timecode(seconds):
    """Render whole seconds as ``M:SS``, or as ``H:MM:SS`` once it passes an hour."""
    hours, within_hour = divmod(seconds, COMPONENT_FACTOR**2)
    minutes, second = divmod(within_hour, COMPONENT_FACTOR)
    return f"{hours}:{minutes:02d}:{second:02d}" if hours else f"{minutes}:{second:02d}"


def stored(entry):
    """The annotations of an entry, in stored order; a legacy entry has none."""
    return entry.get(ANNOTATIONS_FIELD, [])


def _named(entry, fields):
    """The annotation of ``entry`` the required ``id`` field names."""
    annotation_id = _required(fields, "id")
    found = next((item for item in stored(entry) if item["id"] == annotation_id), None)
    if found is None:
        raise AnnotationError(
            HTTPStatus.NOT_FOUND, f"this entry has no annotation '{annotation_id}'"
        )
    return found


def _required(fields, field):
    """The text a required request field carries, naming it when it is absent."""
    value = fields.get(field)
    if not isinstance(value, str):
        raise AnnotationError(
            HTTPStatus.BAD_REQUEST, f"the annotation field '{field}' is required"
        )
    return value


def _unused_id(annotations):
    """Smallest positive integer no annotation of this entry uses, as text."""
    taken = {annotation["id"] for annotation in annotations}
    return next(candidate for candidate in map(str, count(1)) if candidate not in taken)
