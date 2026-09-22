"""Dataset identity and the in-memory table store."""

import hashlib
from dataclasses import dataclass

ID_LENGTH = 16


def dataset_id(source_url):
    """Map a source URL string to its stable dataset id."""
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:ID_LENGTH]


@dataclass(frozen=True)
class Dataset:
    """A parsed table: header names and typed rows, both in source order."""

    columns: list
    rows: list


class DatasetStore:
    """Holds converted datasets for the lifetime of the process."""

    def __init__(self):
        self._datasets = {}

    def put(self, identifier, dataset):
        self._datasets[identifier] = dataset

    def get(self, identifier):
        """Return the dataset for `identifier`, or None if it was never converted."""
        return self._datasets.get(identifier)
