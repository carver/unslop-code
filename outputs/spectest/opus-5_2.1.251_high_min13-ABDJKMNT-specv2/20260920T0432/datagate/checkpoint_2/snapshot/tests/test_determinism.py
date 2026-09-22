"""Determinism guarantees."""

BODY = "name,age,start\nada,36,08:30\ngrace,45,9:15\n"


# Spec: "Same `source` URL always maps to the same dataset id."
# Context: the id is a function of the URL string, stable across app instances.
def test_dataset_id_is_stable_across_app_instances(origin):
    from gateway.app import create_app

    source = origin.serve("/determinism.csv", BODY)
    endpoints = []
    for _ in range(2):
        client = create_app().test_client()
        endpoints.append(
            client.get("/convert", query_string={"source": source}).get_json()["endpoint"]
        )
    assert endpoints[0] == endpoints[1]


# Spec: "columns and each row follow source column order." / "Type inference is
# deterministic."
# Context: repeated reads of one dataset return byte-identical payloads apart
# from the timing field.
def test_repeated_reads_are_identical(client, convert):
    endpoint = convert(BODY).get_json()["endpoint"]
    payloads = []
    for _ in range(3):
        body = client.get(endpoint).get_json()
        body.pop("query_ms")
        payloads.append(body)
    assert payloads[0] == payloads[1] == payloads[2]
    assert payloads[0]["columns"] == ["name", "age", "start"]
    assert payloads[0]["rows"] == [["ada", 36, "08:30"], ["grace", 45, "9:15"]]


# Spec: "No dependence on clock/locale/timezone beyond query_ms."
# Context: a shifted timezone and a comma-decimal locale environment must not
# change the payload.
def test_payload_is_independent_of_timezone(client, convert, monkeypatch):
    import time

    endpoint = convert(BODY).get_json()["endpoint"]
    before = client.get(endpoint).get_json()
    monkeypatch.setenv("TZ", "Pacific/Kiritimati")
    time.tzset()
    after = client.get(endpoint).get_json()
    monkeypatch.undo()
    time.tzset()
    assert before["rows"] == after["rows"]
    assert before["columns"] == after["columns"]
