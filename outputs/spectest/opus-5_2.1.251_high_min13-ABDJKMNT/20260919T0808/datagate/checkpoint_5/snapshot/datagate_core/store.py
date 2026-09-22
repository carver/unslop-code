"""Dataset identity and the in-process dataset store."""

import hashlib

from datagate_core.tables import Table

ID_LENGTH = 16


def dataset_id(identity: str | bytes) -> str:
    """Return the stable id for a dataset's identity.

    That identity is the `source` URL string for `/convert` (T1) and the file's
    own bytes for `/upload`, so re-uploading the same file lands on one id (T34).
    """
    material = identity.encode("utf-8") if isinstance(identity, str) else identity
    return hashlib.sha256(material).hexdigest()[:ID_LENGTH]


class DatasetStore:
    """Keeps parsed tables keyed by the id derived from their source or bytes."""

    def __init__(self) -> None:
        self._tables: dict[str, Table] = {}

    def save(self, identity: str | bytes, table: Table) -> str:
        """Store `table` under the id of `identity`, replacing any earlier version."""
        identifier = dataset_id(identity)
        self._tables[identifier] = table
        return identifier

    def has(self, identifier: str) -> bool:
        """Whether a dataset is already stored under `identifier` (a cache hit)."""
        return identifier in self._tables

    def get(self, identifier: str) -> Table | None:
        return self._tables.get(identifier)
