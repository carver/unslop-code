"""The vaults the viewer landing page offers as recently visited.

Visits are kept beside the vaults themselves, so the list a browser saw
survives both the browser session and the server that served it.
"""

import json
from pathlib import Path

#: File the viewer keeps its visit history in, inside the served directory.
RECENT_FILENAME = ".mvault-recent.json"

#: How many visits the landing page remembers.
RECENT_LIMIT = 10


def read(directory: Path) -> list[str]:
    """Vaults visited through the viewer, most recently visited first.

    A history that was never written, or no longer reads as one, counts as no
    visits at all: it is a convenience, never something a page depends on.
    """
    try:
        stored = json.loads((directory / RECENT_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return stored[:RECENT_LIMIT] if isinstance(stored, list) else []


def visit(directory: Path, name: str) -> None:
    """Record ``name`` as the vault most recently visited."""
    ordered = [name] + [other for other in read(directory) if other != name]
    path = directory / RECENT_FILENAME
    path.write_text(json.dumps(ordered[:RECENT_LIMIT]) + "\n", encoding="utf-8")
