"""The annotations a viewer's user keeps on an entry.

An annotation is a titled note pinned to a timecode inside an entry's media,
kept in the entry's ``annotations`` list in creation order. That field arrived
with version 3, so a vault has to be in the current format before it can carry
any: a request against a legacy catalog migrates it first.
"""

import re
from uuid import uuid4

from .entries import ANNOTATIONS_FIELD

ID_FIELD = "id"
TIMECODE_FIELD = "timecode"
TITLE_FIELD = "title"
BODY_FIELD = "body"

#: ``SS``, ``MM:SS`` or ``HH:MM:SS``, each component a non-negative integer.
TIMECODE_PATTERN = re.compile(r"\d+(?::\d+){0,2}")
#: How much of the next component one component of a timecode is worth.
COMPONENT_SCALE = 60


class AnnotationError(Exception):
    """Raised for an annotation request an entry cannot be asked to carry out."""


class NotFound(Exception):
    """Raised when a request names an entry or an annotation that is not there."""


def _is_text(value):
    return isinstance(value, str)


def _is_optional_text(value):
    return value is None or _is_text(value)


FIELD_VALIDATORS = {
    ID_FIELD: _is_text,
    TIMECODE_FIELD: _is_text,
    TITLE_FIELD: _is_text,
    BODY_FIELD: _is_optional_text,
}


def read_timecode(text):
    """Whole seconds named by ``SS``, ``MM:SS`` or ``HH:MM:SS`` text.

    Components are non-negative integers that may carry leading zeros and need
    not respect the bounds of a clock, so ``"90:00"`` is ninety minutes rather
    than an error. Text that is no timecode at all reads as ``None``.
    """
    if not _is_text(text) or not TIMECODE_PATTERN.fullmatch(text):
        return None
    seconds = 0
    for component in text.split(":"):
        seconds = seconds * COMPONENT_SCALE + int(component)
    return seconds


def stored(entry):
    """The annotations of ``entry``, which a legacy entry carries none of."""
    return entry.get(ANNOTATIONS_FIELD, [])


def create(entry, request):
    """Append the annotation ``request`` describes to ``entry`` and return it.

    A request without a ``body`` makes one that says nothing beyond its title.
    """
    title = _field(request, TITLE_FIELD)
    seconds = read_timecode(_field(request, TIMECODE_FIELD))
    if seconds is None:
        raise AnnotationError(f"the {TIMECODE_FIELD} field is not SS, MM:SS or HH:MM:SS")
    annotation = {
        ID_FIELD: uuid4().hex,
        TIMECODE_FIELD: seconds,
        TITLE_FIELD: title,
        BODY_FIELD: _field(request, BODY_FIELD),
    }
    entry.setdefault(ANNOTATIONS_FIELD, []).append(annotation)
    return annotation


def update(entry, request):
    """Replace the title, the body, or both of one annotation of ``entry``.

    A field the request leaves out keeps the value the annotation stores.
    """
    annotation = _find(entry, _field(request, ID_FIELD))
    for name in (TITLE_FIELD, BODY_FIELD):
        if name in request:
            annotation[name] = _field(request, name)
    return annotation


def delete(entry, request):
    """Drop one annotation of ``entry``, leaving the order of the rest alone."""
    stored(entry).remove(_find(entry, _field(request, ID_FIELD)))


def _find(entry, identifier):
    """The annotation of ``entry`` with this id, which it has to hold one of."""
    found = next((found for found in stored(entry) if found[ID_FIELD] == identifier), None)
    if found is None:
        raise NotFound(f"this entry holds no annotation {identifier}")
    return found


def _field(request, name):
    """The value ``request`` holds for ``name``, refused if it is the wrong type.

    A field the request leaves out reads as ``None``: that is what an optional
    ``body`` defaults to, and what a required field is refused for.
    """
    value = request.get(name)
    if not FIELD_VALIDATORS[name](value):
        raise AnnotationError(f"the {name} field is missing or is not text")
    return value
