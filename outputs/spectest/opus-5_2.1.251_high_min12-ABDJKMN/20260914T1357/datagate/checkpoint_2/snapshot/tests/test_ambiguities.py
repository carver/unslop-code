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


# ==========================================================================
# Pagination / sorting / shape controls (T21-T31)
# ==========================================================================
MIXED = "label,value\nb,10\na,\nc,x\nd,9\n"
FOUR = "name,age\nzoe,30\nada,36\nmia,30\nbea,36\n"


@pytest.fixture
def ctl(server, csv_url):
    def make(body, name="amb"):
        url = csv_url(body, name=name)
        return server.convert(url)[2]["endpoint"]
    return make


# T21 — `_size` is the specified control; legacy `limit` still applies when
# `_size` is absent, and `_size` wins when both are given.
def test_t21_size_and_legacy_limit(server, ctl):
    body = "n,v\n" + "".join("%d,a\n" % i for i in range(120))
    endpoint = ctl(body, name="t21")
    assert len(server.get(endpoint + "?limit=5")[2]["rows"]) == 5
    assert len(server.get(endpoint + "?_size=7")[2]["rows"]) == 7
    assert len(server.get(endpoint + "?limit=5&_size=7")[2]["rows"]) == 7
    # a malformed legacy `limit` still falls back to 100 rather than erroring
    status, _, data = server.get(endpoint + "?limit=abc")
    assert status == 200 and len(data["rows"]) == 100


# T22 — `rowid` numbers data rows, so the first data row is 1 (not 2).
def test_t22_rowid_starts_at_one_for_first_data_row(server, ctl):
    endpoint = ctl(SIMPLE, name="t22")
    rows = server.get(endpoint + "?_shape=objects")[2]["rows"]
    assert [r["rowid"] for r in rows] == [1, 2]
    assert rows[0]["name"] == "ada"


# T23 — mixed-type column: empties first, then numbers numerically, then text.
def test_t23_mixed_type_sort_order(server, ctl):
    endpoint = ctl(MIXED, name="t23")
    status, _, data = server.get(endpoint + "?_sort=value")
    assert status == 200, data
    assert [r[0] for r in data["rows"]] == ["a", "d", "b", "c"]


# T23 — descending is the exact reverse ranking (empties last), still stable.
def test_t23_mixed_type_sort_desc(server, ctl):
    endpoint = ctl(MIXED, name="t23d")
    data = server.get(endpoint + "?_sort_desc=value")[2]
    assert [r[0] for r in data["rows"]] == ["c", "b", "d", "a"]


# T23 — numbers compare numerically, not as text.
def test_t23_numbers_sort_numerically(server, ctl):
    endpoint = ctl("n,v\n100,a\n9,b\n20,c\n", name="t23n")
    data = server.get(endpoint + "?_sort=n")[2]
    assert [r[0] for r in data["rows"]] == [9, 20, 100]


# T24 — when both are present only `_sort_desc` is validated; a bogus `_sort`
# is ignored rather than rejected.
def test_t24_losing_sort_is_not_validated(server, ctl):
    endpoint = ctl(FOUR, name="t24")
    status, _, data = server.get(endpoint + "?_sort=bogus&_sort_desc=name")
    assert status == 200, data
    assert [r[0] for r in data["rows"]] == ["zoe", "mia", "bea", "ada"]
    status, _, data = server.get(endpoint + "?_sort=&_sort_desc=name")
    assert status == 200, data


# T25 — `_rowid=hide` is accepted (and a no-op) with the lists shape.
def test_t25_rowid_hide_is_noop_for_lists(server, ctl):
    endpoint = ctl(SIMPLE, name="t25")
    status, _, data = server.get(endpoint + "?_rowid=hide")
    assert status == 200, data
    assert data["rows"] == [["ada", 36], ["grace", 45]]
    status, _, data = server.get(endpoint + "?_shape=lists&_rowid=hide")
    assert status == 200, data


# T26 — repeats of non-control parameters are not rejected.
def test_t26_repeated_non_control_params_allowed(server, ctl):
    endpoint = ctl(SIMPLE, name="t26")
    assert server.get(endpoint + "?foo=1&foo=2")[0] == 200
    assert server.get(endpoint + "?limit=1&limit=2")[0] == 200


# T27 — an unknown dataset id answers 404 even with invalid controls.
def test_t27_unknown_dataset_wins_over_bad_controls(server):
    status, _, data = server.get("/datasets/missing?_size=0&_size=0&_shape=x")
    assert status == 404
    assert data["ok"] is False


# T28 — ASCII integer syntax: sign and leading zeros accepted; padded
# whitespace and non-ASCII digits rejected; no upper bound on `_size`.
def test_t28_integer_syntax(server, ctl):
    body = "n,v\n" + "".join("%d,a\n" % i for i in range(10))
    endpoint = ctl(body, name="t28")
    assert len(server.get(endpoint + "?_size=%2B3")[2]["rows"]) == 3
    assert len(server.get(endpoint + "?_size=003")[2]["rows"]) == 3
    assert server.get(endpoint + "?_offset=%2B0")[0] == 200
    assert len(server.get(endpoint + "?_size=99999999999")[2]["rows"]) == 10
    assert server.get(endpoint + "?_size=%20%35%20")[0] == 400
    assert server.get(endpoint + "?_size=%D9%A1%D9%A2")[0] == 400
    assert server.get(endpoint + "?_offset=%D9%A7")[0] == 400


# T29 — `rowid` is the first key of an object row.
def test_t29_rowid_is_first_key(server, ctl):
    endpoint = ctl(SIMPLE, name="t29")
    raw = server.raw(endpoint + "?_shape=objects")[2].decode("utf-8")
    body = json.loads(raw)
    assert list(body["rows"][0])[0] == "rowid"
    rows_text = raw[raw.index('"rows"'):]
    assert rows_text.index('"rowid"') < rows_text.index('"name"')


# T30 — duplicate header names collapse in the objects shape; `columns` keeps
# reporting the header verbatim.
def test_t30_duplicate_columns_in_objects_shape(server, ctl):
    endpoint = ctl("a,a,b\n1,2,3\n", name="t30")
    data = server.get(endpoint + "?_shape=objects")[2]
    assert data["columns"] == ["a", "a", "b"]
    assert data["rows"] == [{"rowid": 1, "a": 2, "b": 3}]


# T31 — `rowid` is not a sortable column.
@pytest.mark.parametrize("param", ["_sort", "_sort_desc"])
def test_t31_sorting_by_rowid_is_400(server, ctl, param):
    endpoint = ctl(SIMPLE, name="t31")
    status, _, data = server.get(endpoint + "?%s=rowid" % param)
    assert status == 400
    assert data["ok"] is False
