"""Storage for converted datasets, kept in memory and mirrored to disk."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

RECORD_SUFFIX = ".json"


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
    """Datasets keyed by a hash of their origin, backed by a directory.

    The key is derived from the origin alone, so ingesting the same source
    twice yields the same endpoint and replaces the previously stored rows.
    Every dataset is written to the storage directory as one JSON record and
    read back when a store opens over that directory again, so datasets
    outlive the run that converted them.
    """

    def __init__(self, directory: Path):
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._datasets = {
            record.stem: _read(record) for record in self._directory.glob(f"*{RECORD_SUFFIX}")
        }

    @staticmethod
    def identify(origin: str) -> str:
        return hashlib.sha256(origin.encode("utf-8")).hexdigest()[:16]

    def add(self, dataset: Dataset) -> str:
        dataset_id = self.identify(dataset.origin)
        self._datasets[dataset_id] = dataset
        _write(self._directory / f"{dataset_id}{RECORD_SUFFIX}", dataset)
        return dataset_id

    def get(self, dataset_id: str) -> Dataset | None:
        return self._datasets.get(dataset_id)


def _write(record: Path, dataset: Dataset) -> None:
    """Store a dataset as JSON, each row as its line number and its values."""
    body = {
        "origin": dataset.origin,
        "columns": dataset.columns,
        "rows": [[row.rowid, row.values] for row in dataset.rows],
    }
    record.write_text(json.dumps(body), encoding="utf-8")


def _read(record: Path) -> Dataset:
    stored = json.loads(record.read_text(encoding="utf-8"))
    rows = [Row(rowid, values) for rowid, values in stored["rows"]]
    return Dataset(stored["origin"], stored["columns"], rows)
