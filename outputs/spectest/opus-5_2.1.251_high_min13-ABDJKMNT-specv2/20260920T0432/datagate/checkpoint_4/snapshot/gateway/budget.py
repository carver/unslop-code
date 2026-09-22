"""The wall-clock budget a single dataset read is allowed to spend."""

import time

from .errors import ApiError

QUERY_BUDGET_SECONDS = 5.0


class Deadline:
    """The moment a read must be abandoned, as a query timeout.

    Created once per request and consulted while the rows are scanned, which is
    the stage whose cost grows with the dataset size and the number of filters.
    """

    def __init__(self):
        self._expires_at = time.perf_counter() + QUERY_BUDGET_SECONDS

    def check(self) -> None:
        """Raise `ApiError(400)` once the budget for this read is spent."""
        if time.perf_counter() >= self._expires_at:
            raise ApiError(400, f"query timed out after {QUERY_BUDGET_SECONDS}s")
