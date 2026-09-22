"""Persistence of datasets under `STORAGE_DIR`: one JSON document per dataset id."""

import json
from pathlib import Path

from .errors import ConfigurationError
from .store import Dataset

SUFFIX = ".json"


class DatasetFiles:
    """The storage directory, created at startup and reusable by a later process."""

    def __init__(self, directory):
        """Open `directory`, creating it and any missing parent (AMBIGUITIES T72)."""
        self._directory = Path(directory)
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ConfigurationError(
                f"Cannot use STORAGE_DIR {directory}: {error.strerror}."
            ) from error

    def write(self, identifier, dataset):
        """Store `dataset` so that reusing this directory brings it back."""
        document = {
            "columns": dataset.columns,
            "rows": dataset.rows,
            "metadata": dataset.metadata,
        }
        self._path(identifier).write_text(json.dumps(document), encoding="utf-8")

    def read(self, identifier):
        """The dataset stored under `identifier`, or None when nothing is stored."""
        path = self._path(identifier)
        if not path.is_file():
            return None

        document = json.loads(path.read_text(encoding="utf-8"))
        return Dataset(document["columns"], document["rows"], document.get("metadata"))

    def _path(self, identifier):
        return self._directory / f"{identifier}{SUFFIX}"
