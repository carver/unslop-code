"""Error type shared by the datagate modules."""


class DatagateError(Exception):
    """An error that maps directly onto an HTTP status and a client-facing message."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message
