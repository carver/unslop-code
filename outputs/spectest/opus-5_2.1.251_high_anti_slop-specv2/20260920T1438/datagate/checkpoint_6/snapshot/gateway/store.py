"""Stored datasets, keyed by a deterministic id and kept on disk."""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

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
    """One JSON file per dataset under a directory, created if it is missing.

    Nothing is held in memory, so datasets outlive the process and a service
    restarted on the same directory serves the ids it served before.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def save(self, dataset: Dataset) -> str:
        """Store ``dataset``, replacing any dataset of the same origin."""
        identifier = dataset_id(dataset.origin)
        self._path(identifier).write_text(
            json.dumps(asdict(dataset)), encoding="utf-8"
        )
        return identifier

    def get(self, identifier: str) -> Dataset | None:
        """Return the stored dataset, or ``None`` when the id is unknown."""
        path = self._path(identifier)
        if not path.is_file():
            return None
        return Dataset(**json.loads(path.read_text(encoding="utf-8")))

    def _path(self, identifier: str) -> Path:
        return self._directory / f"{identifier}.json"
