"""Spec tests for "Origin Allowlist". Each section quotes its phrase."""
import pytest

from conftest import assert_error_envelope, running

ALLOWED = "example.com,test.internal"
SIMPLE = "name,age\nada,36\n"


def ref(url):
    return {"Referer": url}


@pytest.fixture(scope="module")
def guarded():
    """A server with `ORIGIN_ALLOWLIST=example.com,test.internal`."""
    with running({"ORIGIN_ALLOWLIST": ALLOWED, "DATAGATE_CONFIG": None},
                 "allow_on") as client:
        yield client


# ==========================================================================
# Spec: "If configured, check every request before routing: 1. Require `Referer`."
# ==========================================================================
@pytest.mark.parametrize("path", [
    "/convert?source=http://example.com/a.csv",
    "/upload",
    "/datasets/abc",
    "/datasets/abc/export",
    "/",
    "/nothing-here",
])
def test_missing_referer_is_refused(guarded, path):
    status, _, data = guarded.get(path)
    assert_error_envelope(status, data, 403)


def test_missing_referer_on_upload_is_refused(guarded):
    status, _, data = guarded.upload(SIMPLE.encode("utf-8"))
    assert_error_envelope(status, data, 403)


# Spec: "Require `Referer`." — an empty header value supplies no origin.
def test_empty_referer_is_refused(guarded):
    status, _, data = guarded.get("/datasets/abc", headers=ref(""))
    assert_error_envelope(status, data, 403)


# ==========================================================================
# Spec: "2. Parse hostname."
# ==========================================================================
def test_allowed_referer_passes_through_to_routing(guarded):
    """A permitted origin is routed normally: unknown id is still a 404."""
    status, _, data = guarded.get("/datasets/unknown",
                                  headers=ref("https://example.com/page"))
    assert status == 404, data
    assert data["ok"] is False


def test_allowed_referer_can_convert_and_query(guarded, csv_url):
    url = csv_url(SIMPLE, name="allow-convert")
    headers = ref("https://example.com/app/index.html")
    status, _, data = guarded.convert(url, headers=headers)
    assert status == 200, data
    status, _, payload = guarded.get(data["endpoint"], headers=headers)
    assert status == 200, payload
    assert payload["rows"] == [["ada", 36]]


def test_allowed_referer_can_upload(guarded):
    status, _, data = guarded.upload(SIMPLE.encode("utf-8"),
                                     headers=ref("https://test.internal/x"))
    assert status == 200, data
    assert data["ok"] is True


# Spec: "Parse hostname." — only the host part is compared; scheme, port,
# userinfo, path and query are not (AMBIGUITIES T91).
@pytest.mark.parametrize("referer", [
    "https://example.com",
    "https://example.com/",
    "http://example.com/deep/path?q=1#frag",
    "https://example.com:8443/page",
    "http://example.com:80/",
    "https://user:pw@example.com/page",
])
def test_hostname_is_compared_without_the_rest_of_the_url(guarded, referer):
    assert guarded.get("/datasets/unknown", headers=ref(referer))[0] == 404


# Spec: "2. Parse hostname." + "4. Otherwise return `HTTP 403`" — a `Referer`
# with no parseable hostname is refused (AMBIGUITIES T90).
@pytest.mark.parametrize("referer", [
    "not a url",
    "example.com",            # no scheme: no hostname to parse
    "example.com/page",
    "/relative/path",
    "about:blank",
    "https://",
    "://example.com",
])
def test_unparseable_referer_is_refused(guarded, referer):
    status, _, data = guarded.get("/datasets/unknown", headers=ref(referer))
    assert_error_envelope(status, data, 403)


# ==========================================================================
# Spec: "3. Accept only hostnames matching any allowed suffix
#        case-insensitively with domain-boundary rules."
# ==========================================================================
@pytest.mark.parametrize("host", [
    "example.com",            # the suffix itself
    "www.example.com",
    "a.b.c.example.com",
    "test.internal",          # the second entry
    "deep.sub.test.internal",
])
def test_matching_hostnames_are_accepted(guarded, host):
    assert guarded.get("/datasets/unknown",
                       headers=ref("https://%s/p" % host))[0] == 404


# Spec: "... with domain-boundary rules." — a suffix only matches at a label
# boundary (AMBIGUITIES T86).
@pytest.mark.parametrize("host", [
    "notexample.com",
    "badexample.com",
    "myexample.com",
    "example.community",
    "example.com.evil.net",
    "wwwexample.com",
    "internal",
    "test.internal.evil.net",
    "othertest.internal.example",
])
def test_boundary_violations_are_refused(guarded, host):
    status, _, data = guarded.get("/datasets/unknown",
                                  headers=ref("https://%s/p" % host))
    assert_error_envelope(status, data, 403)


# Spec: "case-insensitively"
@pytest.mark.parametrize("host", ["EXAMPLE.COM", "Example.Com",
                                  "WWW.Example.COM", "TEST.INTERNAL"])
def test_matching_is_case_insensitive_on_the_host(guarded, host):
    assert guarded.get("/datasets/unknown",
                       headers=ref("https://%s/p" % host))[0] == 404


# Spec: "case-insensitively" — also for the configured entries.
def test_matching_is_case_insensitive_on_the_entries():
    with running({"ORIGIN_ALLOWLIST": "EXAMPLE.COM", "DATAGATE_CONFIG": None},
                 "allow_case") as client:
        assert client.get("/datasets/x",
                          headers=ref("https://www.example.com/"))[0] == 404
        assert client.get("/datasets/x",
                          headers=ref("https://other.test/"))[0] == 403


# Spec: "any allowed suffix" — one match out of several entries is enough.
def test_any_entry_may_match():
    with running({"ORIGIN_ALLOWLIST": "a.test,b.test,c.test",
                  "DATAGATE_CONFIG": None}, "allow_multi") as client:
        for host in ("a.test", "b.test", "c.test", "x.c.test"):
            assert client.get("/datasets/x",
                              headers=ref("https://%s/" % host))[0] == 404
        assert client.get("/datasets/x",
                          headers=ref("https://d.test/"))[0] == 403


# An entry written with a leading dot means the same suffix (AMBIGUITIES T87).
def test_leading_dot_entry():
    with running({"ORIGIN_ALLOWLIST": ".example.com", "DATAGATE_CONFIG": None},
                 "allow_dot") as client:
        assert client.get("/datasets/x",
                          headers=ref("https://www.example.com/"))[0] == 404
        assert client.get("/datasets/x",
                          headers=ref("https://example.com/"))[0] == 404
        assert client.get("/datasets/x",
                          headers=ref("https://notexample.com/"))[0] == 403


# A hostname's own trailing dot (an absolute FQDN) does not defeat the match.
def test_trailing_dot_host(guarded):
    assert guarded.get("/datasets/unknown",
                       headers=ref("https://www.example.com./p"))[0] == 404


# An IP-literal host is compared as written (AMBIGUITIES T91).
def test_ip_literal_host():
    with running({"ORIGIN_ALLOWLIST": "127.0.0.1", "DATAGATE_CONFIG": None},
                 "allow_ip") as client:
        assert client.get("/datasets/x",
                          headers=ref("http://127.0.0.1:9000/p"))[0] == 404
        assert client.get("/datasets/x",
                          headers=ref("http://127.0.0.2/p"))[0] == 403


# ==========================================================================
# Spec: "4. Otherwise return `HTTP 403`."
# ==========================================================================
def test_refusal_uses_the_standard_envelope(guarded):
    status, _, data = guarded.get("/datasets/unknown",
                                  headers=ref("https://denied.test/"))
    assert_error_envelope(status, data, 403)


def test_refused_upload_is_not_stored(guarded):
    body = "name,age\nrefused,1\n"
    assert guarded.upload(body.encode("utf-8"),
                          headers=ref("https://denied.test/"))[0] == 403
    # The same bytes uploaded from an allowed origin are parsed fresh.
    status, _, data = guarded.upload(body.encode("utf-8"),
                                     headers=ref("https://example.com/"))
    assert status == 200, data


# ==========================================================================
# Spec: "check every request before routing" (AMBIGUITIES T89/T99)
# ==========================================================================
def test_unknown_path_is_refused_before_it_becomes_a_404(guarded):
    """Routing has not happened yet, so 403 wins over 404."""
    status, _, data = guarded.get("/no/such/route",
                                  headers=ref("https://denied.test/"))
    assert_error_envelope(status, data, 403)


def test_wrong_method_is_refused_before_it_becomes_a_405(guarded):
    status, _, data = guarded.get("/upload", headers=ref("https://denied.test/"))
    assert_error_envelope(status, data, 403)


def test_options_request_is_checked_too(guarded):
    status, _, body = guarded.raw("/convert", method="OPTIONS")
    assert status == 403, body


def test_allowlist_precedes_argument_errors(guarded):
    """/convert without `source` would be a 400; the origin check comes first."""
    status, _, data = guarded.get("/convert", headers=ref("https://bad.test/"))
    assert_error_envelope(status, data, 403)


def test_allowlist_precedes_the_size_limit():
    env = {"ORIGIN_ALLOWLIST": "example.com", "MAX_SOURCE_SIZE": "4",
           "DATAGATE_CONFIG": None}
    with running(env, "allow_size") as client:
        big = ("a,b\n" + "1,2\n" * 50).encode("utf-8")
        status, _, data = client.upload(big, headers=ref("https://bad.test/"))
        assert_error_envelope(status, data, 403)
        # From an allowed origin the same request hits the size limit.
        status, _, data = client.upload(big, headers=ref("https://example.com/"))
        assert_error_envelope(status, data, 400)


# ==========================================================================
# Spec: "No allowlist means all requests pass."
# ==========================================================================
def test_no_allowlist_accepts_requests_without_referer(server, csv_url):
    url = csv_url(SIMPLE, name="noallow")
    assert server.convert(url)[0] == 200
    assert server.get("/datasets/unknown")[0] == 404


@pytest.mark.parametrize("referer", ["https://anything.example/",
                                     "garbage", "", "http://10.0.0.1/"])
def test_no_allowlist_ignores_the_referer_entirely(server, referer):
    status, _, data = server.get("/datasets/unknown",
                                 headers={"Referer": referer} if referer else {})
    assert status == 404, data


# An allowlist that parses to no entries is not configured (AMBIGUITIES T88).
def test_blank_allowlist_lets_everything_through():
    with running({"ORIGIN_ALLOWLIST": " , ", "DATAGATE_CONFIG": None},
                 "allow_blank") as client:
        assert client.get("/datasets/unknown")[0] == 404
