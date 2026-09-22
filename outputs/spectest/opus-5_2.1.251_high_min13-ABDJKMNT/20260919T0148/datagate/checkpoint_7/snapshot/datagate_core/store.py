"""Dataset identity and the in-memory table store."""

import hashlib
from dataclasses import dataclass

ID_LENGTH = 16


def dataset_id(source_url):
    """Map a source URL string to its stable dataset id."""
    return content_id(source_url.encode("utf-8"))


def content_id(raw):
    """Map uploaded file bytes to their stable dataset id.

    Uploads are content-addressed, so re-uploading the same bytes lands on the same
    dataset whatever the part was named (AMBIGUITIES T36).
    """
    return hashlib.sha256(raw).hexdigest()[:ID_LENGTH]


@dataclass(frozen=True)
class Dataset:
    """A parsed table: header names, typed rows, and the metadata of an enriched one.

    `metadata` is None for a dataset ingested without `enrich=yes`, which is what
    keeps the enrichment fields out of its responses entirely.
    """

    columns: list
    rows: list
    metadata: dict | None = None


class DatasetStore:
    """Converted datasets, held in memory and mirrored into a `DatasetFiles` when given.

    Backing the store with files is what lets a dataset outlive the process that
    ingested it, so a restart over the same `STORAGE_DIR` still answers for it
    (AMBIGUITIES T71).
    """

    def __init__(self, files=None):
        self._datasets = {}
        self._files = files

    def put(self, identifier, dataset):
        self._datasets[identifier] = dataset
        if self._files is not None:
            self._files.write(identifier, dataset)

    def get(self, identifier):
        """Return the dataset for `identifier`, or None if it was never converted.

        The first miss after a restart is served from the storage directory, and the
        dataset stays in memory from then on.
        """
        if identifier in self._datasets:
            return self._datasets[identifier]

        dataset = None if self._files is None else self._files.read(identifier)
        if dataset is not None:
            self._datasets[identifier] = dataset
        return dataset
