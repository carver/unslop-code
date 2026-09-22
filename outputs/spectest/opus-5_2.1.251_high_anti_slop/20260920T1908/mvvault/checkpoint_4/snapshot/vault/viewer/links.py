"""The addresses of the local viewer.

Reports print absolute links to the address the viewer listens on by default,
while the viewer's own pages link to each other by path.
"""

from urllib.parse import quote

SCHEME = "http"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8840

LANDING_PATH = "/"


def base_url(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> str:
    """The origin the viewer answers on."""
    return f"{SCHEME}://{host}:{port}"


def catalog_path(name: str) -> str:
    """The route that redirects to a vault's default category page."""
    return f"/catalog/{quote(name, safe='')}"


def category_path(name: str, category: str) -> str:
    """The listing page of one category of a vault."""
    return f"{catalog_path(name)}/{quote(category, safe='')}"


def entry_path(name: str, category: str, entry_id: str) -> str:
    """The page one entry's viewer link points at."""
    return f"{category_path(name, category)}/{quote(entry_id, safe='')}"


def entry_link(name: str, category: str, entry_id: str) -> str:
    """The absolute viewer link a report prints next to one entry's title."""
    return base_url() + entry_path(name, category, entry_id)
