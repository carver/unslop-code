"""Vault builders and request helpers shared by the annotation tests.

The annotation methods are driven over HTTP against a real `serve` process, so
these helpers only speak in requests and in what `catalog.json` holds
afterwards -- never in viewer internals.
"""

from conftest import EPOCH_KEY, REDIRECT_STATUSES, find_entry, legacy_entry, read_catalog, v1_catalog, write_vault

#: The detail route of the shared fixture entry, in a v3 vault and in a v1 one.
V3_ENTRY = "/catalog/demo/episodes/e1"
V1_ENTRY = "/catalog/demo/entries/e1"

#: An older and a newer UNIX-epoch key, for a v1 vault with two entries.
EPOCH_SECOND = "1718448000"


def mark(**overrides):
    """A well-formed create body, overridden field by field."""
    return {"title": "chorus", "timecode": "1:30", **overrides}


def annotate(viewer, method, payload, path=V3_ENTRY):
    """Send one annotation request; `payload` is a dict, or raw body text."""
    return viewer.client.json_request(method, path, payload)


def post(viewer, payload=None, path=V3_ENTRY):
    return annotate(viewer, "POST", mark() if payload is None else payload, path)


def patch(viewer, payload, path=V3_ENTRY):
    return annotate(viewer, "PATCH", payload, path)


def delete(viewer, payload, path=V3_ENTRY):
    return annotate(viewer, "DELETE", payload, path)


def stored(vault_path, category="episodes", entry_id="e1"):
    """The annotations one entry of a vault on disk currently holds."""
    return find_entry(read_catalog(vault_path), category, entry_id)["annotations"]


def created(viewer, vault_path, payload=None, path=V3_ENTRY, category="episodes"):
    """`POST` one annotation and return the record the vault stored for it."""
    response = post(viewer, payload, path)
    assert response.status in REDIRECT_STATUSES, response.body
    return stored(vault_path, category)[-1]


def v1_pair_vault(tmp_path, name="demo"):
    """A v1 vault with two entries, so a shared migration timestamp is visible."""
    entries = (legacy_entry("e1", EPOCH_KEY), legacy_entry("e2", EPOCH_SECOND))
    return write_vault(tmp_path, name, v1_catalog(*entries))
