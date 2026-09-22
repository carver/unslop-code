"""Datasets, the cell types they hold, and the ids they are addressed by."""

import hashlib
import threading
from dataclasses import dataclass

from errors import DatagateError

ID_LENGTH = 16

Cell = str | int | float
Row = list[Cell]
# A table as it comes out of a parser: rows of cells, not yet split into header and data.
Grid = list[Row]
# A row paired with its 1-based position among the source file's data rows.
NumberedRow = tuple[int, Row]


@dataclass(frozen=True)
class Dataset:
    """A parsed table: header names plus data rows, both in source order."""

    columns: list[str]
    rows: list[Row]


def dataset_id_for(origin: bytes) -> str:
    """Map a dataset's origin to its id.

    The origin is whatever identifies the dataset: a source URL's text for `/convert`, the file's
    own content for `/upload`. The same origin always yields the same id.
    """
    return hashlib.sha256(origin).hexdigest()[:ID_LENGTH]


class DatasetStore:
    """In-memory dataset registry, safe to share between server threads."""

    def __init__(self):
        self._datasets: dict[str, Dataset] = {}
        self._lock = threading.Lock()

    def save(self, origin: bytes, dataset: Dataset) -> str:
        """Store (or replace) the dataset for `origin` and return its id."""
        dataset_id = dataset_id_for(origin)
        with self._lock:
            self._datasets[dataset_id] = dataset
        return dataset_id

    def holds(self, dataset_id: str) -> bool:
        """Whether a dataset is already stored under this id — the question the cache asks."""
        with self._lock:
            return dataset_id in self._datasets

    def require(self, dataset_id: str) -> Dataset:
        """Return the stored dataset, reporting an id that was never converted as 404."""
        with self._lock:
            dataset = self._datasets.get(dataset_id)
        if dataset is None:
            raise DatagateError(404, f"Unknown dataset id: {dataset_id!r}")
        return dataset
