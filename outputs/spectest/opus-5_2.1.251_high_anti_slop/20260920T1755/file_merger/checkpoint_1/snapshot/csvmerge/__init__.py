"""Schema-aligning CSV merge sorter.

The pipeline is: resolve a schema (``schema``), read and cast rows into
records (``records``), order them with a memory-bounded sort (``sorting``),
and write the result (``csvio``).
"""

from csvmerge.errors import MergeError

__all__ = ["MergeError"]
