"""Spec section: Input Auto-Detection.

Which stdin payloads are taken as JSON, and what happens to the rest.
"""

import pytest

from conftest import DOC, HTMLISH_DOC, JSON_ARRAY, JSON_OBJECT


# Phrase: "Auto-detect stdin as JSON object/array" (object), without any flag
# asking for it.
def test_top_level_object_is_detected_as_json(xjq):
    result = xjq("//title/text()", stdin=JSON_OBJECT)
    assert result.returncode == 0
    assert result.stdout == "Dune\n"


# Phrase: "Auto-detect stdin as JSON object/array" (array).
def test_top_level_array_is_detected_as_json(xjq):
    result = xjq("//item/id/text()", stdin=JSON_ARRAY)
    assert result.returncode == 0
    assert result.stdout == "1\n2\n"


# Phrase: "Auto-detect stdin as JSON object/array" -- surrounding whitespace
# does not hide the document.
@pytest.mark.parametrize("payload", ['  {"a": 1}  ', '\n\t{"a": 1}\n'])
def test_whitespace_padded_json_is_detected(xjq, payload):
    assert xjq("//a/text()", stdin=payload).stdout == "1\n"


# Phrase: "Auto-detect stdin as JSON object/array" -- detection is on the
# input, so it applies in CSS mode too.
def test_json_detection_applies_in_css_mode(xjq):
    assert xjq("--css", "title", stdin=JSON_OBJECT).stdout == '<title type="str">Dune</title>\n'


# Phrase: "Top-level JSON primitives are not accepted as JSON input for this
# mode; they fall back to XML parsing."
@pytest.mark.parametrize("payload", ["42", '"text"', "true", "false", "null", "1.5"])
def test_top_level_primitives_fall_back_to_xml(xjq, payload):
    result = xjq("//a", stdin=payload)
    assert result.returncode == 1
    message = result.stderr.lower()
    assert "xml" in message or "parse" in message


# Phrase: "Input that fails JSON detection is parsed as XML/HTML."
def test_xml_input_still_parses_as_xml(xjq):
    assert xjq("//author/text()", stdin=DOC).stdout == "Frank Herbert\nAntoine de Saint-Exupery\n"


# Phrase: "Input that fails JSON detection is parsed as XML/HTML."
def test_html_shaped_input_still_parses(xjq):
    assert xjq("//a/@href", stdin=HTMLISH_DOC).stdout == "/one\n/two\n"


# Phrase: "Input that fails JSON detection is parsed as XML/HTML." -- an XML
# document whose text happens to contain JSON is still XML.
def test_xml_wrapping_json_text_is_parsed_as_xml(xjq):
    doc = '<payload>{"a": 1}</payload>'
    assert xjq("//payload/text()", stdin=doc).stdout == '{"a": 1}\n'


# Phrase: "Input that fails JSON detection is parsed as XML/HTML." -- malformed
# JSON is not JSON, so it takes the XML path and fails there.
@pytest.mark.parametrize("payload", ['{"a": }', "{'a': 1}", '{"a": 1}, {"b": 2}', "["])
def test_malformed_json_falls_back_to_xml_error(xjq, payload):
    result = xjq("//a", stdin=payload)
    assert result.returncode == 1
    message = result.stderr.lower()
    assert "xml" in message or "parse" in message
