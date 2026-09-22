"""Reading the file a client posts to ``/upload`` out of its multipart request."""

import hashlib
from dataclasses import dataclass

from flask import Request

from .errors import DataGateError

FILE_FIELDS = ("file", "attachment")
MULTIPART_TYPE = "multipart/form-data"


@dataclass(frozen=True)
class Upload:
    """An uploaded file's bytes together with the origin key its content maps to."""

    data: bytes
    origin: str


def read_upload(request: Request) -> Upload:
    """Return the file posted under the ``file`` or ``attachment`` form field.

    The origin key is derived from the file's bytes, so re-posting the same file always
    addresses the same dataset. A request that is not multipart form data raises a 415
    error; one whose body is malformed or carries neither field raises a 400 error.
    """
    if request.mimetype != MULTIPART_TYPE:
        raise DataGateError(
            f"upload must be {MULTIPART_TYPE}, got {request.mimetype or 'no'} content",
            415,
        )

    for field in FILE_FIELDS:
        posted = request.files.get(field)
        if posted is not None:
            data = posted.read()
            return Upload(data=data, origin=f"upload:{hashlib.sha256(data).hexdigest()}")

    listed = " or ".join(repr(name) for name in FILE_FIELDS)
    raise DataGateError(f"upload must carry a {listed} file field", 400)
