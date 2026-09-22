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
# Ingestion-time metadata, held as the fragment the dataset endpoint merges into its reply:
# a `dataset_summary` always, plus `column_details` for the formats that have per-column types.
Enrichment = dict[str, object]


@dataclass(frozen=True)
class Dataset:
    """A parsed table: header names plus data rows, both in source order.

    `enrichment` carries the metadata of an ingestion that was asked to enrich, and is None for
    one that was not; it is stored alongside the table so every later read reports the same.
    """

    columns: list[str]
    rows: list[Row]
    enrichment: Enrichment | None = None


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

    def holds(self, dataset_id: str, enriched: bool) -> bool:
        """Whether a stored dataset can answer a `/convert` as it stands — the cache's question.

        A request for an enriched ingestion is only answered from the store when the stored
        dataset carries its metadata; one converted without it is ingested again so that the
        metadata is recorded rather than missing from every read that follows.
        """
        dataset = self._load(dataset_id)
        return dataset is not None and (dataset.enrichment is not None or not enriched)

    def require(self, dataset_id: str) -> Dataset:
        """Return the stored dataset, reporting an id that was never converted as 404."""
        dataset = self._load(dataset_id)
        if dataset is None:
            raise DatagateError(404, f"Unknown dataset id: {dataset_id!r}")
        return dataset

    def _load(self, dataset_id: str) -> Dataset | None:
        """Return the dataset held in memory, falling back to a record an earlier run wrote."""
        with self._lock:
            return self._datasets.get(dataset_id) or self._recall(dataset_id)

    def _recall(self, dataset_id: str) -> Dataset | None:
        """Read a dataset an earlier run saved, keeping it in memory for the reads that follow."""
        path = self._path(dataset_id)
        if not path.exists():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        dataset = Dataset(record["columns"], record["rows"], record.get("enrichment"))
        self._datasets[dataset_id] = dataset
        return dataset

    def _path(self, dataset_id: str) -> Path:
        return self._directory / f"{dataset_id}{RECORD_SUFFIX}"
