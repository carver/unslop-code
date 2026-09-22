"""User-managed annotations held on a catalog entry.

An annotation is a titled mark at a whole-second offset into an entry's media,
with an optional note. Entries keep them in an `annotations` list in creation
order, which only the version 3 catalog shape defines.

The functions here work on that list alone: reading a request body, applying
the change and reporting what went wrong in terms an HTTP response can carry.
"""

import re
from http import HTTPStatus
from uuid import uuid4

from mvaultlib.errors import MvaultError

#: `SS`, `MM:SS` or `HH:MM:SS`, each component a non-negative decimal integer.
TIMECODE_PATTERN = re.compile(r"[0-9]+(?::[0-9]+){0,2}")

#: Seconds per timecode component, least significant first.
COMPONENT_SECONDS = (1, 60, 3600)


class AnnotationError(MvaultError):
    """An annotation request the viewer answers with a specific HTTP status."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def timecode_seconds(text):
    """Whole seconds meant by a timecode, or None when the text is not one.

    Components carry no conventional clock bounds, so `"90:00"` is an hour and
    a half rather than an error, and leading zeros are insignificant.
    """
    if not isinstance(text, str) or not TIMECODE_PATTERN.fullmatch(text):
        return None
    components = [int(part) for part in reversed(text.split(":"))]
    return sum(value * unit for value, unit in zip(components, COMPONENT_SECONDS))


def create_annotation(annotations, payload):
    """Append one annotation from a create body and return its timecode."""
    title = _text(_required(payload, "title"), "title")
    timecode = timecode_seconds(_required(payload, "timecode"))
    if timecode is None:
        raise AnnotationError(
            HTTPStatus.BAD_REQUEST,
            f"invalid 'timecode' format {payload['timecode']!r}: expected SS, MM:SS or HH:MM:SS",
        )
    annotations.append(
        {
            "id": uuid4().hex,
            "timecode": timecode,
            "title": title,
            "body": _optional_text(payload.get("body"), "body"),
        }
    )
    return timecode


def update_annotation(annotations, payload):
    """Replace the fields an update body names, leaving omitted ones alone."""
    annotation = _located(annotations, payload)
    changes = {
        field: validate(payload[field], field)
        for field, validate in REPLACEABLE_FIELDS.items()
        if field in payload
    }
    if not changes:
        raise AnnotationError(HTTPStatus.BAD_REQUEST, "update requires 'title' or 'body'")
    annotation.update(changes)


def delete_annotation(annotations, payload):
    """Remove the annotation a delete body names."""
    annotations.remove(_located(annotations, payload))


def _located(annotations, payload):
    """The annotation the body's `id` names inside this entry."""
    annotation_id = _text(_required(payload, "id"), "id")
    found = [note for note in annotations if note.get("id") == annotation_id]
    if not found:
        raise AnnotationError(HTTPStatus.NOT_FOUND, f"no annotation '{annotation_id}' on this entry")
    return found[0]


def _required(payload, field):
    """The value of a field the request body must carry."""
    value = payload.get(field)
    if value is None:
        raise AnnotationError(HTTPStatus.BAD_REQUEST, f"missing required field '{field}'")
    return value


def _text(value, field):
    """A field that has to be a string, stored exactly as it arrives."""
    if not isinstance(value, str):
        raise AnnotationError(HTTPStatus.BAD_REQUEST, f"field '{field}' must be a string")
    return value


def _optional_text(value, field):
    """A field that has to be a string, or `null` to mean no text at all."""
    return None if value is None else _text(value, field)


#: The fields an update may replace, and how each validates its new value.
REPLACEABLE_FIELDS = {"title": _text, "body": _optional_text}
