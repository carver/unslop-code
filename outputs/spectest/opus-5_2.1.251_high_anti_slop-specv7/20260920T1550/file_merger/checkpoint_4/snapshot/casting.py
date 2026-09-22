"""Casting values into the declared types, and what a cast value renders as.

Every type in a schema — the primitives of :mod:`column_types` and the nested
types of :mod:`nested_types` — implements :class:`ValueType`, so a struct field
and a top level column are cast by the same call.  A value that does not fit
its type is not an exception but a decision: :meth:`CastContext.recover`
applies ``--on-type-error`` wherever the value sits, so a leaf deep inside an
array follows the same rule as a whole column.

A cast value is therefore one of three things: the type's own Python value,
``None`` for a null, or :class:`KeptText` for text that ``keep-string`` held on
to.  The last two are shared by every type, so :func:`rendered` and
:func:`json_form` deal with them once instead of in every type.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Callable, Protocol

from errors import TypeCastError
from records import FieldValue, Origin


class KeptText(str):
    """The original text of a value ``--on-type-error=keep-string`` kept.

    It is a string, so it serialises and renders as one, but it stays
    distinguishable from a value that genuinely parsed, which is what lets it
    sort after the values of its column.
    """


class ValueType(Protocol):
    """What the schema's types have in common, primitive or nested."""

    @property
    def name(self) -> str:
        """The type as it is written in a schema, for error messages."""

    def cast(self, value: FieldValue, context: "CastContext") -> object:
        """Turn an input value into a value of this type, or recover from it."""

    def render(self, value: object) -> str:
        """The CSV cell text of a non-null cast value of this type."""

    def to_json(self, value: object) -> object:
        """The ``json.dumps`` ready form of a non-null cast value."""


@dataclass(frozen=True)
class CastContext:
    """The ``--on-type-error`` policy, plus where the value being cast sits.

    The path grows as the cast descends into a nested value, so the field named
    in an error message is the full ``items.0.sku`` rather than the column.
    """

    on_type_error: str
    origin: Origin
    path: str = ""

    @property
    def text_cells(self) -> bool:
        """True when the input hands over text, so nested cells are JSON text."""
        return self.origin.text_cells

    def child(self, member: str | int) -> "CastContext":
        """The context of a field, element or map entry of the current value."""
        return replace(self, path=f"{self.path}.{member}" if self.path else str(member))

    def recover(self, text: str, type_name: str) -> KeptText | None:
        """Settle a value that does not fit ``type_name`` the way the flag asks."""
        if self.on_type_error == "fail":
            raise TypeCastError(
                f'cannot cast "{text}" to {type_name} in field "{self.path}" '
                f"(file={self.origin.file}, line={self.origin.line})"
            )
        return KeptText(text) if self.on_type_error == "keep-string" else None


def compact_json(value: object, default: Callable[[object], object] | None = None) -> str:
    """Serialise ``value`` as canonical JSON: minified, UTF-8, RFC 8259 escaped.

    ``default`` renders whatever JSON itself has no form for, which is how a
    value that arrived typed from Parquet reaches its canonical text.
    """
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=default)


def rendered(value_type: ValueType, value: object) -> str:
    """The output text of a non-null cast value; kept text is already text."""
    return str(value) if isinstance(value, KeptText) else value_type.render(value)


def json_form(value_type: ValueType, value: object) -> object:
    """The JSON ready form of a cast value; nulls and kept text pass through."""
    if value is None or isinstance(value, KeptText):
        return value
    return value_type.to_json(value)
