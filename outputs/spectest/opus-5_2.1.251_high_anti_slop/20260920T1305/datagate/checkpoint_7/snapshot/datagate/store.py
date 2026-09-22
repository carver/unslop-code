"""Registry of converted datasets, keyed by a deterministic id and kept on disk."""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .enrichment import Metadata
from .errors import DataGateError
from .values import Value

ID_LENGTH = 16


@dataclass(frozen=True)
class Dataset:
    """A parsed table, with columns and rows in source order.

    ``origin`` names where the table came from -- the source URL for a conversion, or a
    digest of the file's bytes for an upload -- and decides the dataset's id.

    The metadata fields hold what an ``enrich=yes`` ingestion computed, and are absent
    from a dataset ingested without enrichment.
    """

    origin: str
    columns: list[str]
    rows: list[list[Value]]
    dataset_summary: dict | None = None
    column_details: dict | None = None

    @property
    def enriched(self) -> bool:
        """Return whether this dataset was ingested with enrichment."""
        return self.dataset_summary is not None

    def metadata(self) -> Metadata:
        """Return the metadata fields to report, leaving out the ones not computed."""
        fields = {
            "dataset_summary": self.dataset_summary,
            "column_details": self.column_details,
        }
        return {name: value for name, value in fields.items() if value is not None}


def dataset_id(origin: str) -> str:
    """Return the id an ``origin`` always maps to."""
    return hashlib.sha256(origin.encode("utf-8")).hexdigest()[:ID_LENGTH]


class DatasetStore:
    """Stores each dataset as one JSON document under the configured storage directory.

    Re-ingesting an origin overwrites its document, and datasets stay queryable across
    restarts as long as the same directory is used again. The directory is created if
    it does not exist yet.
    """

    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._directory = directory

    def add(self, dataset: Dataset) -> str:
        """Store ``dataset`` and return the id under which it can be queried."""
        identifier = dataset_id(dataset.origin)
        document = json.dumps(asdict(dataset))
        self._document(identifier).write_text(document, encoding="utf-8")
        return identifier

    def has(self, identifier: str) -> bool:
        """Return whether a dataset is already stored under ``identifier``."""
        return self._document(identifier).is_file()

    def holds(self, identifier: str, *, enriched: bool) -> bool:
        """Return whether a stored dataset can answer a request asking for ``enriched``.

        A dataset stored without ingestion metadata cannot answer a request for it, so
        ``enrich=yes`` over such a dataset re-ingests the source and upgrades it.
        """
        return self.has(identifier) and (not enriched or self.get(identifier).enriched)

    def get(self, identifier: str) -> Dataset:
        """Return the dataset stored under ``identifier``, or raise a 404 error."""
        if not self.has(identifier):
            raise DataGateError(f"unknown dataset {identifier!r}", 404)
        stored = json.loads(self._document(identifier).read_text(encoding="utf-8"))
        return Dataset(**stored)

    def _document(self, identifier: str) -> Path:
        """Return the file a dataset's id is stored in."""
        return self._directory / f"{identifier}.json"
