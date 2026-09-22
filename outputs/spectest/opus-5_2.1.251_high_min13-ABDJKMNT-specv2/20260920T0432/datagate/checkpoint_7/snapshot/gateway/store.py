"""Dataset identity and the on-disk dataset store."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import ConfigError
from .tabular import Cell


@dataclass(frozen=True)
class Dataset:
    """One converted CSV: its id, the columns and typed rows to serve, and the
    enrichment metadata if it was ingested with `enrich=yes`."""

    id: str
    columns: list[str]
    rows: list[list[Cell]] = field(default_factory=list)
    metadata: dict | None = None

    @property
    def enriched(self) -> bool:
        return self.metadata is not None


ID_LENGTH = 16
# Ids are digests, so anything else names no dataset and never reaches the disk.
IDENTIFIER = re.compile(f"[0-9a-f]{{{ID_LENGTH}}}")


def dataset_id(source: str) -> str:
    """Id for a source URL, derived from the URL string alone.

    Being a pure function of the string, the same `source` maps to the same id
    for every request and across restarts.
    """
    return _digest(source.encode("utf-8"))


def content_id(raw: bytes) -> str:
    """Id for an uploaded file, derived from the file's bytes.

    Uploads arrive without a stable name of their own, so their identity is
    their content: re-uploading the same bytes resolves to the same dataset.
    """
    return _digest(raw)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:ID_LENGTH]


class DatasetStore:
    """Datasets held as one JSON file per id under the storage directory.

    Writing each dataset out as it is ingested is what lets a later process
    reusing the same directory serve it, and it makes the store the cache that
    `/convert` consults for a source it has already seen.
    """

    def __init__(self, directory: str):
        self._directory = Path(directory)
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ConfigError(f"STORAGE_DIR '{directory}' is unusable: {exc}") from exc

    def save(self, dataset: Dataset) -> None:
        """Store `dataset`, replacing any earlier conversion of the same source.

        The metadata is stored alongside the rows, so enrichment survives both a
        restart and the cache hit a later request is answered from.
        """
        body = {
            "columns": dataset.columns,
            "rows": dataset.rows,
            "metadata": dataset.metadata,
        }
        self._path(dataset.id).write_text(json.dumps(body), encoding="utf-8")

    def get(self, identifier: str) -> Dataset | None:
        """The stored dataset, or `None` when the id names nothing usable.

        A file that is absent, unreadable or no longer a stored dataset all say
        the same thing to a caller, and the route turns that into a 404.
        """
        if not IDENTIFIER.fullmatch(identifier):
            return None
        try:
            stored = json.loads(self._path(identifier).read_text(encoding="utf-8"))
            return Dataset(
                id=identifier,
                columns=stored["columns"],
                rows=stored["rows"],
                metadata=stored.get("metadata"),
            )
        except (OSError, ValueError, KeyError):
            return None

    def _path(self, identifier: str) -> Path:
        return self._directory / f"{identifier}.json"
