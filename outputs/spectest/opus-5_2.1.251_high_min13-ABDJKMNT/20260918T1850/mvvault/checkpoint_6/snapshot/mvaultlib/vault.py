"""The vault directory: `catalog.json`, its backup, and version-aware loading."""

import json
from pathlib import Path

from .catalog import new_catalog
from .errors import MvaultError
from .legacy import load_catalog

CATALOG_FILENAME = "catalog.json"
BACKUP_FILENAME = "catalog.bak"

#: Directories the download phase fills; both are created on first use.
MEDIA_DIRNAME = "media"
PREVIEWS_DIRNAME = "previews"


class Vault:
    """A vault directory holding `catalog.json` and its `catalog.bak` backup."""

    def __init__(self, name, root=None):
        """The vault called `name`, under `root` or under the working directory."""
        self.name = name
        self.path = Path(name) if root is None else Path(root, name)
        self.catalog_path = self.path / CATALOG_FILENAME
        self.backup_path = self.path / BACKUP_FILENAME
        self.media_path = self.path / MEDIA_DIRNAME
        self.previews_path = self.path / PREVIEWS_DIRNAME

    def create(self, source_url):
        """Create the vault directory with an empty catalog.

        Refuses to touch anything that already exists at the vault path.
        """
        if self.path.exists():
            raise MvaultError(f"vault {self.name!r} already exists")
        self.path.mkdir(parents=True)
        self._write(new_catalog(source_url))

    def read(self):
        """The stored catalog as parsed JSON, with no version handling at all.

        This is what a format-aware reader such as `digest` wants: the document
        exactly as written, whichever version it declares.
        """
        if not self.catalog_path.is_file():
            raise MvaultError(f"vault {self.name!r} is missing or has no {CATALOG_FILENAME}")
        try:
            return json.loads(self.catalog_path.read_text())
        except (OSError, ValueError) as error:
            raise MvaultError(f"vault {self.name!r} is not valid: {error}") from error

    def load(self):
        """Read `catalog.json` as a v3 catalog, and whether it had to be migrated.

        A v1 or v2 catalog is converted in memory only. Nothing is written here,
        so a caller that merely reads leaves the file exactly as it found it.
        """
        try:
            return load_catalog(self.read())
        except ValueError as error:
            raise MvaultError(f"vault {self.name!r} is not valid: {error}") from error

    def save(self, catalog):
        """Back up the existing catalog, then write the new one over it.

        A backup that cannot be written aborts the save, leaving the catalog on
        disk as it was.
        """
        if self.catalog_path.is_file():
            try:
                self.backup_path.write_bytes(self.catalog_path.read_bytes())
            except OSError as error:
                raise MvaultError(
                    f"vault {self.name!r}: cannot write {BACKUP_FILENAME}: {error}"
                ) from error
        self._write(catalog)

    def _write(self, catalog):
        self.catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")
