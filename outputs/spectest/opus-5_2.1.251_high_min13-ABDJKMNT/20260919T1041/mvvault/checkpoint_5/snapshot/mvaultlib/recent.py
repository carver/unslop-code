"""The viewer's list of recently visited vaults.

The list lives beside the vaults the viewer serves, so a browser that is
started again later still sees what was visited before.
"""

import json
from pathlib import Path

STORE_NAME = ".mvault-recent.json"

#: How many vaults the landing page remembers.
LIMIT = 20


def record(name):
    """Move `name` to the front of the list, dropping the oldest names."""
    remembered = [name, *(other for other in names() if other != name)]
    Path(STORE_NAME).write_text(json.dumps(remembered[:LIMIT], indent=2) + "\n", encoding="utf-8")


def names():
    """The remembered vault names, most recently visited first."""
    try:
        return json.loads(Path(STORE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
