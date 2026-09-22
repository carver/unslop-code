"""In-memory registry of converted datasets, keyed by a deterministic id."""

import hashlib
from dataclasses import dataclass

from gateway.values import Value

ID_LENGTH = 16


@dataclass(frozen=True)
class Dataset:
    """A parsed CSV: its origin, its column names and all of its rows."""

    source: str
    columns: list[str]
    rows: list[list[Value]]


def dataset_id(source: str) -> str:
    """Derive the stable dataset id of a source URL."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:ID_LENGTH]


class DatasetStore:
    """Process-local storage; re-converting a source replaces its dataset."""

    def __init__(self) -> None:
        self._datasets: dict[str, Dataset] = {}

    def save(self, dataset: Dataset) -> str:
        """Store ``dataset`` and return the id it is reachable under."""
        identifier = dataset_id(dataset.source)
        self._datasets[identifier] = dataset
        return identifier

    def get(self, identifier: str) -> Dataset | None:
        """Return the stored dataset, or ``None`` when the id is unknown."""
        return self._datasets.get(identifier)
