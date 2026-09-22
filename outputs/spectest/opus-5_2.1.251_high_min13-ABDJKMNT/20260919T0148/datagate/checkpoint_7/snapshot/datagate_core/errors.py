"""The error types used to carry a failure out of the pipeline or out of startup."""


class DatagateError(Exception):
    """A failure that maps onto a documented status code and error message."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class ConfigurationError(ValueError):
    """A configuration value or file the service refuses to start with."""
