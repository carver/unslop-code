"""In-memory registry of ingested datasets, keyed by a deterministic id."""

import hashlib
from dataclasses import dataclass

from gateway.values import Value

ID_LENGTH = 16


@dataclass(frozen=True)
class Dataset:
    """A parsed table: where it came from, its column names and all of its rows."""

    origin: str
    columns: list[str]
    rows: list[list[Value]]


def dataset_id(origin: str) -> str:
    """Derive the stable dataset id of an origin."""
    return hashlib.sha256(origin.encode("utf-8")).hexdigest()[:ID_LENGTH]


def upload_origin(payload: bytes) -> str:
    """Name an uploaded dataset after its bytes.

    An upload has no address to be identified by, so its content becomes its
    origin and re-uploading the same file lands on the same dataset.
    """
    return f"upload:{hashlib.sha256(payload).hexdigest()}"


class DatasetStore:
    """Process-local storage; re-ingesting an origin replaces its dataset."""

    def __init__(self) -> None:
        self._datasets: dict[str, Dataset] = {}

    def save(self, dataset: Dataset) -> str:
        """Store ``dataset`` and return the id it is reachable under."""
        identifier = dataset_id(dataset.origin)
        self._datasets[identifier] = dataset
        return identifier

    def get(self, identifier: str) -> Dataset | None:
        """Return the stored dataset, or ``None`` when the id is unknown."""
        return self._datasets.get(identifier)
