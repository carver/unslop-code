"""Dataset identity and the in-process dataset store."""

import hashlib

from datagate_core.tables import Table

ID_LENGTH = 16


def dataset_id(source: str) -> str:
    """Return the stable id for a source URL string (see AMBIGUITIES T1)."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:ID_LENGTH]


class DatasetStore:
    """Keeps parsed tables keyed by the id derived from their source URL."""

    def __init__(self) -> None:
        self._tables: dict[str, Table] = {}

    def save(self, source: str, table: Table) -> str:
        """Store `table` under the id of `source`, replacing any earlier version."""
        identifier = dataset_id(source)
        self._tables[identifier] = table
        return identifier

    def get(self, identifier: str) -> Table | None:
        return self._tables.get(identifier)
