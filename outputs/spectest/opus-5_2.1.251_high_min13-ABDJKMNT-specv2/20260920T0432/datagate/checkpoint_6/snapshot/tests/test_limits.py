"""`MAX_SOURCE_SIZE`: the byte limit on files reaching `/convert` and `/upload`."""

import io

BODY = "name,age\nada,36\n"
BODY_SIZE = len(BODY.encode("utf-8"))
ROWS = [["ada", 36]]


def convert(client, origin, path, body=BODY, **params):
    """Serve `body` at `path` and convert it through `client`."""
    source = origin.serve(path, body)
    return client.get("/convert", query_string={"source": source, **params})


def upload(client, body=BODY, filename="table.csv"):
    """POST `body` to /upload as a multipart file part."""
    return client.post(
        "/upload",
        data={"file": (io.BytesIO(body.encode("utf-8")), filename)},
        content_type="multipart/form-data",
    )


# Spec: "Enforced for `/convert` and `/upload`: file size `= limit` accepted."
# Context: a source whose downloaded bytes are exactly the configured limit.
def test_convert_accepts_a_file_at_the_limit(configured_client, origin):
    client = configured_client(MAX_SOURCE_SIZE=str(BODY_SIZE))
    response = convert(client, origin, "/limit-exact.csv")
    assert response.status_code == 200
    assert client.get(response.get_json()["endpoint"]).get_json()["rows"] == ROWS


# Spec: "file size `= limit` accepted."
# Context: the same boundary on an upload, measured on the file part (T56).
def test_upload_accepts_a_file_at_the_limit(configured_client):
    client = configured_client(MAX_SOURCE_SIZE=str(BODY_SIZE))
    assert upload(client).status_code == 200


# Spec: "file size `> limit` => `HTTP 400` with standard envelope."
# Context: one byte over the limit, on /convert.
def test_convert_refuses_a_file_over_the_limit(configured_client, origin):
    client = configured_client(MAX_SOURCE_SIZE=str(BODY_SIZE - 1))
    response = convert(client, origin, "/limit-over.csv")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Spec: "file size `> limit` => `HTTP 400` with standard envelope."
# Context: one byte over the limit, on /upload.
def test_upload_refuses_a_file_over_the_limit(configured_client):
    client = configured_client(MAX_SOURCE_SIZE=str(BODY_SIZE - 1))
    assert upload(client).status_code == 400


# Spec: "| Size exceeded | 400 | `{"ok": false, "error": "<message>"}` |"
# Context: the refusal carries the standard envelope and nothing else.
def test_the_refusal_uses_the_standard_envelope(configured_client, origin):
    client = configured_client(MAX_SOURCE_SIZE="1")
    payload = convert(client, origin, "/limit-envelope.csv").get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]
    assert "endpoint" not in payload


# Spec: "file size `> limit` => `HTTP 400`"
# Context: an oversized file leaves no dataset behind to read.
def test_an_oversized_source_stores_nothing(configured_client, origin):
    client = configured_client(MAX_SOURCE_SIZE="1")
    convert(client, origin, "/limit-nothing.csv")
    unlimited = configured_client()
    endpoint = convert(unlimited, origin, "/limit-nothing.csv").get_json()["endpoint"]
    assert client.get(endpoint).status_code == 404


# Spec: "unset limit means no max."
# Context: the default configuration against a comfortably large file.
def test_no_limit_accepts_a_large_file(client, upload):
    large = "name,value\n" + "".join(f"row{n},{n}\n" for n in range(5000))
    assert upload(large).status_code == 200


# Spec: "| `MAX_SOURCE_SIZE` | integer bytes | unset |"
# Context: a zero limit is a limit, so every non-empty file is over it (T54).
def test_a_zero_limit_refuses_every_file(configured_client):
    client = configured_client(MAX_SOURCE_SIZE="0")
    assert upload(client).status_code == 400


# Spec: "Enforced for `/convert` and `/upload`"
# Context: the limit measures the file, not the multipart envelope carrying it,
# so a long filename does not push an at-limit upload over (T56).
def test_the_upload_limit_ignores_the_multipart_envelope(configured_client):
    client = configured_client(MAX_SOURCE_SIZE=str(BODY_SIZE))
    assert upload(client, filename="a-very-long-file-name-" * 20 + ".csv").status_code == 200


# Spec: "file size `> limit` => `HTTP 400`"
# Context: an oversized file that is also unparseable is refused on size, before
# any parsing is attempted (T57).
def test_size_is_checked_before_parsing(configured_client):
    client = configured_client(MAX_SOURCE_SIZE="4")
    response = upload(client, "<html><body>not a table</body></html>")
    assert response.status_code == 400
    assert "4" in response.get_json()["error"]


# Spec: "Enforced for `/convert`" / "return the cached dataset id without
# re-downloading"
# Context: a source converted under a loose limit is answered from the store
# after the limit is tightened, since no file is fetched to measure (T58).
def test_a_cache_hit_skips_the_limit(configured_client, origin, tmp_path):
    storage = str(tmp_path / "shared")
    first = configured_client(STORAGE_DIR=storage)
    endpoint = convert(first, origin, "/limit-cached.csv").get_json()["endpoint"]
    restarted = configured_client(STORAGE_DIR=storage, MAX_SOURCE_SIZE="1")
    again = convert(restarted, origin, "/limit-cached.csv")
    assert again.status_code == 200
    assert again.get_json()["endpoint"] == endpoint
