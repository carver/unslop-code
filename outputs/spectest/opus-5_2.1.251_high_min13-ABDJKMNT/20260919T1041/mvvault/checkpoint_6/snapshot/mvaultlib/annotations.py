"""User annotations on one entry: the `timecode` grammar and the list operations.

Each operation works on the `annotations` list of a single native (version 3)
entry and raises :class:`AnnotationError` for whatever the request itself got
wrong, so the viewer can answer with a status and a message instead of failing.
"""

import re
from itertools import count

from .errors import MvaultError

BAD_REQUEST, NOT_FOUND = 400, 404

#: A timecode is one to three `:`-separated digit runs: `SS`, `MM:SS`, `HH:MM:SS`.
TIMECODE_PATTERN = re.compile(r"\d+(?::\d+){0,2}\Z")

#: What one component is worth in seconds, by how many components were written.
COMPONENT_SECONDS = {1: (1,), 2: (60, 1), 3: (3600, 60, 1)}


class AnnotationError(MvaultError):
    """A rejected annotation request, carrying the status it is answered with."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def create(entry, payload):
    """Append the annotation `payload` describes to `entry`, and return it."""
    annotation = {
        "id": _free_id(entry),
        "timecode": parse_timecode(_required_text(payload, "timecode")),
        "title": _required_text(payload, "title"),
        "body": _checked_body(payload.get("body"), "body"),
    }
    entry.setdefault("annotations", []).append(annotation)
    return annotation


def update(entry, payload):
    """Replace the fields `payload` carries on one annotation of `entry`."""
    annotation_id = _required_text(payload, "id")
    replacements = {field: check(payload[field], field) for field, check in UPDATABLE.items() if field in payload}
    if not replacements:
        raise AnnotationError(BAD_REQUEST, "An annotation update needs a 'title' or a 'body'.")

    annotation = _found(entry, annotation_id)
    annotation.update(replacements)
    return annotation


def delete(entry, payload):
    """Remove the annotation `payload` names from `entry`, and return it."""
    annotation = _found(entry, _required_text(payload, "id"))
    entry["annotations"].remove(annotation)
    return annotation


def parse_timecode(text):
    """The whole seconds `text` names in `SS`, `MM:SS` or `HH:MM:SS` form.

    Components are non-negative integers that may carry leading zeros and are
    not held to conventional clock bounds, so `"90:00"` is 5400 seconds.
    """
    if not TIMECODE_PATTERN.match(text):
        raise AnnotationError(BAD_REQUEST, f"Invalid timecode format: '{text}'.")

    components = [int(part) for part in text.split(":")]
    return sum(value * weight for value, weight in zip(components, COMPONENT_SECONDS[len(components)]))


def seek_seconds(text):
    """The position a `?timecode=` query value asks for, or `None` when it names none."""
    try:
        return parse_timecode(text) if text else None
    except AnnotationError:
        return None


def format_timecode(seconds):
    """Clock text for a stored timecode: `M:SS`, or `H:MM:SS` from an hour on."""
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{remainder:02d}" if hours else f"{minutes}:{remainder:02d}"


def _found(entry, annotation_id):
    """The annotation `annotation_id` names inside `entry`, which has to be there."""
    stored = entry.get("annotations", [])
    annotation = next((one for one in stored if one["id"] == annotation_id), None)
    if annotation is None:
        raise AnnotationError(NOT_FOUND, f"This entry has no annotation '{annotation_id}'.")
    return annotation


def _free_id(entry):
    """The smallest unused counting number as text, unique inside this entry."""
    taken = {one["id"] for one in entry.get("annotations", [])}
    return next(candidate for candidate in map(str, count(1)) if candidate not in taken)


def _required_text(payload, field):
    """A string field the request had to carry."""
    if payload.get(field) is None:
        raise AnnotationError(BAD_REQUEST, f"The annotation field '{field}' is required.")
    return _checked_text(payload[field], field)


def _checked_text(value, field):
    """A field the annotation stores as a string."""
    if not isinstance(value, str):
        raise AnnotationError(BAD_REQUEST, f"The annotation field '{field}' must be a string.")
    return value


def _checked_body(value, field):
    """The `body` field, which is stored as written or as `null`."""
    return None if value is None else _checked_text(value, field)


#: The fields an update may replace, each with the check its value has to pass.
UPDATABLE = {"title": _checked_text, "body": _checked_body}
