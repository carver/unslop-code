"""The single error type the HTTP layer knows how to render."""


class DataGateError(Exception):
    """An error that maps directly onto an HTTP status and a JSON envelope."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status
