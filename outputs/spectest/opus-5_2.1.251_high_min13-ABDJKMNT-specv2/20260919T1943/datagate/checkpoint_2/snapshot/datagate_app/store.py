"""Dataset identity and in-memory storage."""

import hashlib

from .parsing import Dataset

ID_LENGTH = 16


def dataset_id(source: str) -> str:
    """Derive the stable id of a source URL string."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:ID_LENGTH]


class DatasetStore:
    """Datasets held in memory, keyed by the id of the URL they came from."""

    def __init__(self):
        self._datasets: dict[str, Dataset] = {}

    def save(self, source: str, dataset: Dataset) -> str:
        """Store (or replace) the dataset for `source` and return its id."""
        identifier = dataset_id(source)
        self._datasets[identifier] = dataset
        return identifier

    def get(self, identifier: str) -> Dataset | None:
        return self._datasets.get(identifier)
