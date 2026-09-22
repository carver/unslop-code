"""The recent-vault list: what the browser remembers, and what the server does.

The cookie is what carries the list from one browser session to the next. The
server keeps its own copy of the same list so that a browser which sends no
cookie back still sees where this viewer has been.
"""

from urllib.parse import quote, unquote

#: Cookie the browser stores the visited vaults in, and how long it keeps it.
COOKIE_NAME = "mvault_recent"
COOKIE_MAX_AGE = 365 * 24 * 60 * 60

#: How many vaults the list holds before the oldest ones drop off.
LIMIT = 20


class RecentVaults:
    """Vaults visited through this server, most recently visited first."""

    def __init__(self):
        self._names = ()

    @property
    def names(self):
        return self._names

    def visit(self, name):
        """Record a visit to `name`, moving it to the front of the list."""
        self._names = merge((name,), self._names)


def merge(*lists):
    """The lists run together, earliest occurrence winning, capped at `LIMIT`."""
    return tuple(dict.fromkeys(name for names in lists for name in names))[:LIMIT]


def from_cookie(header):
    """The vault names a request's `Cookie` header carries, most recent first."""
    for chunk in header.split(";"):
        key, _, value = chunk.strip().partition("=")
        if key == COOKIE_NAME:
            return tuple(unquote(part) for part in value.split(",") if part)
    return ()


def to_cookie(names):
    """A `Set-Cookie` value storing `names` beyond the browser session."""
    stored = ",".join(quote(name, safe="") for name in names)
    return f"{COOKIE_NAME}={stored}; Max-Age={COOKIE_MAX_AGE}; Path=/; SameSite=Lax"
