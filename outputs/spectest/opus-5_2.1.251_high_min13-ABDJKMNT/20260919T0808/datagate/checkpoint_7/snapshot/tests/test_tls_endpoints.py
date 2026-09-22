"""Spec section: TLS-aware endpoint URLs."""

import io

import pytest

SIMPLE_CSV = "name,age\nada,36\n"


@pytest.fixture
def tls(configured_client, origin):
    """A client started with `REQUIRE_TLS` set, plus both ingestion helpers."""

    def _tls(value=None):
        client = configured_client(REQUIRE_TLS=value)
        counter = iter(range(1000))

        def convert(**kwargs):
            url = origin.serve(f"/tls-{value}-{next(counter)}.csv", SIMPLE_CSV)
            return client.get(f"/convert?source={url}", **kwargs)

        def upload(**kwargs):
            return client.post(
                "/upload",
                data={"file": (io.BytesIO(SIMPLE_CSV.encode()), "data.csv")},
                content_type="multipart/form-data",
                **kwargs,
            )

        return client, convert, upload

    return _tls


# Phrase: "`REQUIRE_TLS=false`: `/convert` and `/upload` return relative endpoints."
@pytest.mark.parametrize("value", [None, "false", "0", "no", "off"])
def test_endpoints_are_relative_without_required_tls(tls, value):
    _, convert, upload = tls(value)

    assert convert().get_json()["endpoint"].startswith("/datasets/")
    assert upload().get_json()["endpoint"].startswith("/datasets/")


# Phrase: "`REQUIRE_TLS=true`: same endpoints are absolute `https://` URLs using
# request host." - on `/convert`.
def test_convert_returns_an_absolute_https_endpoint(tls):
    _, convert, _ = tls("true")

    endpoint = convert(headers={"Host": "gate.example"}).get_json()["endpoint"]

    assert endpoint.startswith("https://gate.example/datasets/")


# Phrase: "same endpoints are absolute `https://` URLs" - on `/upload` too.
def test_upload_returns_an_absolute_https_endpoint(tls):
    _, _, upload = tls("on")

    endpoint = upload(headers={"Host": "gate.example"}).get_json()["endpoint"]

    assert endpoint.startswith("https://gate.example/datasets/")


# Phrase: "using request host" - the host comes from the request, so two
# requests to different hosts get different absolute URLs (T69).
def test_the_absolute_url_follows_the_request_host(tls):
    _, convert, _ = tls("yes")

    first = convert(headers={"Host": "a.example"}).get_json()["endpoint"]
    second = convert(headers={"Host": "b.example"}).get_json()["endpoint"]

    assert first.startswith("https://a.example/")
    assert second.startswith("https://b.example/")


# Phrase: "using request host" - a host carrying a port is used as received (T69).
def test_the_absolute_url_keeps_a_port_in_the_host(tls):
    _, convert, _ = tls("1")

    endpoint = convert(headers={"Host": "gate.example:8443"}).get_json()["endpoint"]

    assert endpoint.startswith("https://gate.example:8443/datasets/")


# Phrase: "same endpoints" - only the scheme and authority are added; the path
# is the `/datasets/<id>` the relative form returns.
def test_the_absolute_url_only_prefixes_the_relative_path(tls, origin):
    url = origin.serve("/tls-same.csv", SIMPLE_CSV)
    plain, _, _ = tls("off")
    secure = tls("on")[0]

    relative = plain.get(f"/convert?source={url}").get_json()["endpoint"]
    absolute = secure.get(f"/convert?source={url}", headers={"Host": "gate.example"})

    assert absolute.get_json()["endpoint"] == f"https://gate.example{relative}"


# Phrase: the endpoint an absolute URL names is the one that serves the dataset.
def test_the_advertised_endpoint_resolves_to_the_dataset(tls):
    client, convert, _ = tls("true")

    endpoint = convert(headers={"Host": "gate.example"}).get_json()["endpoint"]
    path = endpoint.removeprefix("https://gate.example")

    assert client.get(path).get_json()["columns"] == ["name", "age"]


# Phrase: the section is about endpoint URLs only, so a plaintext request is
# still served when `REQUIRE_TLS=true` (T68).
def test_required_tls_does_not_refuse_plaintext_requests(tls):
    client, convert, _ = tls("true")

    assert convert().status_code == 200
    assert client.get("/datasets/missing").status_code == 404
