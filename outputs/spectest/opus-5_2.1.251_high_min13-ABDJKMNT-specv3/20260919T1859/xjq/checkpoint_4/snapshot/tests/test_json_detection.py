"""Auto-detection of stdin as a JSON document or as XML/HTML."""

import json

from conftest import BOOKS


# Spec: "Auto-detect stdin as JSON object/array or XML/HTML." -- a JSON object
# on stdin is converted and queried without any flag asking for it.
def test_json_object_is_detected(run_xjq):
    result = run_xjq("/root/name/text()", stdin='{"name": "Ada"}')
    assert result.returncode == 0
    assert result.stdout == "Ada"


# Spec: "Auto-detect stdin as JSON object/array or XML/HTML." -- a JSON array
# on stdin is detected the same way.
def test_json_array_is_detected(run_xjq):
    result = run_xjq("/root/item/text()", stdin="[1, 2]")
    assert result.returncode == 0
    assert result.stdout == "1\n2"


# Spec: "Auto-detect stdin as JSON object/array or XML/HTML." -- detection
# tolerates the surrounding whitespace a pretty-printed document carries.
def test_detection_tolerates_surrounding_whitespace(run_xjq):
    stdin = '\n  {\n    "name": "Ada"\n  }\n'
    assert run_xjq("/root/name/text()", stdin=stdin).stdout == "Ada"


# Spec: "Auto-detect stdin as JSON object/array or XML/HTML." -- XML input is
# still parsed as XML, so detection does not disturb the existing mode.
def test_xml_input_is_still_parsed_as_xml(run_xjq):
    result = run_xjq("//book[@lang='fr']/title/text()", stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout == "Les Miserables"


# Spec: "Top-level JSON primitives are not accepted as JSON input for this
# mode; they fall back to XML parsing." -- a bare number is not JSON input, and
# is not well-formed XML either, so it fails as XML. See [T18].
def test_top_level_number_falls_back_to_xml(run_xjq):
    result = run_xjq("/root", stdin="123")
    assert result.returncode == 1
    assert result.stdout == ""
    assert "xml" in result.stderr.lower()


# Spec: "Top-level JSON primitives are not accepted as JSON input for this
# mode; they fall back to XML parsing." -- strings, booleans, and null behave
# the same way.
def test_other_top_level_primitives_fall_back_to_xml(run_xjq):
    for stdin in ['"text"', "true", "false", "null", "1.5"]:
        result = run_xjq("/root", stdin=stdin)
        assert result.returncode == 1, stdin
        assert "xml" in result.stderr.lower(), stdin


# Spec: "Top-level JSON primitives are not accepted as JSON input for this
# mode; they fall back to XML parsing." -- the fallback is a real XML parse, so
# a primitive that happens to be well-formed XML is queried as XML.
def test_primitive_fallback_parses_as_xml_when_possible(run_xjq):
    result = run_xjq("/x/text()", stdin="<x>123</x>")
    assert result.returncode == 0
    assert result.stdout == "123"


# Spec: "Input that fails JSON detection is parsed as XML/HTML." -- text that
# starts like JSON but does not parse is handed to the XML parser, whose error
# is the one reported. See [T18].
def test_malformed_json_is_reported_as_an_xml_failure(run_xjq):
    result = run_xjq("/root", stdin='{"a": }')
    assert result.returncode == 1
    assert "xml" in result.stderr.lower()


# Spec: "Input that fails JSON detection is parsed as XML/HTML." -- including
# an unterminated array.
def test_unterminated_array_is_reported_as_an_xml_failure(run_xjq):
    result = run_xjq("/root", stdin="[1, 2")
    assert result.returncode == 1
    assert "xml" in result.stderr.lower()


# Spec: "Input that fails JSON detection is parsed as XML/HTML." -- empty input
# is unchanged by detection and still fails as XML.
def test_empty_input_still_fails_as_xml(run_xjq):
    result = run_xjq("/root", stdin="")
    assert result.returncode == 1
    assert "xml" in result.stderr.lower()


# Spec: "Auto-detect stdin as JSON object/array or XML/HTML." -- a converted
# document is an ordinary document for every other feature, such as --css.
def test_converted_document_works_with_css_selectors(run_xjq):
    result = run_xjq("--css", "root > name::text", stdin='{"name": "Ada"}')
    assert result.returncode == 0
    assert result.stdout == "Ada"


# Spec: "Auto-detect stdin as JSON object/array or XML/HTML." -- and with the
# text-extraction flags.
def test_converted_document_works_with_text_flags(run_xjq):
    stdin = json.dumps({"outer": {"inner": "deep"}})
    assert run_xjq("--text-all", "/root/outer", stdin=stdin).stdout == "deep"
