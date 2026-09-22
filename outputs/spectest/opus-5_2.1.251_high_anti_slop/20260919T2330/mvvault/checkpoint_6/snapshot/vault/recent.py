"""The vaults visited through the viewer, remembered across browser sessions.

The list lives in a small JSON file beside the vault directories, so a browser
coming back later still sees what it visited before.
"""

import json
from pathlib import Path

STORE_NAME = ".mvault-recent.json"
#: How many visited vaults the landing page remembers.
LIMIT = 10


class RecentVaults:
    """Vault names visited through the viewer, most recently visited first."""

    def __init__(self, path=None):
        self._path = Path(path or STORE_NAME)

    def names(self):
        """Visited vault names, newest first; empty until the first visit is recorded."""
        if not self._path.is_file():
            return []
        return json.loads(self._path.read_text(encoding="utf-8"))

    def record(self, name):
        """Move ``name`` to the front of the list and store the list back."""
        names = [name] + [visited for visited in self.names() if visited != name]
        self._path.write_text(json.dumps(names[:LIMIT], indent=2) + "\n", encoding="utf-8")
