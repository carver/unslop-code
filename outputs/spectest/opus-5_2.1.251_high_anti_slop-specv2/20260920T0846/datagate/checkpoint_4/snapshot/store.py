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
    """A converted table: what it came from, its column names and its rows.

    ``origin`` identifies the source rather than describing it: the URL a
    conversion read, or a fingerprint of the bytes an upload carried.
    """

    origin: str
    columns: list[str]
    rows: list[Row]


class DatasetStore:
    """Datasets keyed by a hash of their origin.

    The key is derived from the origin alone, so ingesting the same source
    twice yields the same endpoint and replaces the previously stored rows.
    """

    def __init__(self):
        self._datasets: dict[str, Dataset] = {}

    @staticmethod
    def identify(origin: str) -> str:
        return hashlib.sha256(origin.encode("utf-8")).hexdigest()[:16]

    def add(self, dataset: Dataset) -> str:
        dataset_id = self.identify(dataset.origin)
        self._datasets[dataset_id] = dataset
        return dataset_id

    def get(self, dataset_id: str) -> Dataset | None:
        return self._datasets.get(dataset_id)
