"""Spec section: CSV Parsing -- charset handling."""

import pytest

from datagate_core.decoding import decode_csv_bytes
from datagate_core.errors import DatagateError

LATIN1 = "name,city\nrené,münchen\n".encode("cp1252")


# Phrase: "If `/convert` receives `charset`, use it to decode bytes."
def test_explicit_charset_is_used(client, origin):
    source = origin.serve("/data.csv", LATIN1)

    convert = client.get("/convert", query_string={"source": source, "charset": "cp1252"})
    body = client.get(convert.get_json()["endpoint"]).get_json()

    assert body["rows"] == [["rené", "münchen"]]


# Phrase: "If `/convert` receives `charset`, use it to decode bytes."
# Context: the same bytes read through a different codec give different text.
def test_explicit_charset_overrides_detection(client, origin):
    source = origin.serve("/data.csv", "a,b\nx,é\n".encode("utf-8"))

    convert = client.get("/convert", query_string={"source": source, "charset": "latin-1"})
    body = client.get(convert.get_json()["endpoint"]).get_json()

    assert body["rows"] == [["x", "Ã©"]]


# Phrase: "Otherwise detect encoding."
def test_utf8_is_detected_without_charset(client, origin):
    source = origin.serve("/data.csv", "name,city\nada,münchen\n".encode("utf-8"))

    convert = client.get("/convert", query_string={"source": source})
    body = client.get(convert.get_json()["endpoint"]).get_json()

    assert body["rows"] == [["ada", "münchen"]]


# Phrase: "Otherwise detect encoding." -- context: a UTF-8 BOM is not part of the first column name.
def test_utf8_bom_is_stripped(client, origin):
    source = origin.serve("/data.csv", "name,age\nada,36\n".encode("utf-8-sig"))

    convert = client.get("/convert", query_string={"source": source})
    body = client.get(convert.get_json()["endpoint"]).get_json()

    assert body["columns"] == ["name", "age"]


# Phrase: "Unsupported or malformed `charset`" -- unit level.
@pytest.mark.parametrize("charset", ["klingon-9", "", "utf-42"])
def test_unusable_charset_names_raise(charset):
    with pytest.raises(DatagateError) as raised:
        decode_csv_bytes(b"a,b\n1,2\n", charset)

    assert raised.value.status == 400


# Phrase: "Unsupported or malformed `charset`" -- context: undecodable bytes (AMBIGUITIES T4).
def test_undecodable_bytes_raise():
    with pytest.raises(DatagateError) as raised:
        decode_csv_bytes("é".encode("utf-8"), "ascii")

    assert raised.value.status == 400


# Phrase: "charset ... Character encoding for decoding CSV bytes." -- alias spellings work.
@pytest.mark.parametrize("charset", ["UTF-8", "utf8", "Latin-1"])
def test_codec_aliases_are_accepted(charset):
    assert decode_csv_bytes(b"a,b\n1,2\n", charset) == "a,b\n1,2\n"
