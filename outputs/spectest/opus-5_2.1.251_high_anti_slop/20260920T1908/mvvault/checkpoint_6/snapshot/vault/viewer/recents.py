"""The vaults a browser has opened through the viewer.

The list travels in a long-lived cookie, so a browser that comes back in a
later session still sees where it has been. Most recently visited comes first.
"""

from http.cookies import SimpleCookie
from urllib.parse import quote, unquote

COOKIE_NAME = "mvault_recent"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365
RECENT_LIMIT = 10


def read_recent(cookie_header: str | None) -> list[str]:
    """The vault names a request's ``Cookie`` header carries, newest first."""
    cookies = SimpleCookie()
    cookies.load(cookie_header or "")
    morsel = cookies.get(COOKIE_NAME)
    if morsel is None:
        return []
    return [unquote(name) for name in morsel.value.split(",") if name]


def visit_cookie(recent: list[str], name: str) -> str:
    """The ``Set-Cookie`` value that moves ``name`` to the front of ``recent``."""
    visited = [name] + [earlier for earlier in recent if earlier != name]
    value = ",".join(quote(entry, safe="") for entry in visited[:RECENT_LIMIT])
    return f"{COOKIE_NAME}={value}; Max-Age={COOKIE_MAX_AGE}; Path=/; SameSite=Lax"
