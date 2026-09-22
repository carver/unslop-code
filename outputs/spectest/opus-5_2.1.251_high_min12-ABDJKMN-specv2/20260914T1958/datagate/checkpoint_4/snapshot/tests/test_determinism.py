"""Spec section: Determinism."""
from conftest import convert_ok, dataset, free_port


# ---------------------------------------------------------------------------
# Phrase: "Same `source` URL always maps to the same dataset id."
# Context: determinism within one running server.
# ---------------------------------------------------------------------------
def test_same_source_same_id_repeatedly(gate, origin):
    url = origin.add("/det-id.csv", "a,b\n1,2\n")
    ids = {gate.convert(source=url).json()["endpoint"] for _ in range(5)}
    assert len(ids) == 1


# ---------------------------------------------------------------------------
# Phrase: "Same `source` URL always maps to the same dataset id."
# Context: determinism across server processes -- ids cannot be per-process
#          counters (see AMBIGUITIES T1).
# ---------------------------------------------------------------------------
def test_same_source_same_id_across_restarts(gate, origin, fresh_gate):
    url = origin.add("/det-restart.csv", "a,b\n1,2\n")
    first = convert_ok(gate, url)
    other = fresh_gate(port=free_port(), address="127.0.0.1")
    assert convert_ok(other, url) == first


# ---------------------------------------------------------------------------
# Phrase: "`columns` and each row follow source column order."
# Context: determinism of ordering, including duplicate values.
# ---------------------------------------------------------------------------
def test_column_and_row_order_follows_source(gate, origin):
    url = origin.add("/det-order.csv", "c,a,b\n3,1,2\n30,10,20\n")
    body = dataset(gate, url)
    assert body["columns"] == ["c", "a", "b"]
    assert body["rows"] == [[3, 1, 2], [30, 10, 20]]


# ---------------------------------------------------------------------------
# Phrase: "`query_ms` is present and non-negative."
# Context: determinism guarantees about the timing field.
# ---------------------------------------------------------------------------
def test_query_ms_always_present_and_non_negative(gate, origin):
    url = origin.add("/det-qms.csv", "a\n1\n")
    endpoint = convert_ok(gate, url)
    for _ in range(3):
        body = gate.get(endpoint).json()
        assert "query_ms" in body
        assert isinstance(body["query_ms"], (int, float))
        assert body["query_ms"] >= 0


# ---------------------------------------------------------------------------
# Phrase: "Type inference is deterministic."
# Context: determinism; identical input yields identical typing every time.
# ---------------------------------------------------------------------------
def test_type_inference_is_stable(gate, origin):
    csv_text = "s,i,d,t,blank\nAlice,42,3.5,08:30,\n"
    url = origin.add("/det-types.csv", csv_text)
    endpoint = convert_ok(gate, url)
    payloads = []
    for _ in range(3):
        body = gate.get(endpoint).json()
        payloads.append((body["columns"], body["rows"]))
    assert payloads[0] == payloads[1] == payloads[2]
    assert payloads[0][1] == [["Alice", 42, 3.5, "08:30", ""]]


# ---------------------------------------------------------------------------
# Phrase: "Type inference is deterministic."
# Context: the same cell text types identically in different columns/rows.
# ---------------------------------------------------------------------------
def test_same_text_types_identically_everywhere(gate, origin):
    url = origin.add("/det-samecell.csv", "a,b\n7,7\n7,x\n")
    rows = dataset(gate, url)["rows"]
    assert rows == [[7, 7], [7, "x"]]


# ---------------------------------------------------------------------------
# Phrase: "Default row limit is 100."
# Context: determinism; the cap is applied to the head of the stored rows.
# ---------------------------------------------------------------------------
def test_default_limit_takes_the_first_100_in_order(gate, origin):
    csv_text = "n\n" + "".join(f"{i}\n" for i in range(150))
    url = origin.add("/det-limit.csv", csv_text)
    body = dataset(gate, url)
    assert body["rows"] == [[i] for i in range(100)]


# ---------------------------------------------------------------------------
# Phrase: "No dependence on clock/locale/timezone beyond `query_ms`."
# Context: determinism; a server running under a different TZ/locale returns
#          byte-identical data.
# ---------------------------------------------------------------------------
def test_no_timezone_or_locale_dependence(gate, origin, fresh_gate):
    csv_text = "when,amount,name\n08:30,1234.50,Ärger\n2024-01-02,0.5,b\n"
    url = origin.add("/det-tz.csv", csv_text)
    baseline = dataset(gate, url)

    exotic = fresh_gate(
        port=free_port(),
        address="127.0.0.1",
        env={"TZ": "Asia/Tokyo", "LC_ALL": "de_DE.UTF-8", "LANG": "de_DE.UTF-8"},
    )
    other = dataset(exotic, url)

    assert other["columns"] == baseline["columns"]
    assert other["rows"] == baseline["rows"]


# ---------------------------------------------------------------------------
# Phrase: "Same `source` URL always maps to the same dataset id."
# Context: the id is a function of the source URL only -- a different charset
#          does not fork the dataset (see AMBIGUITIES T2).
# ---------------------------------------------------------------------------
def test_charset_does_not_change_the_id(gate, origin):
    url = origin.add("/det-charset-id.csv", "name\nabc\n".encode("utf-8"))
    plain = convert_ok(gate, url)
    with_charset = convert_ok(gate, url, charset="utf-8")
    assert plain == with_charset
