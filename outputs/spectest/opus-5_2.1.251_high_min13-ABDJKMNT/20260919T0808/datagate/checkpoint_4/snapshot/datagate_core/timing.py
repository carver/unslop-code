"""The wall-clock budget a single dataset query runs under (see AMBIGUITIES T27)."""

import time

from datagate_core.errors import QueryTimeoutError

#: Seconds one `GET /datasets/<id>` may spend scanning, sorting and paginating rows.
QUERY_TIMEOUT_SECONDS = 5.0


class Deadline:
    """Times one dataset query and cuts it short once its budget is spent."""

    def __init__(self) -> None:
        self._started = time.perf_counter()
        self._budget = QUERY_TIMEOUT_SECONDS

    @property
    def elapsed_ms(self) -> float:
        """Milliseconds spent so far, reported to the client as `query_ms`."""
        return round(self._elapsed() * 1000, 3)

    def check(self) -> None:
        """Abandon the query once it has outlived its budget."""
        if self._elapsed() > self._budget:
            raise QueryTimeoutError(f"query exceeded its {self._budget}s time budget")

    def _elapsed(self) -> float:
        return time.perf_counter() - self._started
