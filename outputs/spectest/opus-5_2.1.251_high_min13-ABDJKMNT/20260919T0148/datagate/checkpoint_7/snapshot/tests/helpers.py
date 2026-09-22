"""Request helpers shared by the fixtures and by tests that build their own client."""

import io


def post_upload(client, payload, field="file", filename="data.csv", **kwargs):
    """POST `payload` to `/upload` on `client` as a multipart part named `field`."""
    body = payload.encode("utf-8") if isinstance(payload, str) else payload
    return client.post(
        "/upload",
        data={field: (io.BytesIO(body), filename)},
        content_type="multipart/form-data",
        **kwargs,
    )
