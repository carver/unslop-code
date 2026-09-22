"""Application error type and the JSON envelope shared by every response."""

from flask import jsonify
from flask.wrappers import Response


class GateError(Exception):
    """Failure that should be reported to the client with ``status``."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


def error_response(message: str, status: int) -> tuple[Response, int]:
    """Build the ``{"ok": false, ...}`` body used for every failure."""
    return jsonify({"ok": False, "error": message}), status
