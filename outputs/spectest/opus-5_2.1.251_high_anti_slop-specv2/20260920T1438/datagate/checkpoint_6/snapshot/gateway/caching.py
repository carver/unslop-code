"""The per-request control that bypasses the ``/convert`` cache."""

from gateway.errors import GateError

#: Query parameter forcing one ``/convert`` request past the cache.
FORCE = "force"


def force_requested(query_string: bytes) -> bool:
    """Report whether the request carries the bare ``force`` flag.

    ``force`` says only that it is there, so it is read from the raw query
    string: Flask reports ``?force`` and ``?force=yes`` as the same key with
    the same empty value, and only the second is a 400.
    """
    occurrences = [
        parameter
        for parameter in query_string.decode("utf-8", "replace").split("&")
        if parameter.split("=", 1)[0] == FORCE
    ]
    if not occurrences:
        return False
    if len(occurrences) > 1:
        raise GateError(f"Query parameter {FORCE!r} may be given only once", 400)
    if "=" in occurrences[0]:
        raise GateError(f"Query parameter {FORCE!r} takes no value", 400)
    return True
