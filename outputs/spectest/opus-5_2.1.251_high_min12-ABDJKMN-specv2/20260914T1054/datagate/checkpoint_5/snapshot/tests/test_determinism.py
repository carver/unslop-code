"""Spec section: Determinism."""
import os
from urllib.parse import quote

import datagate

CSV = "name,qty,when\nwidget,3,08:30\ngadget,4.5,9:15\n"


# Phrase: "Same `source` URL always maps to the same dataset id."
# Context: stable across repeated conversions within a process.
def test_stable_id_within_process(convert, origin):
    url = origin.add(CSV)
    ids = {convert(source=url)[1]["endpoint"] for _ in range(5)}
    assert len(ids) == 1


# Phrase: "Same `source` URL always maps to the same dataset id."
# Context: stable across independent app instances (i.e. across process restarts).
def test_stable_id_across_app_instances(origin):
    url = origin.add(CSV, path="/stable.csv")
    endpoints = []
    for _ in range(2):
        app = datagate.create_app()
        c = app.test_client()
        endpoints.append(c.get("/convert", query_string={"source": url}).get_json()["endpoint"])
    assert endpoints[0] == endpoints[1]


# Phrase: "Same `source` URL always maps to the same dataset id."
# Context: the id is a function of the URL string, not of the content it serves.
def test_id_depends_on_url_not_content(convert, origin):
    url = origin.add("a,b\n1,2\n", path="/mutable.csv")
    first = convert(source=url)[1]["endpoint"]
    origin.add("x,y,z\n7,8,9\n", path="/mutable.csv")
    second = convert(source=url)[1]["endpoint"]
    assert first == second


# Phrase: "Same `source` URL always maps to the same dataset id."  (see AMBIGUITIES T12)
# Context: T12 is now resolved by the caching section - a plain re-convert is a cache
# hit that keeps the stored data, and `force` is what refreshes it under the same id.
def test_reconvert_is_cached_and_force_refreshes(client, convert, origin):
    url = origin.add("a,b\n1,2\n", path="/refresh.csv")
    endpoint = convert(source=url)[1]["endpoint"]
    origin.add("x,y,z\n7,8,9\n", path="/refresh.csv")
    convert(source=url)
    assert client.get(endpoint).get_json()["columns"] == ["a", "b"]
    forced = client.get("/convert", query_string="source=%s&force" % quote(url, safe=""))
    assert forced.status_code == 200
    assert forced.get_json()["endpoint"] == endpoint
    assert client.get(endpoint).get_json()["columns"] == ["x", "y", "z"]


# Phrase: "`columns` and each row follow source column order."
# Context: order is byte-stable across repeated queries.
def test_repeated_queries_identical(client, convert, origin):
    _, payload = convert(source=origin.add(CSV))
    seen = {client.get(payload["endpoint"]).get_json()["columns"][0] for _ in range(3)}
    bodies = [client.get(payload["endpoint"]).get_json() for _ in range(3)]
    assert len(seen) == 1
    assert all(b["rows"] == bodies[0]["rows"] for b in bodies)
    assert all(b["columns"] == bodies[0]["columns"] for b in bodies)


# Phrase: "Type inference is deterministic."
# Context: the same input yields the same types every time and per-cell, not per-column.
def test_type_inference_deterministic(dataset):
    csv = "mixed\n1\nabc\n2.5\n08:30\n"
    results = [dataset(csv)[1]["rows"] for _ in range(3)]
    assert results[0] == [[1], ["abc"], [2.5], ["08:30"]]
    assert all(r == results[0] for r in results)


# Phrase: "`query_ms` is present and non-negative."
# Context: holds on every query, including repeat and empty-ish datasets.
def test_query_ms_always_non_negative(client, convert, origin):
    _, payload = convert(source=origin.add(CSV))
    for _ in range(3):
        body = client.get(payload["endpoint"]).get_json()
        assert "query_ms" in body and body["query_ms"] >= 0


# Phrase: "Default row limit is 100."
# Context: the cap is the default with no parameters supplied.
def test_default_limit_is_100(dataset):
    _, body = dataset("n\n" + "".join("%d\n" % i for i in range(120)))
    assert len(body["rows"]) == 100


# Phrase: "No dependence on clock/locale/timezone beyond `query_ms`."
# Context: results are identical under a shifted timezone and a non-C locale env.
def test_no_timezone_dependence(client, convert, origin):
    url = origin.add(CSV, path="/tzcheck.csv")
    _, payload = convert(source=url)
    baseline = client.get(payload["endpoint"]).get_json()
    old_tz, old_lc = os.environ.get("TZ"), os.environ.get("LC_ALL")
    try:
        os.environ["TZ"] = "Pacific/Kiritimati"
        os.environ["LC_ALL"] = "de_DE.UTF-8"
        if hasattr(__import__("time"), "tzset"):
            __import__("time").tzset()
        app = datagate.create_app()
        c = app.test_client()
        ep = c.get("/convert", query_string={"source": url}).get_json()["endpoint"]
        shifted = c.get(ep).get_json()
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        if old_lc is None:
            os.environ.pop("LC_ALL", None)
        else:
            os.environ["LC_ALL"] = old_lc
        __import__("time").tzset()
    assert ep == payload["endpoint"]
    assert shifted["columns"] == baseline["columns"]
    assert shifted["rows"] == baseline["rows"]


# Phrase: "No dependence on clock/locale/timezone beyond `query_ms`."
# Context: decimal parsing must not follow a comma-decimal locale.
def test_decimal_parsing_locale_independent(dataset):
    _, body = dataset("a;b\n3,5;2.5\n")
    assert body["rows"][0] == ["3,5", 2.5]
