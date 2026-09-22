"""The annotations a reader keeps on one entry.

An annotation is a note at a point in an entry's media: a timecode in whole
seconds, a title and an optional body. An entry keeps its annotations in an
``annotations`` list, in the order they were created.

Only version 3 entries carry that list, so writing an annotation to an older
vault migrates the whole catalog first and stores both changes with one write.
"""

import re
from dataclasses import dataclass
from http import HTTPStatus
from itertools import count
from pathlib import Path

from .catalog import load_catalog, save_catalog
from .schema import ANNOTATIONS_FIELD

TIMECODE_PATTERN = re.compile(r"\d+(?::\d+){0,2}")
TIMECODE_GRAMMAR = "SS, MM:SS or HH:MM:SS"


class AnnotationError(Exception):
    """Raised when an annotation request cannot be applied as it was asked.

    The status is what the viewer answers with: a request that does not state
    a usable annotation is a bad one, and a request naming an annotation the
    entry does not hold asks for something that is not there.
    """

    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Annotation:
    """One stored annotation, as a page states it."""

    annotation_id: str
    timecode: int
    title: str
    body: str | None


def parse_timecode(text: str) -> int:
    """Read ``SS``, ``MM:SS`` or ``HH:MM:SS`` as whole seconds.

    Every component is a non-negative integer and may carry leading zeros.
    Clock bounds are not part of the grammar, so ``90:00`` is five thousand
    four hundred seconds rather than an error.
    """
    cleaned = text.strip()
    if not TIMECODE_PATTERN.fullmatch(cleaned):
        raise AnnotationError(f"'{text}' is not a timecode; expected {TIMECODE_GRAMMAR}")
    seconds = 0
    for component in cleaned.split(":"):
        seconds = seconds * 60 + int(component)
    return seconds


def format_timecode(seconds: int) -> str:
    """Render whole seconds the way a player's own clock reads them."""
    minutes, second = divmod(seconds, 60)
    hour, minute = divmod(minutes, 60)
    return f"{hour}:{minute:02}:{second:02}" if hour else f"{minute}:{second:02}"


def stored_annotations(entry: dict) -> tuple[Annotation, ...]:
    """The annotations of one entry, in creation order.

    Versions 1 and 2 have no ``annotations`` field, so their entries read as
    carrying none until an annotation migrates the vault.
    """
    return tuple(
        Annotation(note["id"], note["timecode"], note["title"], note.get("body"))
        for note in entry.get(ANNOTATIONS_FIELD, [])
    )


def apply_annotation(
    vault_dir: Path, category: str, entry_id: str, method: str, fields: dict
) -> int | None:
    """Apply one annotation request to a stored entry and store the catalog.

    ``category`` names the version 3 category the entry has ended up in, which
    is where a migrated version 1 entry is looked up rather than in the flat
    list it was stored in. A catalog from an older version is migrated as it is
    read and stored by the same write, so the backup that write leaves behind
    holds the catalog from before both the migration and the annotation.

    Returns the timecode a created annotation was placed at, which is what the
    viewer seeks to, and ``None`` for a request that changed a stored one.
    Anything the request gets wrong raises before a single byte is written.
    """
    catalog, _ = load_catalog(vault_dir)
    entry = next((one for one in catalog[category] if one["id"] == entry_id), None)
    if entry is None:
        raise AnnotationError(
            f"the {category} of '{vault_dir.name}' hold no entry '{entry_id}'",
            HTTPStatus.NOT_FOUND,
        )
    timecode = _MUTATIONS[method](entry, fields)
    save_catalog(vault_dir, catalog)
    return timecode


def _create(entry: dict, fields: dict) -> int:
    """Add an annotation to the end of an entry's list, returning its timecode."""
    title = _text(fields, "title")
    timecode = parse_timecode(_text(fields, "timecode"))
    annotations = entry.setdefault(ANNOTATIONS_FIELD, [])
    annotations.append(
        {
            "id": _unused_id(annotations),
            "timecode": timecode,
            "title": title,
            "body": _body(fields),
        }
    )
    return timecode


def _update(entry: dict, fields: dict) -> None:
    """Replace the title and body a request states, leaving out what it omits."""
    annotation = _named(entry, fields)
    if "title" in fields:
        annotation["title"] = _text(fields, "title")
    if "body" in fields:
        annotation["body"] = _body(fields)


def _delete(entry: dict, fields: dict) -> None:
    """Drop one annotation, leaving the rest in the order they were created in."""
    entry[ANNOTATIONS_FIELD].remove(_named(entry, fields))


_MUTATIONS = {"POST": _create, "PATCH": _update, "DELETE": _delete}


def _named(entry: dict, fields: dict) -> dict:
    """The stored annotation a request names, which the entry has to hold."""
    annotation_id = _text(fields, "id")
    stored = entry.get(ANNOTATIONS_FIELD, [])
    found = next((one for one in stored if one["id"] == annotation_id), None)
    if found is None:
        raise AnnotationError(
            f"this entry has no annotation '{annotation_id}'", HTTPStatus.NOT_FOUND
        )
    return found


def _unused_id(annotations: list) -> str:
    """An identifier no annotation of this entry carries, counting from the first."""
    taken = {annotation["id"] for annotation in annotations}
    return next(candidate for number in count(1) if (candidate := f"a{number}") not in taken)


def _text(fields: dict, name: str) -> str:
    """One text field a request has to state."""
    if name not in fields:
        raise AnnotationError(f"an annotation needs a '{name}'")
    value = fields[name]
    if not isinstance(value, str):
        raise AnnotationError(f"the '{name}' of an annotation is text")
    return value


def _body(fields: dict) -> str | None:
    """The body a request states, which is as often left out as given."""
    body = fields.get("body")
    if body is not None and not isinstance(body, str):
        raise AnnotationError("the 'body' of an annotation is text")
    return body
