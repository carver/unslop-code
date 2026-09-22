"""The vaults a browser has visited, remembered in a cookie.

The list lives in the browser rather than the vault directory, so it survives
the browser being closed and reopened without the viewer writing anything.
"""

from urllib.parse import quote, unquote

COOKIE_NAME = "mvault_recent"
SEPARATOR = "|"
LIMIT = 8
MAX_AGE_SECONDS = 365 * 24 * 60 * 60


def visited(cookie_header):
    """Vault names the browser sending ``cookie_header`` has seen, newest first."""
    for crumb in cookie_header.split(";"):
        name, _, value = crumb.strip().partition("=")
        if name == COOKIE_NAME:
            return [unquote(item) for item in value.split(SEPARATOR) if item]
    return []


def remember(names, name):
    """The ``Set-Cookie`` value that moves ``name`` to the head of ``names``."""
    kept = [name] + [other for other in names if other != name]
    value = SEPARATOR.join(quote(item, safe="") for item in kept[:LIMIT])
    return f"{COOKIE_NAME}={value}; Max-Age={MAX_AGE_SECONDS}; Path=/; SameSite=Lax"
