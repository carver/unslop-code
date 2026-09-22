"""Helpers shared by the nested-types tests: schema and alias file fixtures."""

import json

INT = {"name": "id", "type": "int"}


def struct(*fields):
    """A struct type declaration from (name, type) pairs."""
    return {
        "struct": {"fields": [{"name": name, "type": kind} for name, kind in fields]}
    }


def array(element):
    """An array type declaration."""
    return {"array": {"element": element}}


def mapping(value, key="string"):
    """A map type declaration; the key type defaults to string."""
    return {"map": {"key": key, "value": value}}


def write_schema(make_file, columns, name="schema.json"):
    """Materialise a --schema file holding `columns`."""
    return make_file(name, json.dumps({"columns": columns}))


def write_aliases(make_file, aliases, name="aliases.json"):
    """Materialise a --type-alias-file holding `aliases`."""
    return make_file(name, json.dumps({"aliases": aliases}))
