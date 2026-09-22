"""Tests pinning the interpretations recorded in AMBIGUITIES.md (T1-T56)."""
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


# T13 (annotated) — the row-limit override is `_size`; the guessed `limit`
# parameter is now an ordinary ignored parameter.
def test_t13_limit_override(server, csv_url):
    body = "n,v\n" + "".join("%d,x\n" % i for i in range(150))
    url = csv_url(body)
    endpoint = server.convert(url)[2]["endpoint"]
    assert len(server.get(endpoint + "?_size=5")[2]["rows"]) == 5
    assert len(server.get(endpoint + "?_size=150")[2]["rows"]) == 150
    assert len(server.get(endpoint + "?limit=5")[2]["rows"]) == 100
    assert len(server.get(endpoint)[2]["rows"]) == 100


# T13 (annotated) — a bare `limit` is ignored, never an error.
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


# T16 (resolved by the caching spec) — re-converting now serves the cached
# dataset; `force` is the documented way to pick up updated remote content.
def test_t16_reconvert_refetches(server, origin):
    origin.add("/t16.csv", "a,b\n1,2\n")
    url = origin.base + "/t16.csv"
    endpoint = server.convert(url)[2]["endpoint"]
    assert server.get(endpoint)[2]["rows"] == [[1, 2]]
    origin.add("/t16.csv", "a,b\n9,8\n7,6\n")
    assert server.convert(url)[2]["endpoint"] == endpoint
    assert server.get(endpoint)[2]["rows"] == [[1, 2]]
    endpoint2 = server.convert(url, extra="force")[2]["endpoint"]
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
    assert len(server.get(endpoint + "?_size=1000")[2]["rows"]) == 250


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


# T21/T13 (annotated) — `_size` is the only row-limit control; the legacy
# `limit` parameter is now an ordinary ignored parameter.
def test_t21_size_is_the_only_row_limit_control(server, ctl):
    body = "n,v\n" + "".join("%d,a\n" % i for i in range(120))
    endpoint = ctl(body, name="t21")
    assert len(server.get(endpoint + "?_size=7")[2]["rows"]) == 7
    assert len(server.get(endpoint + "?limit=5")[2]["rows"]) == 100
    assert len(server.get(endpoint + "?limit=5&_size=7")[2]["rows"]) == 7
    # an ignored parameter never errors, whatever its value
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


# --------------------------------------------------------------------------
# Column-level filtering (T32-T42)
# --------------------------------------------------------------------------
FILTER_ROWS = "name,age,city\nada,36,London\ngrace,45,New York\nlin,29,london\n"


@pytest.fixture
def fds(server, csv_url):
    """Convert a CSV body; return its /datasets/<id> endpoint path."""
    def make(body, name="amb-flt"):
        url = csv_url(body, name=name)
        status, _, data = server.convert(url)
        assert status == 200, data
        return data["endpoint"]
    return make


# T32 — string comparators render the stored value, so numeric cells match.
def test_t32_exact_and_contains_see_rendered_numbers(server, fds):
    endpoint = fds(FILTER_ROWS, name="t32")
    assert server.get(endpoint + "?age__exact=36")[2]["rows"] == [
        ["ada", 36, "London"]]
    assert [r[0] for r in server.get(endpoint + "?age__contains=9")[2]["rows"]] \
        == ["lin"]


# T32 — the rendering is `str()` of the converted value, not the source text.
def test_t32_float_cells_compare_by_their_rendering(server, fds):
    endpoint = fds("id,v\na,36.0\nb,1e3\n", name="t32-float")
    assert server.get(endpoint + "?v__exact=36.0")[2]["rows"] == [["a", 36.0]]
    assert server.get(endpoint + "?v__exact=1e3")[2]["rows"] == []
    assert server.get(endpoint + "?v__exact=1000.0")[2]["rows"] == [["b", 1000.0]]


# T33 — `<column>__<comparator>` splits on the LAST `__`.
def test_t33_column_names_may_contain_double_underscores(server, fds):
    endpoint = fds("a__b,n\nx,1\ny,2\n", name="t33")
    status, _, data = server.get(endpoint + "?a__b__exact=x")
    assert status == 200, data
    assert data["rows"] == [["x", 1]]


# T34 — a `__` param with an unknown suffix is an invalid comparator (400),
# not a silently ignored parameter.
@pytest.mark.parametrize("key", ["name__startswith", "name__", "name__exact_"])
def test_t34_unknown_suffix_after_double_underscore_is_400(server, fds, key):
    endpoint = fds(FILTER_ROWS, name="t34")
    status, _, data = server.get(endpoint + "?%s=ada" % key)
    assert status == 400, data
    assert data["ok"] is False


# T35 — a name beginning with `_` is never a filter, even with `__` in it.
@pytest.mark.parametrize("query", ["?__exact=ada", "?_id__less=3",
                                   "?_name__nope=1"])
def test_t35_underscore_prefixed_names_are_not_filters(server, fds, query):
    endpoint = fds(FILTER_ROWS, name="t35")
    status, _, data = server.get(endpoint + query)
    assert status == 200, data
    assert len(data["rows"]) == 3


# T35 — a column whose name starts with `_` is therefore not filterable.
def test_t35_underscore_column_is_not_filterable(server, fds):
    endpoint = fds("_id,n\n1,a\n2,b\n", name="t35-col")
    data = server.get(endpoint + "?_id__exact=1")[2]
    assert len(data["rows"]) == 2


# T36 — the query budget is a server-side wall-clock limit; exhausting it
# yields the standard 400 envelope.
def test_t36_query_budget_is_server_side(server, fds):
    endpoint = fds(FILTER_ROWS, name="t36")
    # No client-facing timeout parameter exists: `_timeout` is just ignored.
    status, _, data = server.get(endpoint + "?_timeout=0")
    assert status == 200, data


# T37 — filter values are parsed with Python's `float()`.
@pytest.mark.parametrize("value", ["1e2", "%2B5", "-5", ".5", "5.", "%207%20"])
def test_t37_float_parse_accepts_python_float_syntax(server, fds, value):
    endpoint = fds(FILTER_ROWS, name="t37")
    status, _, data = server.get(endpoint + "?age__less=%s" % value)
    assert status == 200, data


# T37 — `nan`/`inf` are accepted by `float()`, so they are not 400; NaN simply
# matches nothing.
def test_t37_nan_and_inf_are_accepted_filter_values(server, fds):
    endpoint = fds(FILTER_ROWS, name="t37-nan")
    status, _, data = server.get(endpoint + "?age__less=nan")
    assert status == 200, data
    assert data["rows"] == []
    assert server.get(endpoint + "?age__less=inf")[2]["total"] == 3


# T38 — `float()` is applied to the stored value whatever its inferred type.
def test_t38_text_cells_that_float_parses_still_compare(server, fds):
    endpoint = fds("id,v\na,1\nb,inf\nc,n/a\n", name="t38")
    data = server.get(endpoint + "?v__greater=0")[2]
    assert [r[0] for r in data["rows"]] == ["a", "b"]


# T39 — an empty value is a value, not a malformed filter.
def test_t39_empty_value_for_string_comparators(server, fds):
    endpoint = fds("id,v\na,1\nb,\n", name="t39")
    assert server.get(endpoint + "?v__exact=")[2]["rows"] == [["b", ""]]
    assert server.get(endpoint + "?v__contains=")[2]["total"] == 2


# T39 — but an empty value is non-numeric for `less`/`greater`.
def test_t39_empty_value_for_numeric_comparators_is_400(server, fds):
    endpoint = fds(FILTER_ROWS, name="t39-num")
    assert server.get(endpoint + "?age__less=")[0] == 400


# T40 — `rowid` is not a filterable column.
def test_t40_rowid_is_not_filterable(server, fds):
    endpoint = fds(FILTER_ROWS, name="t40")
    status, _, data = server.get(endpoint + "?rowid__exact=1")
    assert status == 400, data
    assert data["ok"] is False


# T41 — filtering keeps the source row numbers; survivors are not renumbered.
def test_t41_filtering_does_not_renumber_rowid(server, fds):
    endpoint = fds(FILTER_ROWS, name="t41")
    data = server.get(endpoint + "?city__contains=ondon&_shape=objects")[2]
    assert [row["rowid"] for row in data["rows"]] == [1, 3]


# T42 — duplicates are per full key; two comparators on one column are legal.
def test_t42_duplicate_is_per_key_not_per_column(server, fds):
    endpoint = fds(FILTER_ROWS, name="t42")
    status, _, data = server.get(endpoint + "?age__greater=30&age__less=40")
    assert status == 200, data
    assert [r[0] for r in data["rows"]] == ["ada"]
    assert server.get(endpoint + "?age__greater=30&age__greater=40")[0] == 400


# T42 — a repeated key that is not a valid filter reports its own fault first.
def test_t42_repeated_invalid_key_is_still_400(server, fds):
    endpoint = fds(FILTER_ROWS, name="t42-bad")
    assert server.get(endpoint + "?nope__exact=1&nope__exact=2")[0] == 400
    assert server.get(endpoint + "?name__nope=1&name__nope=2")[0] == 400


# --------------------------------------------------------------------------
# T44-T56 — export, upload, and multi-format ingestion
# --------------------------------------------------------------------------
from conftest import make_xls, make_xlsx, read_csv_bytes  # noqa: E402

EXP_PEOPLE = ("name,age,city\n"
              "ada,36,London\n"
              "grace,45,New York\n"
              "lin,29,london\n"
              "Ada,50,Paris\n")
EXP_MANY = "n,tag\n" + "".join("%d,%s\n" % (i, "even" if i % 2 == 0 else "odd")
                               for i in range(1, 121))


@pytest.fixture
def eds(server, csv_url):
    """Convert a CSV body; return its /datasets/<id> endpoint path."""
    def make(body, name="amb"):
        url = csv_url(body, name=name)
        status, _, data = server.convert(url)
        assert status == 200, data
        return data["endpoint"]
    return make


# T44 — export reuses the query defaults, so a bare export is one page (100).
def test_t44_export_uses_default_page_size(server, eds):
    endpoint = eds(EXP_MANY, name="t44")
    rows = read_csv_bytes(server.raw(endpoint + "/export")[2])
    assert len(rows) == 101  # header + 100 data rows
    assert rows[1][0] == "1" and rows[-1][0] == "100"


# T44 — an explicit `_size` still widens the page.
def test_t44_export_size_overrides_default(server, eds):
    endpoint = eds(EXP_MANY, name="t44-size")
    rows = read_csv_bytes(server.raw(endpoint + "/export?_size=500")[2])
    assert len(rows) == 121


# T45 — the exported CSV starts with the column names.
def test_t45_export_has_header_row(server, eds):
    endpoint = eds(EXP_PEOPLE, name="t45")
    rows = read_csv_bytes(server.raw(endpoint + "/export")[2])
    assert rows[0] == ["name", "age", "city"]
    assert rows[1] == ["ada", "36", "London"]


# T46 — `_shape`/`_rowid`/`_total` are still validated on /export.
@pytest.mark.parametrize("query", ["?_shape=bogus", "?_rowid=yes",
                                   "?_total=maybe"])
def test_t46_export_validates_ignored_controls(server, eds, query):
    endpoint = eds(EXP_PEOPLE, name="t46")
    status, _, data = server.get(endpoint + "/export" + query)
    assert status == 400, data
    assert data["ok"] is False


# T46 — valid values of those controls are accepted and change nothing.
def test_t46_valid_ignored_controls_are_accepted(server, eds):
    endpoint = eds(EXP_PEOPLE, name="t46-ok")
    plain = server.raw(endpoint + "/export")[2]
    assert server.raw(endpoint + "/export?_shape=objects&_total=hide")[2] == plain


# T47 — /export on an unknown id is a 404 JSON envelope, not an empty CSV.
def test_t47_export_unknown_id_is_404_json(server):
    status, headers, data = server.get("/datasets/0123456789abcdef/export")
    assert status == 404
    assert data["ok"] is False
    assert "json" in headers.get("Content-Type", "").lower()


# T48 — the upload id is a digest of the bytes; the filename is not part of it.
def test_t48_upload_id_ignores_filename(up):
    a = up.upload(EXP_PEOPLE, filename="one.csv")[2]["endpoint"]
    b = up.upload(EXP_PEOPLE, filename="two-completely-other.csv")[2]["endpoint"]
    assert a == b


# T48 — the id looks like the opaque hex digest /convert produces.
def test_t48_upload_id_is_opaque_hex(up):
    endpoint = up.upload(EXP_PEOPLE, filename="hex.csv")[2]["endpoint"]
    ident = endpoint[len("/datasets/"):]
    assert ident and all(c in "0123456789abcdef" for c in ident)


# T48 — the same bytes reaching /convert by URL keep their own URL-derived id.
def test_t48_upload_and_convert_ids_are_independent(up, server, csv_url):
    uploaded = up.upload(EXP_PEOPLE, filename="ind.csv")[2]["endpoint"]
    url = csv_url(EXP_PEOPLE, name="t48")
    converted = server.convert(url)[2]["endpoint"]
    assert uploaded != converted
    assert server.get(uploaded)[0] == 200
    assert server.get(converted)[0] == 200


# T49 — the 415/400 split is decided by the Content-Type header alone.
def test_t49_multipart_mixed_is_415(up):
    from conftest import BOUNDARY, multipart_body
    body = multipart_body([("file", "a.csv", "a,b\n1,2\n")])
    status, _, data = up.post(
        "/upload", body,
        content_type="multipart/mixed; boundary=%s" % BOUNDARY)
    assert status == 415, data
    assert data["ok"] is False


# T49 — a well-formed body under the right type is not a media-type error.
def test_t49_form_data_type_is_never_415(up):
    status, _, data = up.post(
        "/upload", b"garbage",
        content_type="multipart/form-data; boundary=----zzz")
    assert status == 400, data


# T50 — when both parts are present, `file` wins.
def test_t50_file_wins_over_attachment(up):
    file_body = "a,b\n1,2\n"
    other = "x,y\n8,9\n"
    status, _, data = up.upload(
        file_body, field="file", filename="f.csv",
        extra=[("attachment", "att.csv", other)])
    assert status == 200, data
    payload = up.get(data["endpoint"])[2]
    assert payload["columns"] == ["a", "b"]
    # The id is the digest of the chosen bytes only.
    solo = up.upload(file_body, field="file", filename="f.csv")[2]["endpoint"]
    assert data["endpoint"] == solo


# T51 — the format comes from the content, not the filename extension.
def test_t51_csv_bytes_named_xlsx_still_ingest(up):
    status, _, data = up.upload("a,b\n1,2\n", filename="lies.xlsx")
    assert status == 200, data
    assert up.get(data["endpoint"])[2]["columns"] == ["a", "b"]


def test_t51_xlsx_bytes_named_txt_still_ingest(up):
    raw = make_xlsx([("S", [["a", "b"], [1, 2]])])
    status, _, data = up.upload(raw, filename="workbook.txt")
    assert status == 200, data
    assert up.get(data["endpoint"])[2]["rows"] == [[1, 2]]


# T51 — /convert sniffs content too: the URL path carries no extension.
def test_t51_convert_sniffs_extensionless_url(server, origin):
    origin.add("/t51-no-extension", make_xlsx([("S", [["a", "b"], [1, 2]])]),
               content_type="application/octet-stream")
    status, _, data = server.convert(origin.base + "/t51-no-extension")
    assert status == 200, data
    assert server.get(data["endpoint"])[2]["rows"] == [[1, 2]]


# T52 — an unusable charset name is a 400 even for a workbook source.
def test_t52_invalid_charset_with_xlsx_is_400(server, origin):
    origin.add("/t52.xlsx", make_xlsx([("S", [["a", "b"], [1, 2]])]))
    status, _, data = server.convert(origin.base + "/t52.xlsx",
                                     charset="not-a-real-charset")
    assert status == 400, data
    assert data["ok"] is False


# T52 — a valid charset is accepted and simply unused for a workbook.
def test_t52_valid_charset_with_xlsx_is_ignored(server, origin):
    origin.add("/t52-ok.xlsx", make_xlsx([("S", [["a", "b"], [1, 2]])]))
    base = server.convert(origin.base + "/t52-ok.xlsx")[2]["endpoint"]
    with_cs = server.convert(origin.base + "/t52-ok.xlsx",
                             charset="cp1252")[2]["endpoint"]
    assert base == with_cs
    assert server.get(base)[2]["rows"] == [[1, 2]]


# T53 — native cell types: numbers stay numbers, blanks are "".
def test_t53_xlsx_numbers_and_blanks(up):
    raw = make_xlsx([("S", [["i", "f", "blank"], [36, 2.5, None]])])
    endpoint = up.upload(raw, filename="t53.xlsx")[2]["endpoint"]
    assert up.get(endpoint)[2]["rows"] == [[36, 2.5, ""]]


# T53 — boolean cells become JSON booleans.
def test_t53_xlsx_booleans(up):
    raw = make_xlsx([("S", [["flag"], [True], [False]])])
    endpoint = up.upload(raw, filename="t53-bool.xlsx")[2]["endpoint"]
    assert up.get(endpoint)[2]["rows"] == [[True], [False]]


# T53 — date/datetime cells become ISO-8601 text (dates keep no time part).
def test_t53_xlsx_dates_are_iso_text(up):
    import datetime
    raw = make_xlsx([("S", [["when"],
                            [datetime.datetime(2024, 1, 15)],
                            [datetime.datetime(2024, 1, 15, 8, 30)]])])
    endpoint = up.upload(raw, filename="t53-date.xlsx")[2]["endpoint"]
    assert up.get(endpoint)[2]["rows"] == [["2024-01-15"],
                                           ["2024-01-15T08:30:00"]]


# T53 — a text cell goes through the same inference the CSV path uses.
def test_t53_text_cells_use_csv_inference(up):
    raw = make_xlsx([("S", [["a", "b"], ["36", " ada "]])])
    endpoint = up.upload(raw, filename="t53-text.xlsx")[2]["endpoint"]
    assert up.get(endpoint)[2]["rows"] == [[36, "ada"]]


# T53 — .xls stores every number as a float; integral values narrow to int.
def test_t53_xls_integral_floats_narrow(up):
    raw = make_xls([("S", [["i", "f"], [36, 2.5]])])
    endpoint = up.upload(raw, filename="t53.xls")[2]["endpoint"]
    assert up.get(endpoint)[2]["rows"] == [[36, 2.5]]


# T54 — blank leading rows are dropped before the header is chosen.
def test_t54_blank_leading_rows_are_dropped(up):
    raw = make_xlsx([("S", [[None, None], ["a", "b"], [1, 2]])])
    endpoint = up.upload(raw, filename="t54-lead.xlsx")[2]["endpoint"]
    payload = up.get(endpoint)[2]
    assert payload["columns"] == ["a", "b"]
    assert payload["rows"] == [[1, 2]]


# T54 — blank rows between records are dropped, like blank CSV lines.
def test_t54_blank_interior_rows_are_dropped(up):
    raw = make_xlsx([("S", [["a", "b"], [1, 2], [None, None], [3, 4]])])
    endpoint = up.upload(raw, filename="t54-mid.xlsx")[2]["endpoint"]
    assert up.get(endpoint)[2]["rows"] == [[1, 2], [3, 4]]


# T54 — trailing all-empty columns are trimmed rather than named "".
def test_t54_trailing_empty_columns_are_trimmed(up):
    raw = make_xlsx([("S", [["a", "b", None], [1, 2, None]])])
    endpoint = up.upload(raw, filename="t54-col.xlsx")[2]["endpoint"]
    payload = up.get(endpoint)[2]
    assert payload["columns"] == ["a", "b"]
    assert payload["rows"] == [[1, 2]]


# T54 — a sheet with only blank rows is not tabular.
def test_t54_only_blank_rows_is_400(up):
    raw = make_xlsx([("S", [[None, None], [None, None]])])
    status, _, data = up.upload(raw, filename="t54-blank.xlsx")
    assert status == 400, data
    assert data["ok"] is False


# T55 — "first worksheet" is sheet index 0, even when it is hidden.
def test_t55_first_sheet_even_if_hidden(up):
    import io
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Hidden"
    ws.append(["a", "b"])
    ws.append([1, 2])
    ws.sheet_state = "hidden"
    second = wb.create_sheet("Visible")
    second.append(["x", "y"])
    second.append([8, 9])
    buf = io.BytesIO()
    wb.save(buf)
    endpoint = up.upload(buf.getvalue(), filename="t55.xlsx")[2]["endpoint"]
    assert up.get(endpoint)[2]["columns"] == ["a", "b"]


# T56 — CSV rendering: ints without a decimal point, blanks as empty fields.
def test_t56_export_value_rendering(server, csv_url):
    url = csv_url("i,f,blank\n36,2.5,\n", name="t56")
    endpoint = server.convert(url)[2]["endpoint"]
    raw = server.raw(endpoint + "/export")[2]
    assert read_csv_bytes(raw) == [["i", "f", "blank"], ["36", "2.5", ""]]
    assert b"36.0" not in raw
