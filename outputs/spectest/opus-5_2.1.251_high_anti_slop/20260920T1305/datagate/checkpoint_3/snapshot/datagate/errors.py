"""The single error type used to report failures back to clients."""


class DataGateError(Exception):
    """An error that maps directly onto an HTTP status and a JSON message."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
