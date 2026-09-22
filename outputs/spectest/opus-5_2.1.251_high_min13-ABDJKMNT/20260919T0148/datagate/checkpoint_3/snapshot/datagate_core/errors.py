"""The single error type used to carry an HTTP status out of the pipeline."""


class DatagateError(Exception):
    """A failure that maps onto a documented status code and error message."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message
