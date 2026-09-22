"""The type a column may be declared as: a primitive, or one of the nested kinds.

A declared type is either a :class:`~csvmerge.types.ColumnType` primitive, one
of the three nested kinds — a ``struct`` of named fields, a homogeneous
``array``, a ``map`` keyed by strings — or ``json``, which carries any JSON
value through untouched. Inference only ever produces primitives; the nested
kinds come from a ``--schema`` file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from .types import ColumnType


@dataclass(frozen=True)
class Field:
    """One named field of a struct. The declaration order is the output order."""

    name: str
    type: DataType


@dataclass(frozen=True)
class StructType:
    """An ordered list of named fields, every one of them always emitted."""

    fields: tuple[Field, ...]


@dataclass(frozen=True)
class ArrayType:
    """A sequence of values that all share ``element``'s type."""

    element: DataType


@dataclass(frozen=True)
class MapType:
    """A mapping with string keys; only the value type varies."""

    value: DataType


@dataclass(frozen=True)
class JsonType:
    """Any JSON value at all, normalised on output but never cast."""


#: ``json`` takes no parameters, so every declaration of it is this instance.
JSON = JsonType()

DataType = Union[ColumnType, StructType, ArrayType, MapType, JsonType]

_DESCRIPTIONS = {
    StructType: lambda _data_type: "struct",
    ArrayType: lambda data_type: f"array<{describe(data_type.element)}>",
    MapType: lambda data_type: f"map<string,{describe(data_type.value)}>",
    JsonType: lambda _data_type: "json",
}


def is_primitive(data_type: DataType) -> bool:
    """Report whether ``data_type`` holds a single value rather than a structure."""
    return isinstance(data_type, ColumnType)


def describe(data_type: DataType) -> str:
    """Spell a type the way the schema file and the error messages refer to it."""
    if isinstance(data_type, ColumnType):
        return data_type.value
    return _DESCRIPTIONS[type(data_type)](data_type)
