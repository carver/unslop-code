"""Turning raw records into typed row values under the type-error policy."""

from __future__ import annotations

from dataclasses import dataclass

from .coltypes import CastError, KeptText, cast
from .errors import MergeError
from .schema import Schema

COERCE_NULL = "coerce-null"
FAIL = "fail"
KEEP_STRING = "keep-string"
POLICIES = (COERCE_NULL, FAIL, KEEP_STRING)


@dataclass(frozen=True)
class RowCaster:
    """Casts records into the resolved schema's types."""

    schema: Schema
    policy: str

    def cast_row(self, record, origin):
        """Return one value per schema column, in schema order."""
        return [self._cell(column, record.get(column.name), origin) for column in self.schema.columns]

    def _cell(self, column, text, origin):
        if text is None:
            return None
        try:
            return cast(column.type, text)
        except CastError as error:
            return self._on_error(column, text, origin, error)

    def _on_error(self, column, text, origin, error):
        if self.policy == FAIL:
            raise MergeError(f"{origin}: column {column.name!r}: {error}")
        return KeptText(text) if self.policy == KEEP_STRING else None
