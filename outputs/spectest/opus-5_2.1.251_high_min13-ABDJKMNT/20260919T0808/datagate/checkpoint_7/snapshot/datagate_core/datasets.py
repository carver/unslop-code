"""What a stored dataset is: the parsed table, plus whatever enrichment added."""

from dataclasses import dataclass

from datagate_core.tables import Table


@dataclass(frozen=True)
class Dataset:
    """A table and its ingestion metadata, which is empty unless enriched.

    An empty `metadata` is what "non-enriched" means both on disk and to the
    `/convert` cache check, and it is why a non-enriched dataset response has no
    metadata fields to show rather than empty ones.
    """

    table: Table
    metadata: dict
