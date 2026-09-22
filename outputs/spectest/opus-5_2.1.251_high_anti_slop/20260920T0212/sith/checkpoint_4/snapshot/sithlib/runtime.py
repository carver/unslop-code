"""Bridging to live objects: importing modules and inspecting what they hold."""

import builtins
import importlib
import inspect
import pkgutil
import sys


def import_module(name):
    """Import `name`, or return ``None`` when importing it fails.

    Importing runs module code, so any failure it raises is simply an
    unresolvable name for our purposes.
    """
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def is_stdlib(dotted):
    """Whether a dotted name belongs to a standard-library module."""
    return dotted.split(".")[0] in sys.stdlib_module_names


def stdlib_names(dotted):
    """Standard-library module names: the top-level ones, or those inside `dotted`."""
    if not dotted:
        return sorted(sys.stdlib_module_names)
    package = import_module(dotted) if is_stdlib(dotted) else None
    paths = getattr(package, "__path__", None)
    return [] if paths is None else [found.name for found in pkgutil.iter_modules(paths)]


def live_members(obj):
    """Name -> attribute of a live object; modules expose their public names only."""
    public_only = inspect.ismodule(obj)
    return {
        name: getattr(obj, name, None)
        for name in dir(obj)
        if not (public_only and name.startswith("_"))
    }


def builtin_type(name):
    """The builtin type of that name, spelling the type of ``None`` as ``None``."""
    return type(None) if name == "None" else getattr(builtins, name, None)


_BUILTINS = {name: getattr(builtins, name) for name in dir(builtins)}


def builtin_objects():
    """Every name in the builtin scope, mapped to the object it holds."""
    return _BUILTINS
