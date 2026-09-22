"""The URLs the viewer serves and the reports link to."""

from urllib.parse import quote

SCHEME = "http"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8840

CATALOG_SEGMENT = "catalog"
CATALOG_ROOT = f"/{CATALOG_SEGMENT}"

#: Root of the static endpoints, and the two kinds of file they serve.
VAULT_SEGMENT = "vault"
MEDIA_SEGMENT = "media"
PREVIEW_SEGMENT = "preview"

#: The path a source platform puts one entry at, below the vault's source.
ENTRY_SEGMENT = "entry"


def catalog_route(name, *segments):
    """The viewer path of a vault, one of its categories, or one entry."""
    path = "/".join(quote(str(segment), safe="") for segment in (name, *segments))
    return f"{CATALOG_ROOT}/{path}"


def entry_url(name, category, entry_id, host=DEFAULT_HOST, port=DEFAULT_PORT):
    """The absolute link a change report appends to an entry's line."""
    return f"{SCHEME}://{host}:{port}{catalog_route(name, category, entry_id)}"


def vault_route(name, kind, leaf):
    """The static path of a stored file: `/vault/<name>/media|preview/<leaf>`."""
    path = "/".join(quote(str(segment), safe="") for segment in (name, kind, leaf))
    return f"/{VAULT_SEGMENT}/{path}"


def source_entry_url(source, entry_id):
    """The entry's page on the source platform the vault was filled from.

    Every supported version resolves to a full source URL - version 1 derives
    one from its `source_id` - so one derivation covers them all.
    """
    return f"{source.rstrip('/')}/{ENTRY_SEGMENT}/{quote(str(entry_id), safe='')}"
