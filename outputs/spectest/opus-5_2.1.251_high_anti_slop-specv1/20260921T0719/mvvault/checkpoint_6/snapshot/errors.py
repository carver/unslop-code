"""Failure types reported to whoever asked: a CLI user or a viewer visitor."""

from http import HTTPStatus


class MvaultError(Exception):
    """A user-facing failure; its message is printed verbatim to stderr."""


class RequestError(Exception):
    """A request the viewer refuses, under the status it refuses it with.

    The message is what the visitor is shown, so it names what was wrong with
    the request rather than where the code noticed it.
    """

    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status
