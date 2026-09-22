"""Storing datasets as one JSON file each, under the configured storage directory."""

import json
from pathlib import Path

from datagate_core.datasets import Dataset
from datagate_core.tables import Table


def ensure_directory(directory: Path) -> Path:
    """Create `directory` and any missing parents, and return it."""
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_dataset(path: Path, dataset: Dataset) -> None:
    """Persist a dataset's columns, already-inferred cell values and metadata.

    Storing the inferred values rather than the source bytes is what makes a
    reloaded dataset filter and sort exactly as the freshly parsed one did
    (T71); storing the metadata beside them is what lets `/convert` tell an
    enriched dataset from a plain one without ingesting the source again.
    """
    payload = {
        "columns": dataset.table.columns,
        "rows": dataset.table.rows,
        "metadata": dataset.metadata,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def read_dataset(path: Path) -> Dataset:
    """Rebuild the dataset that `write_dataset` left at `path`."""
    stored = json.loads(path.read_text(encoding="utf-8"))
    table = Table(columns=stored["columns"], rows=stored["rows"])
    return Dataset(table, stored["metadata"])
