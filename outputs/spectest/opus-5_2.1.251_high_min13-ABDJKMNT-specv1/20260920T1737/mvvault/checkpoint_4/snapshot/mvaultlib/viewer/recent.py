"""The vaults visited through the viewer, newest first.

The list is kept in the directory the viewer serves, beside the vaults it names,
so it outlives both a closed browser and a restarted server.
"""

import json
from pathlib import Path

RECENT_NAME = ".mvault-recent.json"

#: How many vaults the landing page remembers.
RECENT_LIMIT = 10


class RecentVaults:
    """The recently visited vault names of one served directory."""

    def __init__(self, directory):
        self.path = Path(directory) / RECENT_NAME

    def names(self):
        """The stored names, newest first; a store yet to be written is empty."""
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [name for name in stored if isinstance(name, str)][:RECENT_LIMIT]

    def record(self, name):
        """Move `name` to the front of the list and persist it."""
        names = [name] + [other for other in self.names() if other != name]
        self.path.write_text(json.dumps(names[:RECENT_LIMIT]), encoding="utf-8")
