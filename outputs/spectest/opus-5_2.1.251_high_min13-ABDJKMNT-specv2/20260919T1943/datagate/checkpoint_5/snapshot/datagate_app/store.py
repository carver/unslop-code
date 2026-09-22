"""Dataset identity and in-memory storage."""

import hashlib

from .parsing import Dataset

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
    """Datasets held in memory under the id derived from where they came from."""

    def __init__(self):
        self._datasets: dict[str, Dataset] = {}

    def save(self, identifier: str, dataset: Dataset) -> None:
        """Store `dataset` under `identifier`, replacing any earlier version."""
        self._datasets[identifier] = dataset

    def get(self, identifier: str) -> Dataset | None:
        return self._datasets.get(identifier)
