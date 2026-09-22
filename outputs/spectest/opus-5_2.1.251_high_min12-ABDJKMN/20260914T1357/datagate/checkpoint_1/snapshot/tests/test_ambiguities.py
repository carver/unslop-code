"""Tests pinning the interpretations recorded in AMBIGUITIES.md (T1-T20)."""
import json

import pytest

from conftest import Client, _spawn, free_port, wait_for_port

SIMPLE = "name,age\nada,36\ngrace,45\n"


# T1 — dataset id derives from the source URL string: opaque, URL-safe, stable.
def test_t1_endpoint_shape_and_stability(server, csv_url):
    url = csv_url(SIMPLE)
    endpoint = server.convert(url)[2]["endpoint"]
    assert endpoint.startswith("/datasets/")
    ident = endpoint[len("/datasets/"):]
    assert ident and all(c.isalnum() or c in "-_" for c in ident)
    assert server.convert(url)[2]["endpoint"] == endpoint


# T1/T15 — distinct URL strings (even trivially different) map to distinct ids.
def test_t1_url_string_is_not_normalised(server, origin):
    origin.add("/t1.csv", SIMPLE)
    a = server.convert(origin.base + "/t1.csv")[2]["endpoint"]
    b = server.convert(origin.base + "/t1.csv?x=1")[2]["endpoint"]
    assert a != b


# T2 — leading-zero integers become numbers.
def test_t2_leading_zeros_become_numbers(dataset):
    payload = dataset("code,n\n007,1\n0123,2\n")
    assert payload["rows"] == [[7, 1], [123, 2]]


# T3 — grouped/currency/percent values stay text.
@pytest.mark.parametrize("value", ["1,234", "$5.00", "50%", "(12)", "1 234"])
def test_t3_formatted_numbers_stay_text(dataset, value):
    payload = dataset('a;b\n"%s";1\n' % value)
    assert payload["rows"] == [[value, 1]]


# T4 — surrounding whitespace is stripped from headers and values.
def test_t4_whitespace_is_stripped(dataset):
    payload = dataset("a , b\n 5 , ada \n")
    assert payload["columns"] == ["a", "b"]
    assert payload["rows"] == [[5, "ada"]]


# T5 — empty cells are empty strings, not null.
def test_t5_empty_cells_are_empty_strings(server, csv_url):
    url = csv_url("a,b,c\n1,,3\n")
    endpoint = server.convert(url)[2]["endpoint"]
    status, _, payload = server.get(endpoint)
    assert status == 200
    assert payload["rows"] == [[1, "", 3]]
    assert "null" not in server.raw(endpoint)[2].decode("utf-8")


# T6 — boolean-looking values stay text.
def test_t6_booleans_stay_text(dataset):
    payload = dataset("flag,n\ntrue,1\nFalse,2\nyes,3\n")
    assert payload["rows"] == [["true", 1], ["False", 2], ["yes", 3]]


# T7 — NaN/Infinity stay text so the response is valid JSON.
def test_t7_nan_and_inf_stay_text(server, csv_url):
    url = csv_url("v,n\nNaN,1\nInfinity,2\n-inf,3\n")
    endpoint = server.convert(url)[2]["endpoint"]
    raw = server.raw(endpoint)[2].decode("utf-8")
    assert "NaN," not in raw.replace('"NaN"', "")
    payload = json.loads(raw)
    assert payload["rows"] == [["NaN", 1], ["Infinity", 2], ["-inf", 3]]


# T8 — scientific notation becomes a number.
def test_t8_scientific_notation_is_number(dataset):
    payload = dataset("a,b\n1e5,2.5E-3\n")
    assert payload["rows"] == [[100000.0, 0.0025]]


# T9 — ragged rows are padded/truncated to the header width.
def test_t9_ragged_rows_rectangularised(dataset):
    payload = dataset("a,b,c\n1,2\n1,2,3,4\n")
    assert payload["columns"] == ["a", "b", "c"]
    assert payload["rows"] == [[1, 2, ""], [1, 2, 3]]


# T10 — header labels are returned verbatim (duplicates kept).
def test_t10_duplicate_headers_verbatim(dataset):
    payload = dataset("a,a,b\n1,2,3\n")
    assert payload["columns"] == ["a", "a", "b"]


# T11 — a delimiter-free (single-column) payload is non-tabular → 400.
def test_t11_single_column_is_non_tabular(server, csv_url):
    url = csv_url("name\nada\ngrace\n")
    status, _, data = server.convert(url)
    assert status == 400
    assert data["ok"] is False


# T12 — a valid codec that cannot decode the bytes is a 400 charset error.
def test_t12_strict_decoding(server, csv_url):
    url = csv_url("a,b\n1,café\n".encode("utf-8"))
    status, _, data = server.convert(url, charset="ascii")
    assert status == 400
    assert data["ok"] is False


# T13 — ?limit=N overrides the default 100.
def test_t13_limit_override(server, csv_url):
    body = "n,v\n" + "".join("%d,x\n" % i for i in range(150))
    url = csv_url(body)
    endpoint = server.convert(url)[2]["endpoint"]
    assert len(server.get(endpoint + "?limit=5")[2]["rows"]) == 5
    assert len(server.get(endpoint + "?limit=150")[2]["rows"]) == 150
    assert len(server.get(endpoint)[2]["rows"]) == 100


# T13 — a malformed limit falls back to the default rather than erroring.
@pytest.mark.parametrize("bad", ["abc", "-3", "0", ""])
def test_t13_bad_limit_falls_back_to_default(server, csv_url, bad):
    body = "n,v\n" + "".join("%d,x\n" % i for i in range(120))
    url = csv_url(body)
    endpoint = server.convert(url)[2]["endpoint"]
    status, _, payload = server.get(endpoint + "?limit=" + bad)
    assert status == 200
    assert len(payload["rows"]) == 100


# T14 — date-like values stay text.
def test_t14_dates_stay_text(dataset):
    payload = dataset("d,ts,n\n2024-01-15,2024-01-15T08:30,1\n")
    assert payload["rows"] == [["2024-01-15", "2024-01-15T08:30", 1]]


# T15 — non-http(s) schemes are invalid URLs (400), not unreachable (404).
@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/a.csv",
                                 "gopher://host/a.csv"])
def test_t15_non_http_scheme_is_400(server, url):
    status, _, data = server.convert(url)
    assert status == 400, url
    assert data["ok"] is False


# T16 — re-converting refetches: updated remote content is reflected.
def test_t16_reconvert_refetches(server, origin):
    origin.add("/t16.csv", "a,b\n1,2\n")
    url = origin.base + "/t16.csv"
    endpoint = server.convert(url)[2]["endpoint"]
    assert server.get(endpoint)[2]["rows"] == [[1, 2]]
    origin.add("/t16.csv", "a,b\n9,8\n7,6\n")
    endpoint2 = server.convert(url)[2]["endpoint"]
    assert endpoint2 == endpoint
    assert server.get(endpoint)[2]["rows"] == [[9, 8], [7, 6]]


# T17 — wrong method on a known route is a JSON 405.
def test_t17_wrong_method_is_json_405(server):
    status, headers, body = server.raw("/convert", method="POST")
    assert status == 405
    assert "application/json" in headers.get("Content-Type", "")
    assert json.loads(body.decode("utf-8"))["ok"] is False


# T18 — content sniffing ignores Content-Type: CSV served as octet-stream works.
def test_t18_csv_served_as_octet_stream_is_accepted(server, csv_url):
    url = csv_url(SIMPLE, content_type="application/octet-stream")
    status, _, data = server.convert(url)
    assert status == 200, data


# T18 — an HTML page is rejected even when served as text/csv.
def test_t18_html_served_as_csv_is_rejected(server, csv_url):
    url = csv_url("<!DOCTYPE html>\n<html><body>a,b,c</body></html>\n",
                  content_type="text/csv")
    status, _, data = server.convert(url)
    assert status == 400
    assert data["ok"] is False


# T19 — all rows are stored; the 100-row cap is applied at query time only.
def test_t19_full_dataset_is_stored(server, csv_url):
    body = "n,v\n" + "".join("%d,x\n" % i for i in range(250))
    url = csv_url(body)
    endpoint = server.convert(url)[2]["endpoint"]
    assert len(server.get(endpoint + "?limit=1000")[2]["rows"]) == 250


# T20 — query_ms is a float in milliseconds, non-negative and plausible.
def test_t20_query_ms_units(dataset):
    payload = dataset(SIMPLE)
    assert isinstance(payload["query_ms"], float)
    assert 0.0 <= payload["query_ms"] < 60000.0
