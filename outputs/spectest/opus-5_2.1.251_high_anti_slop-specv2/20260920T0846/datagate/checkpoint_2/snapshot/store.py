"""In-memory storage for converted datasets."""

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Row:
    """One data row, tagged with the line it occupied in the source file."""

    rowid: int
    values: list


@dataclass(frozen=True)
class Dataset:
    """A converted CSV: its origin, its column names and its typed rows."""

    source: str
    columns: list[str]
    rows: list[Row]


class DatasetStore:
    """Datasets keyed by a hash of their source URL.

    The key is derived from the URL alone, so converting the same source twice
    yields the same endpoint and replaces the previously stored rows.
    """

    def __init__(self):
        self._datasets: dict[str, Dataset] = {}

    @staticmethod
    def identify(source: str) -> str:
        return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]

    def add(self, dataset: Dataset) -> str:
        dataset_id = self.identify(dataset.source)
        self._datasets[dataset_id] = dataset
        return dataset_id

    def get(self, dataset_id: str) -> Dataset | None:
        return self._datasets.get(dataset_id)
