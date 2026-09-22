"""The origin allowlist standing in front of every route, and TLS endpoints."""

import io
from dataclasses import replace

import pytest

from gateway.app import create_app

TABLE = b"name,age\nada,36\n"
ALLOWED = ("example.com", "internal.test")


@pytest.fixture
def guarded(settings):
    """Build a client whose requests are checked against ``ALLOWED``."""
    return create_app(
        replace(settings, origin_allowlist=ALLOWED)
    ).test_client()


def upload_from(client, referer: str | None):
    """Upload a table, quoting ``referer`` when there is one."""
    return client.post(
        "/upload",
        data={"file": (io.BytesIO(TABLE), "data.csv")},
        content_type="multipart/form-data",
        headers={"Referer": referer} if referer else {},
    )


@pytest.mark.parametrize(
    "referer",
    [
        "https://example.com/reports",
        "https://docs.example.com/",
        "http://EXAMPLE.com:8080/page?a=1",
        "https://deep.nested.internal.test/",
    ],
)
def test_an_allowed_referer_passes(guarded, referer):
    assert upload_from(guarded, referer).status_code == 200


@pytest.mark.parametrize(
    "referer",
    [
        "https://notexample.com/",
        "https://example.com.evil.net/",
        "https://example.org/",
        "https://internal.test.attacker.io/",
        "not a url",
    ],
)
def test_a_referer_outside_the_allowlist_is_refused(guarded, referer):
    response = upload_from(guarded, referer)

    assert response.status_code == 403
    assert response.get_json()["ok"] is False


def test_a_missing_referer_is_refused(guarded):
    response = upload_from(guarded, None)

    assert response.status_code == 403
    assert response.get_json() == {
        "ok": False,
        "error": "Request needs a Referer header",
    }


def test_the_allowlist_is_checked_before_routing(guarded):
    assert guarded.get("/nowhere").status_code == 403


def test_reading_a_dataset_is_checked_too(guarded, settings):
    endpoint = upload_from(guarded, "https://example.com/").get_json()["endpoint"]
    open_client = create_app(settings).test_client()

    assert open_client.get(endpoint).status_code == 200
    assert guarded.get(endpoint).status_code == 403
    allowed = guarded.get(endpoint, headers={"Referer": "https://example.com/"})
    assert allowed.status_code == 200


def test_without_an_allowlist_every_request_passes(client):
    assert upload_from(client, None).status_code == 200
    assert upload_from(client, "https://anywhere.example/").status_code == 200


def test_endpoints_are_relative_without_required_tls(client):
    body = upload_from(client, None).get_json()
    assert body["endpoint"].startswith("/datasets/")


def test_required_tls_makes_endpoints_absolute(settings):
    secure = create_app(replace(settings, require_tls=True)).test_client()

    endpoint = upload_from(secure, None).get_json()["endpoint"]
    assert endpoint.startswith("https://localhost/datasets/")
    assert secure.get(endpoint).get_json()["rows"] == [["ada", 36]]


def test_required_tls_uses_the_host_of_the_request(settings, files, base_url):
    secure = create_app(replace(settings, require_tls=True)).test_client()
    files["/data.csv"] = TABLE

    response = secure.get(
        "/convert",
        query_string={"source": f"{base_url}/data.csv"},
        headers={"Host": "gateway.example.com"},
    )
    assert response.get_json()["endpoint"].startswith(
        "https://gateway.example.com/datasets/"
    )
