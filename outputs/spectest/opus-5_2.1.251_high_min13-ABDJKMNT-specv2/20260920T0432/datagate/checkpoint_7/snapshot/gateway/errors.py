"""The single error type the request pipeline raises."""


class ApiError(Exception):
    """A failure that maps directly onto an HTTP status and the JSON envelope.

    Every stage of ingestion (URL validation, fetching, decoding, parsing)
    signals refusal with this, so the Flask layer needs one error handler.
    """

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message
