"""Bridging to live objects: importing modules and inspecting what they hold."""

import builtins
import contextlib
import importlib
import inspect
import sys


def import_module(name, search_path):
    """Import `name`, letting the analysed project shadow installed packages.

    Importing runs third-party module code, so any failure it raises is simply
    an unresolvable name for our purposes.
    """
    with _path_prefixed(search_path):
        try:
            return importlib.import_module(name)
        except Exception:
            return None


@contextlib.contextmanager
def _path_prefixed(search_path):
    sys.path.insert(0, search_path)
    try:
        yield
    finally:
        sys.path.remove(search_path)


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
