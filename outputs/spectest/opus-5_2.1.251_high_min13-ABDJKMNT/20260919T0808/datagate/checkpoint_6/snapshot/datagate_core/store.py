"""Dataset identity and the on-disk dataset store."""

import hashlib
import re
from pathlib import Path

from datagate_core.persistence import ensure_directory, read_table, write_table
from datagate_core.tables import Table

ID_LENGTH = 16

#: Ids are truncated hex digests, so nothing else can name a stored dataset.
ID_PATTERN = re.compile(rf"[0-9a-f]{{{ID_LENGTH}}}\Z")


def dataset_id(identity: str | bytes) -> str:
    """Return the stable id for a dataset's identity.

    That identity is the `source` URL string for `/convert` (T1) and the file's
    own bytes for `/upload`, so re-uploading the same file lands on one id (T34).
    Deriving the id from the identity alone is also what lets a restarted
    process find the file an earlier one wrote under the same name.
    """
    material = identity.encode("utf-8") if isinstance(identity, str) else identity
    return hashlib.sha256(material).hexdigest()[:ID_LENGTH]


class DatasetStore:
    """Parsed tables kept as one file per dataset under a storage directory.

    Datasets live on disk rather than in the process, so both `/datasets/<id>`
    and the `/convert` cache that `has()` answers survive a restart reusing the
    same directory (T71).
    """

    def __init__(self, directory: Path) -> None:
        self._directory = ensure_directory(directory)

    def save(self, identity: str | bytes, table: Table) -> str:
        """Store `table` under the id of `identity`, replacing any earlier version."""
        identifier = dataset_id(identity)
        write_table(self._path(identifier), table)
        return identifier

    def has(self, identifier: str) -> bool:
        """Whether a dataset is already stored under `identifier` (a cache hit)."""
        return self._path(identifier).exists()

    def get(self, identifier: str) -> Table | None:
        """The table stored under `identifier`, or `None` when nothing is stored there.

        `identifier` comes straight out of a request path, so a name that is not
        an id at all names no dataset and never reaches the filesystem.
        """
        if not ID_PATTERN.match(identifier):
            return None
        path = self._path(identifier)
        return read_table(path) if path.exists() else None

    def _path(self, identifier: str) -> Path:
        return self._directory / f"{identifier}.json"
