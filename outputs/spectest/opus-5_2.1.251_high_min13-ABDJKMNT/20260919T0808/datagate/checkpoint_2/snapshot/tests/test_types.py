"""Spec section: Dataset Query type handling."""

import pytest

from datagate_core.values import infer_value


# Phrase: "Strings remain text."
def test_strings_remain_text(dataset):
    payload = dataset("name,note\nada,first programmer\ngrace,compiler\n")
    assert payload["rows"] == [["ada", "first programmer"], ["grace", "compiler"]]


# Phrase: "Integers/decimals are JSON numbers."
def test_integers_and_decimals_become_numbers(dataset):
    payload = dataset("count,ratio\n42,3.5\n-7,0.25\n")
    assert payload["rows"] == [[42, 3.5], [-7, 0.25]]
    assert all(isinstance(row[0], int) for row in payload["rows"])
    assert all(isinstance(row[1], float) for row in payload["rows"])


# Phrase: "Integers/decimals are JSON numbers." - signs and exponents.
@pytest.mark.parametrize(
    "text,expected",
    [("0", 0), ("+5", 5), ("-12", -12), ("3.0", 3.0), (".5", 0.5), ("2e3", 2000.0), ("-1.5e-2", -0.015)],
)
def test_numeric_spellings(text, expected):
    assert infer_value(text) == expected


# Phrase: "Time-like values (for example `08:30`, `9:15`, `12:00`) remain text."
def test_time_like_values_remain_text(dataset):
    payload = dataset("event,start\nstandup,08:30\nreview,9:15\nlunch,12:00\n")
    assert payload["rows"] == [["standup", "08:30"], ["review", "9:15"], ["lunch", "12:00"]]


# Phrase: "Time-like values ... remain text." - dates are not reformatted either (T5).
def test_dates_remain_text(dataset):
    payload = dataset("label,day\nlaunch,2024-01-31\nreview,03/04/2024\n")
    assert payload["rows"] == [["launch", "2024-01-31"], ["review", "03/04/2024"]]


# Phrase: "Strings remain text." - values that only look numeric stay text (T3).
@pytest.mark.parametrize("text", ["1,234", "$5.00", "12%", "1 2", "nan", "inf", "-infinity", "", "  "])
def test_non_numeric_values_stay_text(text):
    assert infer_value(text) == text


# Phrase: "Integers/decimals are JSON numbers." - surrounding whitespace (T3).
def test_padded_numbers_are_numbers():
    assert infer_value(" 42 ") == 42


# Phrase: "Integers/decimals are JSON numbers." - leading zeros convert (T3).
def test_leading_zero_integers_convert():
    assert infer_value("007") == 7


# Phrase: "Strings remain text." - booleans are not a spec type.
def test_booleans_remain_text(dataset):
    payload = dataset("name,active\nada,true\ngrace,FALSE\n")
    assert payload["rows"] == [["ada", "true"], ["grace", "FALSE"]]


# Phrase: "Type inference is deterministic." - same cell, same result, every time.
def test_type_inference_is_stable_per_cell(dataset):
    payload = dataset("a,b\n1,x\n2.5,y\nz,3\n")
    assert payload["rows"] == [[1, "x"], [2.5, "y"], ["z", 3]]


# Phrase: rows are rectangular against `columns` (T10).
def test_ragged_rows_are_aligned_to_the_header(dataset):
    payload = dataset("a,b,c\n1,2\n4,5,6,7\n")
    assert payload["rows"] == [[1, 2, ""], [4, 5, 6]]


# Phrase: empty cells stay text (T4).
def test_empty_cells_are_empty_strings(dataset):
    assert dataset("a,b\n1,\n,2\n")["rows"] == [[1, ""], ["", 2]]
