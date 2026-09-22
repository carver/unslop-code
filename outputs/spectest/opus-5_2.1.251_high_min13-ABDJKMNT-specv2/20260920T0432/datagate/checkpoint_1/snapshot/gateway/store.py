"""Dataset identity and the in-memory dataset store."""

import hashlib
from dataclasses import dataclass, field

from .tabular import Cell


@dataclass(frozen=True)
class Dataset:
    """One converted CSV: its id plus the columns and typed rows to serve."""

    id: str
    columns: list[str]
    rows: list[list[Cell]] = field(default_factory=list)


def dataset_id(source: str) -> str:
    """Id for a source URL, derived from the URL string alone.

    Being a pure function of the string, the same `source` maps to the same id
    for every request and across restarts.
    """
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


class DatasetStore:
    """Datasets held in process memory, keyed by `dataset_id`."""

    def __init__(self):
        self._datasets: dict[str, Dataset] = {}

    def save(self, dataset: Dataset) -> None:
        """Store `dataset`, replacing any earlier conversion of the same source."""
        self._datasets[dataset.id] = dataset

    def get(self, identifier: str) -> Dataset | None:
        return self._datasets.get(identifier)
