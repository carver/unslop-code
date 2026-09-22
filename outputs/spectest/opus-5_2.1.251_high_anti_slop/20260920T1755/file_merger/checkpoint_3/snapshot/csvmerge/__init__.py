"""Schema-aligning merge sorter for CSV, TSV, JSON Lines and Parquet inputs.

The pipeline is: identify each input (``formats``) and open it as a stream of
rows (``sources``, ``parquetio``), resolve a schema (``schema``), cast the
rows into records (``records``) tagged with the partition directory they
belong in (``partition``), order them with a memory-bounded sort
(``sorting``), and write the result as one CSV or a tree of part files
(``csvio``, ``output``).
"""

from csvmerge.errors import MergeError

__all__ = ["MergeError"]
