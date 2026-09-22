"""Spec section: Determinism."""

import pytest

SIMPLE = "name,age\nalice,30\nbob,41\n"


# Phrase: "Same `source` URL always maps to the same dataset id."
def test_same_source_maps_to_same_id_across_calls(client, origin):
    origin.add("/det.csv", SIMPLE)
    source = origin.url("/det.csv")
    ids = {
        client.get("/convert", query_string={"source": source})
        .get_json()["endpoint"]
        for _ in range(5)
    }
    assert len(ids) == 1


# Phrase: "Same `source` URL always maps to the same dataset id."
# Context: the id survives a restart of the process, i.e. it is derived from the
# URL rather than from a counter or from object identity.
def test_id_is_derived_from_url_not_insertion_order(client, origin):
    import datagate

    origin.add("/det-a.csv", SIMPLE)
    origin.add("/det-b.csv", "x,y\n1,2\n")
    source_a, source_b = origin.url("/det-a.csv"), origin.url("/det-b.csv")

    first = client.get("/convert", query_string={"source": source_a}).get_json()[
        "endpoint"
    ]
    datagate.reset_store()
    client.get("/convert", query_string={"source": source_b})
    again = client.get("/convert", query_string={"source": source_a}).get_json()[
        "endpoint"
    ]
    assert first == again


# Phrase: "`columns` and each row follow source column order."
def test_column_order_preserved(dataset):
    payload = dataset("/det-order.csv", "c,a,b\n3,1,2\n").get_json()
    assert payload["columns"] == ["c", "a", "b"]
    assert payload["rows"] == [[3, 1, 2]]


# Phrase: "`query_ms` is present and non-negative."
def test_query_ms_non_negative_on_repeated_queries(dataset, client, convert):
    response = convert("/det-qms.csv", SIMPLE)
    endpoint = response.get_json()["endpoint"]
    for _ in range(5):
        payload = client.get(endpoint).get_json()
        assert payload["query_ms"] >= 0


# Phrase: "Type inference is deterministic."
def test_type_inference_is_repeatable(dataset, client, convert):
    csv_text = "s,i,d,t\nalice,30,3.2,08:30\n"
    endpoint = convert("/det-types.csv", csv_text).get_json()["endpoint"]
    payloads = [client.get(endpoint).get_json()["rows"] for _ in range(5)]
    assert all(rows == [["alice", 30, 3.2, "08:30"]] for rows in payloads)


# Phrase: "Type inference is deterministic."
# Context: the same token infers the same type regardless of its column or file.
def test_same_token_infers_same_type_everywhere(dataset):
    first = dataset("/det-t1.csv", "a,b\n42,42\n").get_json()["rows"][0]
    second = dataset("/det-t2.csv", "z,y\nq,42\n").get_json()["rows"][0]
    assert first == [42, 42]
    assert second[1] == 42


# Phrase: "Default row limit is 100."
def test_default_row_limit_is_100(dataset):
    csv_text = "i\tv\n" + "".join("{}\t{}\n".format(i, i) for i in range(500))
    payload = dataset("/det-limit.csv", csv_text).get_json()
    assert len(payload["rows"]) == 100


# Phrase: "Default row limit is 100."
# Context: repeated queries return the identical first-100 window.
def test_row_window_is_stable(convert, client):
    csv_text = "i,v\n" + "".join("{},{}\n".format(i, i) for i in range(300))
    endpoint = convert("/det-window.csv", csv_text).get_json()["endpoint"]
    first = client.get(endpoint).get_json()["rows"]
    second = client.get(endpoint).get_json()["rows"]
    assert first == second
    assert first[0] == [0, 0] and first[-1] == [99, 99]


# Phrase: "No dependence on clock/locale/timezone beyond `query_ms`."
def test_response_identical_apart_from_query_ms(convert, client):
    endpoint = convert("/det-clock.csv", SIMPLE).get_json()["endpoint"]
    first = client.get(endpoint).get_json()
    second = client.get(endpoint).get_json()
    first.pop("query_ms")
    second.pop("query_ms")
    assert first == second


# Phrase: "No dependence on clock/locale/timezone beyond `query_ms`."
# Context: values that a locale-aware parser would mangle stay stable.
@pytest.mark.parametrize(
    "name,token,expected",
    [
        ("decimal-comma", "1,5", "1,5"),   # 1.5 under a European locale
        ("thousands", "1 000", "1 000"),   # 1000 with a locale group separator
        ("nan", "nan", "nan"),             # not representable in JSON
        ("inf", "inf", "inf"),
        ("underscored", "1_000", "1_000"),  # Python literal syntax, not CSV data
        ("boolean", "true", "true"),
        ("empty", "", ""),
    ],
)
def test_locale_sensitive_tokens_stay_text(dataset, name, token, expected):
    csv_text = "a;b\n{};x\n".format(token)
    payload = dataset("/det-locale-{}.csv".format(name), csv_text).get_json()
    assert payload["rows"][0][0] == expected
