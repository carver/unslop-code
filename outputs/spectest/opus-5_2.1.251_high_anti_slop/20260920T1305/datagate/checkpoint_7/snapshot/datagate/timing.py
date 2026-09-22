"""The wall-clock budget that bounds how long one dataset query may run."""

import time

from .errors import DataGateError


class Deadline:
    """A time budget for one query, checked while its rows are being worked through."""

    def __init__(self, seconds: float) -> None:
        self._expires_at = time.perf_counter() + seconds

    def check(self) -> None:
        """Raise a 400 error once the budget has run out."""
        if time.perf_counter() > self._expires_at:
            raise DataGateError("query timed out", 400)
