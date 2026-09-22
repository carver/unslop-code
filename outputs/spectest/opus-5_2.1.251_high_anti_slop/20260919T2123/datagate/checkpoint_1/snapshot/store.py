"""Storage of converted datasets, addressed by a hash of their source URL."""

import hashlib
import threading
from dataclasses import dataclass

ID_LENGTH = 16

Row = list[str | int | float]


@dataclass(frozen=True)
class Dataset:
    """A parsed table: header names plus data rows, both in source order."""

    columns: list[str]
    rows: list[Row]


def dataset_id_for(source: str) -> str:
    """Map a source URL to its dataset id. The same URL string always yields the same id."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:ID_LENGTH]


class DatasetStore:
    """In-memory dataset registry, safe to share between server threads."""

    def __init__(self):
        self._datasets: dict[str, Dataset] = {}
        self._lock = threading.Lock()

    def save(self, source: str, dataset: Dataset) -> str:
        """Store (or replace) the dataset for `source` and return its id."""
        dataset_id = dataset_id_for(source)
        with self._lock:
            self._datasets[dataset_id] = dataset
        return dataset_id

    def get(self, dataset_id: str) -> Dataset | None:
        with self._lock:
            return self._datasets.get(dataset_id)
