"""Tests for the `ORIGIN_ALLOWLIST` check applied to every request."""

import pytest

from conftest import FIXTURES
from helpers import convert, upload

ALLOWLIST = ("example.com", "reports.example.org")


@pytest.fixture
def guarded_client(make_client):
    return make_client(origin_allowlist=ALLOWLIST)


def get(client, path, referer=None, **params):
    """Request a path with an optional `Referer`, which is what the allowlist judges."""
    headers = {"Referer": referer} if referer else {}
    return client.get(path, query_string=params, headers=headers)


def convert_from(client, base_url, referer):
    return get(client, "/convert", referer, source=f"{base_url}/basic.csv")


@pytest.mark.parametrize(
    "referer",
    [
        "https://example.com/reports",
        "https://EXAMPLE.COM/reports",
        "https://docs.example.com/",
        "http://deep.docs.example.com/page?q=1",
        "https://reports.example.org/index.html",
    ],
)
def test_an_allowed_referer_passes(guarded_client, base_url, referer):
    assert convert_from(guarded_client, base_url, referer).status_code == 200


@pytest.mark.parametrize(
    "referer",
    [
        "https://notexample.com/",
        "https://example.com.elsewhere.net/",
        "https://example.org/",
        "https://sub.reports.example.org.evil.net/",
        "not a url at all",
    ],
)
def test_a_referer_outside_the_allowlist_is_forbidden(guarded_client, base_url, referer):
    response = convert_from(guarded_client, base_url, referer)
    assert response.status_code == 403
    assert response.get_json()["ok"] is False


def test_a_missing_referer_is_forbidden(guarded_client, base_url):
    response = convert(guarded_client, base_url, "basic.csv")
    assert response.status_code == 403
    assert response.get_json()["ok"] is False


def test_the_allowlist_guards_uploads(guarded_client):
    assert upload(guarded_client, FIXTURES["staff.csv"]).status_code == 403


def test_the_allowlist_guards_dataset_reads_and_exports(guarded_client, base_url):
    allowed = "https://example.com/"
    endpoint = convert_from(guarded_client, base_url, allowed).get_json()["endpoint"]

    assert get(guarded_client, endpoint).status_code == 403
    assert get(guarded_client, endpoint, allowed).status_code == 200
    assert get(guarded_client, f"{endpoint}/export", allowed).status_code == 200


def test_requests_are_checked_before_routing(guarded_client):
    assert guarded_client.get("/no-such-route").status_code == 403


def test_no_allowlist_lets_every_request_through(client, base_url):
    assert convert(client, base_url, "basic.csv").status_code == 200
    assert convert_from(client, base_url, "https://anywhere.invalid/").status_code == 200
