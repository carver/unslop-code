"""What the viewer sends back, apart from what any one request means.

Pages, redirects and refusals share these shapes, so the routes that read a
vault and the ones that write an annotation to it answer in the same terms.
"""

from dataclasses import dataclass
from http import HTTPStatus
from urllib.parse import urlencode

import pages

#: Query the landing page reports an unreadable vault under.
MISSING_QUERY = "missing"

#: Content type every page the viewer renders is served as.
HTML_TYPE = "text/html; charset=utf-8"


@dataclass(frozen=True)
class Response:
    """What to send back: a status, a body and, for a redirect, a target."""

    status: HTTPStatus
    body: bytes = b""
    content_type: str = HTML_TYPE
    location: str = ""


def page(status: HTTPStatus, markup: str) -> Response:
    """A rendered page, ready to be sent."""
    return Response(status, markup.encode("utf-8"))


def refusal(status: HTTPStatus, message: str) -> Response:
    """A request the viewer answers with the reason it does not serve it."""
    return page(status, pages.failure(message))


def redirect(location: str) -> Response:
    """Send the visitor on to ``location``."""
    return Response(HTTPStatus.SEE_OTHER, location=location)


def missing(name: str) -> Response:
    """Send the visitor back to the landing page, naming the vault it wanted."""
    return redirect(f"/?{urlencode({MISSING_QUERY: name})}")


#: Answers to a path the viewer serves nothing at, and to a request it broke on.
NOT_FOUND = refusal(HTTPStatus.NOT_FOUND, "No such page")
FAILURE = refusal(
    HTTPStatus.INTERNAL_SERVER_ERROR, "The viewer could not answer that request"
)
