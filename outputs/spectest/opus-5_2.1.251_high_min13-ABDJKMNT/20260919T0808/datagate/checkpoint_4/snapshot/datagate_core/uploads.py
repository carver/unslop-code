"""Reading the uploaded file out of a `POST /upload` multipart request."""

from flask import Request

from datagate_core.errors import InvalidRequestError, UnsupportedMediaTypeError

MULTIPART = "multipart/form-data"

#: The accepted part names, searched in this order when a request carries both (T42).
FILE_FIELDS = ("file", "attachment")


def uploaded_bytes(request: Request) -> bytes:
    """The bytes of the uploaded file part, or the error its absence maps onto.

    A body that is not a multipart form is a 415; one that is multipart but
    carries neither accepted part - because it is malformed, or simply names its
    part something else - is a 400.
    """
    if request.mimetype != MULTIPART:
        raise UnsupportedMediaTypeError(f"/upload expects a {MULTIPART} body")

    for field in FILE_FIELDS:
        if field in request.files:
            return request.files[field].read()
        if field in request.form:
            return request.form[field].encode("utf-8")
    raise InvalidRequestError("multipart body carries no 'file' or 'attachment' part")
