"""User-managed annotations: the timecode grammar and the edits a request makes.

Everything here works on one already-loaded v3 entry and its `annotations`
list. Who loaded that entry, and whether the catalog had to be migrated to have
the field at all, belongs to `mutations`. A request that cannot be satisfied
raises `AnnotationError`, whose `status` is the HTTP status to answer with, so
the routing layer never classifies a failure itself.
"""

import json
import re
from itertools import count

from .history import is_text

#: Grammar of a `timecode`: one to three `:`-separated runs of decimal digits.
#: Clock bounds are deliberately absent -- `"90:00"` is a valid `MM:SS` value.
TIMECODE_PATTERN = re.compile(r"[0-9]+(?::[0-9]+){0,2}")

#: What one timecode component is worth, least significant component first.
COMPONENT_SECONDS = (1, 60, 3600)

#: Shape of a generated annotation id; the number is the first one still free.
ID_TEMPLATE = "a{}"


class AnnotationError(Exception):
    """A rejected annotation request, carrying the status to answer with."""

    status = 400


class AnnotationNotFound(AnnotationError):
    """Nothing to annotate: no such entry, or no such annotation inside it."""

    status = 404


def _is_optional_text(value):
    """`body` is the one annotation field that may also be `null`."""
    return value is None or is_text(value)


#: The fields a request may write, what each accepts, and how to say so.
FIELD_TYPES = {
    "title": (is_text, "a string"),
    "body": (_is_optional_text, "a string or null"),
}


def timecode_seconds(text):
    """Whole seconds a `SS`, `MM:SS` or `HH:MM:SS` timecode names.

    Returns None for anything outside the grammar, including a value that is
    not text at all, so a caller that merely reads a query can ignore it.
    """
    if not is_text(text) or not TIMECODE_PATTERN.fullmatch(text):
        return None
    components = [int(part) for part in reversed(text.split(":"))]
    return sum(value * unit for value, unit in zip(components, COMPONENT_SECONDS))


def parse_timecode(text):
    """The seconds a timecode names, refusing anything outside the grammar."""
    seconds = timecode_seconds(text)
    if seconds is None:
        raise AnnotationError(f"timecode {text!r} is not SS, MM:SS or HH:MM:SS")
    return seconds


def clock_text(seconds):
    """Whole seconds as `M:SS`, or `H:MM:SS` once there is an hour to show."""
    hours, rest = divmod(seconds, 3600)
    minutes, remainder = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remainder:02d}"
    return f"{minutes}:{remainder:02d}"


def request_fields(body):
    """The JSON object an annotation request carries."""
    try:
        fields = json.loads(body)
    except ValueError as error:
        raise AnnotationError(f"request body is not valid JSON: {error}") from error
    if not isinstance(fields, dict):
        raise AnnotationError("request body is not a JSON object")
    return fields


def create(entry, fields):
    """Append an annotation to `entry` and return the second it points at."""
    _required(fields, "title")
    seconds = parse_timecode(_required(fields, "timecode"))
    annotations = entry.setdefault("annotations", [])
    annotations.append(
        {
            "id": _unused_id(annotations),
            "timecode": seconds,
            "title": _written(fields, "title"),
            "body": _written(fields, "body") if "body" in fields else None,
        }
    )
    return seconds


def update(entry, fields):
    """Replace the `title` and `body` an update names, leaving the rest alone.

    Fields the request omits keep their stored value, and a field it does not
    own -- `id`, `timecode` -- is left alone even when the body carries one.
    """
    annotation = _named(entry, fields)
    replacements = {name: _written(fields, name) for name in FIELD_TYPES if name in fields}
    if not replacements:
        raise AnnotationError("annotation update names no 'title' or 'body' to change")
    annotation.update(replacements)


def delete(entry, fields):
    """Remove the annotation a delete names."""
    entry["annotations"].remove(_named(entry, fields))


def _required(fields, name):
    """One field a request must carry, whatever its value."""
    if name not in fields:
        raise AnnotationError(f"annotation request is missing the {name!r} field")
    return fields[name]


def _written(fields, name):
    """One writable field's value, checked against the type that field accepts."""
    accepts, expected = FIELD_TYPES[name]
    value = fields[name]
    if not accepts(value):
        raise AnnotationError(f"annotation {name!r} must be {expected}")
    return value


def _named(entry, fields):
    """The annotation an update or delete names by `id`."""
    annotation_id = _required(fields, "id")
    for annotation in entry.get("annotations", []):
        if annotation.get("id") == annotation_id:
            return annotation
    raise AnnotationNotFound(f"This entry holds no annotation {annotation_id!r}.")


def _unused_id(annotations):
    """The first `a<n>` the entry's list is not already using."""
    taken = {annotation.get("id") for annotation in annotations}
    for number in count(1):
        candidate = ID_TEMPLATE.format(number)
        if candidate not in taken:
            return candidate
