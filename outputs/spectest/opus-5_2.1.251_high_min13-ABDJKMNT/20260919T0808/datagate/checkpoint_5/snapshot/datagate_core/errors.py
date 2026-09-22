"""Application errors, each carrying the HTTP status the spec assigns to it."""


class DataGateError(Exception):
    """Base class for errors that map onto a JSON error response."""

    status = 400


class InvalidRequestError(DataGateError):
    """A required query parameter is missing or unusable."""


class InvalidURLError(DataGateError):
    """The `source` value is not a fetchable HTTP(S) URL."""


class CharsetError(DataGateError):
    """The requested `charset` is unknown, or it cannot decode the source bytes."""


class NonTabularError(DataGateError):
    """The fetched document is not a delimited table with a header and data."""


class UnsupportedFormatError(DataGateError):
    """The bytes announce a format datagate cannot read as a table."""


class QueryTimeoutError(DataGateError):
    """A dataset query outlived the wall-clock budget it may run in."""


class FetchError(DataGateError):
    """The source could not be retrieved, or the remote answered with an error."""

    status = 404


class DatasetNotFoundError(DataGateError):
    """No dataset has been stored under the requested id."""

    status = 404


class UnsupportedMediaTypeError(DataGateError):
    """`POST /upload` was sent something other than a multipart form."""

    status = 415
