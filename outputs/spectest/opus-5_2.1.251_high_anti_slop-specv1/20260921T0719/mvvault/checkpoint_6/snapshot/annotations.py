"""The timecoded notes an entry carries, and the changes a visitor makes to them.

An annotation marks one moment of the media an entry stands for: a whole
number of seconds, a title and, when the visitor wrote one, a body.  They are
the one part of a vault the viewer writes, and they are kept in the order they
were created, under identifiers unique inside the entry that holds them.

Only version 3 entries have the field they live in, so reading the annotations
of a legacy entry answers none; :mod:`editing` upgrades such a vault before a
change is applied to it.
"""

import re
import uuid
from http import HTTPStatus
from typing import Any, Optional

from catalogs import Entry
from errors import RequestError

#: Entry field the annotations of an entry are stored under.
FIELD = "annotations"

#: A timecode is one to three non-negative integers: SS, MM:SS or HH:MM:SS.
TIMECODE = re.compile(r"[0-9]+(?::[0-9]+){0,2}")

#: What each component of a timecode is worth in units of the one on its right.
COMPONENT = 60

Annotation = dict[str, Any]
Request = dict[str, Any]


def of(entry: Entry) -> list[Annotation]:
    """The annotations of an entry, in the order they were created."""
    return entry.get(FIELD, [])


def create(entry: Entry, request: Request) -> int:
    """Add an annotation to ``entry``, and answer the second it marks."""
    title = _text(request, "title")
    timecode = parse_timecode(_text(request, "timecode"))
    entry.setdefault(FIELD, []).append(
        {"id": uuid.uuid4().hex, "timecode": timecode, "title": title, "body": _body(request)}
    )
    return timecode


def update(entry: Entry, request: Request) -> None:
    """Replace the title and the body the request carries, and nothing else.

    A field the request leaves out is a field the visitor did not touch, so
    the annotation keeps the value it was stored with.
    """
    annotation = _targeted(entry, request)
    if "title" in request:
        annotation["title"] = _text(request, "title")
    if "body" in request:
        annotation["body"] = _body(request)


def remove(entry: Entry, request: Request) -> None:
    """Drop the annotation the request names from ``entry``."""
    of(entry).remove(_targeted(entry, request))


def parse_timecode(text: str) -> int:
    """Read ``SS``, ``MM:SS`` or ``HH:MM:SS`` text as whole seconds.

    Components are non-negative integers and may carry leading zeros; they are
    not held to the bounds of a clock, so ``"90:00"`` is the ninety minutes it
    reads as rather than an error.
    """
    if not TIMECODE.fullmatch(text):
        raise RequestError(
            HTTPStatus.BAD_REQUEST,
            f"'{text}' is not a SS, MM:SS or HH:MM:SS timecode",
        )
    seconds = 0
    for component in text.split(":"):
        seconds = seconds * COMPONENT + int(component)
    return seconds


def _targeted(entry: Entry, request: Request) -> Annotation:
    """The annotation of ``entry`` the request names by identifier."""
    identifier = _text(request, "id")
    found = next((note for note in of(entry) if note["id"] == identifier), None)
    if found is None:
        raise RequestError(
            HTTPStatus.NOT_FOUND,
            f"No annotation '{identifier}' on entry '{entry['id']}'",
        )
    return found


def _body(request: Request) -> Optional[str]:
    """The body of an annotation, which the request writes as text or as null."""
    body = request.get("body")
    if body is not None and not isinstance(body, str):
        raise RequestError(HTTPStatus.BAD_REQUEST, "An annotation body is text or null")
    return body


def _text(request: Request, field: str) -> str:
    """One field the request must carry as text."""
    value = request.get(field)
    if not isinstance(value, str):
        raise RequestError(
            HTTPStatus.BAD_REQUEST, f"An annotation request needs a '{field}' field"
        )
    return value
