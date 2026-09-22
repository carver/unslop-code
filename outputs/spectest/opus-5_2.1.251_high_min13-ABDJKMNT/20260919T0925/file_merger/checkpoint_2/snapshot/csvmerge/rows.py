"""Turning source records into typed row values under the type-error policy."""

from __future__ import annotations

from dataclasses import dataclass

from .coltypes import CastError, KeptText, render
from .errors import CastFailure
from .schema import Schema
from .values import cast_value

COERCE_NULL = "coerce-null"
FAIL = "fail"
KEEP_STRING = "keep-string"
POLICIES = (COERCE_NULL, FAIL, KEEP_STRING)


@dataclass(frozen=True)
class RowCaster:
    """Casts records into the resolved schema's types.

    Records hold raw text from CSV/TSV and native values from JSONL/Parquet;
    `cast_value` handles both, so the policy below is all that differs.
    """

    schema: Schema
    policy: str

    def cast_row(self, record, origin):
        """Return one value per schema column, in schema order."""
        return [self._cell(column, record.get(column.name), origin) for column in self.schema.columns]

    def _cell(self, column, value, origin):
        if value is None:
            return None
        try:
            return cast_value(column.type, value)
        except CastError as error:
            return self._on_error(column, value, origin, error)

    def _on_error(self, column, value, origin, error):
        if self.policy == FAIL:
            raise CastFailure(f"{origin}: column {column.name!r}: {error}")
        return KeptText(render(value, "")) if self.policy == KEEP_STRING else None
