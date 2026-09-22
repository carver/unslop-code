"""The wall-clock budget a single dataset query is allowed to spend."""

import time

from .errors import DatagateError

QUERY_TIMEOUT_SECONDS = 5.0


class Deadline:
    """The instant a query must finish by, carried through the row scan.

    The budget is read when the deadline is created, so a deployment can lower
    `QUERY_TIMEOUT_SECONDS` for every request without threading a value through
    the request path.
    """

    def __init__(self):
        self._expires_at = time.perf_counter() + QUERY_TIMEOUT_SECONDS

    def check(self):
        """Raise a 400 `DatagateError` once the query has outlived its budget."""
        if time.perf_counter() > self._expires_at:
            raise DatagateError(400, "Query timed out; narrow the filters or the page size.")
