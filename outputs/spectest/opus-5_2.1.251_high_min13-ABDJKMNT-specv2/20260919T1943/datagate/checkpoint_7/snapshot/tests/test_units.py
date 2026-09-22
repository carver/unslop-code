"""Unit-level checks for the parsing, typing and decoding helpers."""

import codecs

import pytest

from datagate_app.decoding import decode_document, detect_encoding
from datagate_app.errors import DataGateError
from datagate_app.parsing import infer_delimiter, parse_table
from datagate_app.values import coerce_value


# Phrase: "Integers/decimals are JSON numbers." / "Strings remain text."
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("42", 42),
        ("-7", -7),
        ("+7", 7),
        ("3.14", 3.14),
        (".5", 0.5),
        ("1e3", 1000.0),
        ("007", 7),
        ("ada", "ada"),
        ("", ""),
        ("1,234", "1,234"),
        ("nan", "nan"),
        ("08:30", "08:30"),
        ("9:15", "9:15"),
        ("12:00", "12:00"),
    ],
)
def test_value_coercion(raw, expected):
    assert coerce_value(raw) == expected


# Phrase: "minimum supported delimiters are `,`, `;`, and `\t`."
@pytest.mark.parametrize(
    ("text", "delimiter"),
    [
        ("a,b\n1,2\n", ","),
        ("a;b\n1;2\n", ";"),
        ("a\tb\n1\t2\n", "\t"),
        ("a|b\n1|2\n", "|"),
        ("only\nrows\n", ","),
    ],
)
def test_delimiter_inference(text, delimiter):
    assert infer_delimiter(text) == delimiter


# Phrase: "A valid file requires at least one header row and one data row."
def test_parse_table_rejects_header_only():
    with pytest.raises(DataGateError):
        parse_table("a,b\n")


# Phrase: "detect unambiguous encoding from content, else latin-1"
def test_detect_encoding():
    assert detect_encoding("plain".encode("utf-8")) == "utf-8"
    assert detect_encoding("zoë".encode("utf-8")) == "utf-8"
    assert detect_encoding(codecs.BOM_UTF8 + b"x") == "utf-8-sig"
    assert detect_encoding(codecs.BOM_UTF16_LE + "x".encode("utf-16-le")) == "utf-16"
    assert detect_encoding("résumé".encode("latin-1")) == "latin-1"


# Phrase: "| Unsupported or malformed `charset` | 400 |"
def test_decode_document_rejects_unknown_charset():
    with pytest.raises(DataGateError) as raised:
        decode_document(b"x", "utf-99")

    assert raised.value.status == 400
