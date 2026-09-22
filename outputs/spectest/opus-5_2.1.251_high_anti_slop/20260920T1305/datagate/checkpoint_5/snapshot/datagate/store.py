"""In-memory registry of converted datasets, keyed by a deterministic id."""

import hashlib
from dataclasses import dataclass

from .errors import DataGateError
from .values import Value

ID_LENGTH = 16


@dataclass(frozen=True)
class Dataset:
    """A parsed table held in memory, with columns and rows in source order.

    ``origin`` names where the table came from -- the source URL for a conversion, or a
    digest of the file's bytes for an upload -- and decides the dataset's id.
    """

    origin: str
    columns: list[str]
    rows: list[list[Value]]


def dataset_id(origin: str) -> str:
    """Return the id an ``origin`` always maps to."""
    return hashlib.sha256(origin.encode("utf-8")).hexdigest()[:ID_LENGTH]


class DatasetStore:
    """Stores datasets so that re-ingesting the same origin overwrites its entry."""

    def __init__(self) -> None:
        self._datasets: dict[str, Dataset] = {}

    def add(self, dataset: Dataset) -> str:
        """Store ``dataset`` and return the id under which it can be queried."""
        identifier = dataset_id(dataset.origin)
        self._datasets[identifier] = dataset
        return identifier

    def has(self, identifier: str) -> bool:
        """Return whether a dataset is already stored under ``identifier``."""
        return identifier in self._datasets

    def get(self, identifier: str) -> Dataset:
        """Return the dataset stored under ``identifier``, or raise a 404 error."""
        dataset = self._datasets.get(identifier)
        if dataset is None:
            raise DataGateError(f"unknown dataset {identifier!r}", 404)
        return dataset
