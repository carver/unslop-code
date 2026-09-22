"""The viewer's memory of visited vaults, most recently visited first.

A visit is recorded twice over: in a long-lived cookie, so the browser that
made it still sees the vault in a later session, and in a small file under the
served directory, so a client that keeps no cookies still gets a useful
landing page. Both stores hold the same order, so merging them is a matter of
dropping duplicates.
"""

import json
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import quote, unquote

COOKIE_NAME = "mvault_recent"
COOKIE_MAX_AGE = 365 * 24 * 60 * 60
STATE_FILE = ".mvault-recent.json"
LIMIT = 20


def promote(names, name):
    """`names` with `name` moved to the front, kept within the list limit."""
    return [name, *(other for other in names if other != name)][:LIMIT]


def merge(cookie_names, stored_names):
    """Both memories as one list, the browser's own visits taking precedence."""
    merged = list(cookie_names)
    merged += [name for name in stored_names if name not in merged]
    return merged[:LIMIT]


def from_cookie(header):
    """The vault names a request's `Cookie` header remembers."""
    morsel = SimpleCookie(header or "").get(COOKIE_NAME)
    if morsel is None:
        return []
    return [unquote(part) for part in morsel.value.split(",") if part]


def to_cookie(names):
    """The `Set-Cookie` value remembering `names` past the current session."""
    value = ",".join(quote(name, safe="") for name in names)
    return f"{COOKIE_NAME}={value}; Max-Age={COOKIE_MAX_AGE}; Path=/"


class RecentFile:
    """The served directory's own record of visited vaults, newest first."""

    def __init__(self, root):
        self.path = Path(root) / STATE_FILE

    def read(self):
        """The remembered names, or none when nothing readable is stored."""
        try:
            names = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [name for name in names if isinstance(name, str)]

    def record(self, name):
        """Move `name` to the front of the stored list."""
        self.path.write_text(json.dumps(promote(self.read(), name)), encoding="utf-8")
