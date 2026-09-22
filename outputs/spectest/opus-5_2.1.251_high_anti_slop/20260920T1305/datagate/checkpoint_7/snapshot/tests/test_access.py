"""Tests for the ORIGIN_ALLOWLIST check applied to every request."""

import io

import pytest

CSV = b"name,age\nada,36\n"


@pytest.fixture
def allowlisted(configured_client):
    """A client accepting requests from example.com and its subdomains only."""
    return configured_client(ORIGIN_ALLOWLIST="example.com, example.net")


def test_requests_pass_without_an_allowlist(client, serve):
    response = client.get("/convert", query_string={"source": serve("a.csv", CSV)})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "referer",
    [
        "https://example.com/reports",
        "https://app.example.com/",
        "https://EXAMPLE.com/",
        "http://deep.nested.example.net/page",
    ],
)
def test_allowed_referers_are_served(allowlisted, serve, referer):
    response = allowlisted.get(
        "/convert",
        query_string={"source": serve("a.csv", CSV)},
        headers={"Referer": referer},
    )

    assert response.status_code == 200


def test_missing_referer_is_forbidden(allowlisted, serve):
    response = allowlisted.get("/convert", query_string={"source": serve("a.csv", CSV)})

    assert response.status_code == 403
    assert response.json["ok"] is False
    assert isinstance(response.json["error"], str)


@pytest.mark.parametrize(
    "referer",
    [
        "https://notexample.com/",
        "https://example.com.attacker.test/",
        "https://example.org/",
        "not a url",
    ],
)
def test_other_referers_are_forbidden(allowlisted, serve, referer):
    response = allowlisted.get(
        "/convert",
        query_string={"source": serve("a.csv", CSV)},
        headers={"Referer": referer},
    )

    assert response.status_code == 403
    assert response.json["ok"] is False


def test_the_check_precedes_routing(allowlisted):
    response = allowlisted.get("/no-such-endpoint")

    assert response.status_code == 403


def test_uploads_are_checked_too(allowlisted):
    response = allowlisted.post(
        "/upload",
        data={"file": (io.BytesIO(CSV), "a.csv")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 403
