"""Pulling the uploaded payload out of a multipart `POST /upload` body."""

from .errors import DatagateError

MULTIPART = "multipart/form-data"
FIELDS = ("file", "attachment")


def uploaded_bytes(request):
    """Return the bytes of the `file` or `attachment` part of a multipart request.

    The media type is checked before the body is touched, so a request that is not
    multipart at all is a 415 while a multipart body that cannot be parsed, or that
    carries neither field, is a 400 (AMBIGUITIES T38). A part sent without a
    filename counts as the field too (AMBIGUITIES T46), and `file` wins when both
    fields are present (AMBIGUITIES T37).
    """
    if request.mimetype != MULTIPART:
        raise DatagateError(
            415, f"Uploads must be sent as {MULTIPART}, got {request.mimetype or 'nothing'!r}."
        )

    for field in FIELDS:
        if field in request.files:
            return request.files[field].read()
        if field in request.form:
            return request.form[field].encode("utf-8")

    raise DatagateError(400, "Multipart upload must carry a 'file' or an 'attachment' part.")
