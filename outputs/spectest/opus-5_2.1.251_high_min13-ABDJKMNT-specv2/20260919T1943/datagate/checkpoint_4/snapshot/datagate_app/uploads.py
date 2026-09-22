"""Reading the payload out of a `POST /upload` request."""

from flask import Request

from .errors import DataGateError
from .formats import SourceDocument

FILE_FIELDS = ("file", "attachment")
MULTIPART_TYPE = "multipart/form-data"


def uploaded_document(request: Request) -> SourceDocument:
    """Take the uploaded file part, preferring `file` over `attachment` (T39).

    A request that never claimed to be multipart is a media-type problem, so it
    is a 415. Once it has claimed it, a body the parser cannot use and a body
    carrying neither field are both malformed forms and so both 400 (T48).
    """
    if request.mimetype != MULTIPART_TYPE:
        declared = request.mimetype or "no media type"
        raise DataGateError(f"/upload needs a {MULTIPART_TYPE} body, got {declared}", 415)
    for field in FILE_FIELDS:
        part = request.files.get(field)
        if part is not None:
            return SourceDocument(part.read(), part.mimetype)
    raise DataGateError(f"Multipart form carries no file in field {' or '.join(FILE_FIELDS)}", 400)
