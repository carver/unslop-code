"""Storing datasets as one JSON file each, under the configured storage directory."""

import json
from pathlib import Path

from datagate_core.tables import Table


def ensure_directory(directory: Path) -> Path:
    """Create `directory` and any missing parents, and return it."""
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_table(path: Path, table: Table) -> None:
    """Persist a table's columns and already-inferred cell values as JSON.

    Storing the inferred values rather than the source bytes is what makes a
    reloaded dataset filter and sort exactly as the freshly parsed one did (T71).
    """
    payload = {"columns": table.columns, "rows": table.rows}
    path.write_text(json.dumps(payload), encoding="utf-8")


def read_table(path: Path) -> Table:
    """Rebuild the table that `write_table` left at `path`."""
    stored = json.loads(path.read_text(encoding="utf-8"))
    return Table(columns=stored["columns"], rows=stored["rows"])
