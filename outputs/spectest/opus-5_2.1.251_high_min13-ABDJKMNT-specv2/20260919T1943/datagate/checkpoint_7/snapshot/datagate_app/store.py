"""Dataset identity and the on-disk dataset store."""

import hashlib
import json
from pathlib import Path

from .parsing import Dataset, Row

ID_LENGTH = 16


def dataset_id(source: str) -> str:
    """Derive the stable id of a source URL string (T1)."""
    return _digest(source.encode("utf-8"))


def upload_id(data: bytes) -> str:
    """Derive the stable id of an upload from its bytes alone (T38)."""
    return _digest(data)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:ID_LENGTH]


class DatasetStore:
    """Datasets held as one JSON document per id inside the storage directory.

    Writing the parsed table out is what lets it outlive the process that
    ingested it: a later server over the same directory reads the same rows back
    (T69). The directory is created when the store is opened.
    """

    def __init__(self, directory: Path):
        self._directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def save(self, identifier: str, dataset: Dataset) -> None:
        """Store `dataset` under `identifier`, replacing any earlier version.

        The document is written beside its destination and moved into place, so a
        reader never observes a half-written dataset.
        """
        document = {
            "columns": dataset.columns,
            "rows": [[row.rowid, row.values] for row in dataset.rows],
            "metadata": dataset.metadata,
        }
        pending = self._path(f"{identifier}.pending")
        pending.write_text(json.dumps(document))
        pending.replace(self._path(identifier))

    def get(self, identifier: str) -> Dataset | None:
        """Read back a stored dataset, or `None` when the directory holds no such id."""
        path = self._path(identifier)
        if not path.is_file():
            return None
        document = json.loads(path.read_text())
        rows = [Row(rowid, values) for rowid, values in document["rows"]]
        return Dataset(document["columns"], rows, document["metadata"])

    def _path(self, identifier: str) -> Path:
        return self._directory / f"{identifier}.json"
