"""Spec section: Type handling -- unit level."""

import pytest

from datagate_core.inference import coerce_value


# Phrase: "Integers/decimals are JSON numbers."
@pytest.mark.parametrize(
    "text,expected",
    [("0", 0), ("42", 42), ("-7", -7), ("+3", 3), ("3.5", 3.5), (".5", 0.5), ("2.", 2.0),
     ("1e3", 1000.0), ("-2.5E-2", -0.025), (" 12 ", 12)],
)
def test_numeric_literals_become_numbers(text, expected):
    assert coerce_value(text) == expected


# Phrase: "Strings remain text." / "Time-like values ... remain text."
@pytest.mark.parametrize(
    "text",
    ["", "ada", "08:30", "9:15", "12:00", "2026-09-19", "1,234", "$5", "20%", "1_000",
     "nan", "inf", "12abc", "--5", "1.2.3"],
)
def test_non_numeric_literals_remain_text(text):
    assert coerce_value(text) == text


# Phrase: "Integers/decimals are JSON numbers." -- integers keep integer type.
def test_integer_and_decimal_python_types():
    assert isinstance(coerce_value("7"), int)
    assert isinstance(coerce_value("7.0"), float)
