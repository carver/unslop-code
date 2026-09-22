"""Datasets, the cell types they hold, the ids they are addressed by, and where they are kept."""

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from errors import DatagateError

ID_LENGTH = 16
RECORD_SUFFIX = ".json"

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
    """Dataset registry backed by a storage directory, safe to share between server threads.

    Every saved dataset is written to the directory as JSON and kept in memory for later reads,
    so a service restarted against the same directory still serves what earlier runs ingested.
    """

    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self._directory = directory
        self._datasets: dict[str, Dataset] = {}
        self._lock = threading.Lock()

    def save(self, origin: bytes, dataset: Dataset) -> str:
        """Store (or replace) the dataset for `origin`, on disk and in memory, and return its id."""
        dataset_id = dataset_id_for(origin)
        with self._lock:
            self._path(dataset_id).write_text(json.dumps(asdict(dataset)), encoding="utf-8")
            self._datasets[dataset_id] = dataset
        return dataset_id

    def holds(self, dataset_id: str) -> bool:
        """Whether a dataset is already stored under this id — the question the cache asks."""
        with self._lock:
            return dataset_id in self._datasets or self._path(dataset_id).exists()

    def require(self, dataset_id: str) -> Dataset:
        """Return the stored dataset, reporting an id that was never converted as 404."""
        with self._lock:
            dataset = self._datasets.get(dataset_id) or self._recall(dataset_id)
        if dataset is None:
            raise DatagateError(404, f"Unknown dataset id: {dataset_id!r}")
        return dataset

    def _recall(self, dataset_id: str) -> Dataset | None:
        """Read a dataset an earlier run saved, keeping it in memory for the reads that follow."""
        path = self._path(dataset_id)
        if not path.exists():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        dataset = Dataset(record["columns"], record["rows"])
        self._datasets[dataset_id] = dataset
        return dataset

    def _path(self, dataset_id: str) -> Path:
        return self._directory / f"{dataset_id}{RECORD_SUFFIX}"
