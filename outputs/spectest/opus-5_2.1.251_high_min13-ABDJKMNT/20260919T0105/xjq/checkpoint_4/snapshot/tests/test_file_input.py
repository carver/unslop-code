"""Reading the document from INFILE instead of stdin.

Spec section: "## Input Source"
"""

import json
import os

import pytest

DOC = "<root><item>alpha</item><item>beta</item></root>"


@pytest.fixture
def write_file(tmp_path):
    """Write `data` to a file under a temp dir and return its path as a str."""

    def _write(data, name="doc.xml"):
        path = tmp_path / name
        path.write_bytes(data.encode() if isinstance(data, str) else data)
        return str(path)

    return _write


# Spec: "`INFILE` takes precedence over stdin when both are present."
# Context: with a document on each source, the file's is the one queried.
def test_file_wins_over_stdin(run_xjq, write_file):
    source = write_file("<root><item>from-file</item></root>")
    result = run_xjq("//item/text()", source, stdin=DOC)
    assert result.returncode == 0
    assert result.lines == ["from-file"]


# Spec: "`INFILE` takes precedence over stdin when both are present."
# Context: stdin is not consulted at all, so unparseable stdin alongside a good
# file is not an error.
def test_unparseable_stdin_is_ignored_when_a_file_is_given(run_xjq, write_file):
    result = run_xjq("//item/text()", write_file(DOC), stdin="<not xml at all")
    assert result.returncode == 0
    assert result.lines == ["alpha", "beta"]


# Spec: "`INFILE` takes precedence over stdin when both are present."
# Context: "when both are present" — with no file, stdin still supplies the
# document.
def test_stdin_is_used_when_no_file_is_named(run_xjq):
    result = run_xjq("//item/text()", stdin=DOC)
    assert result.returncode == 0
    assert result.lines == ["alpha", "beta"]


# Spec: "`INFILE` takes precedence over stdin when both are present."
# Context: an empty stdin does not make the file any less preferred.
def test_file_is_read_with_empty_stdin(run_xjq, write_file):
    result = run_xjq("//item/text()", write_file(DOC), stdin="")
    assert result.returncode == 0
    assert result.lines == ["alpha", "beta"]


# Spec: "Additional positional args after `QUERY [INFILE]` are ignored."
# Context: a third positional neither errors nor displaces INFILE.
def test_third_positional_is_ignored(run_xjq, write_file):
    result = run_xjq("//item/text()", write_file(DOC), "extra")
    assert result.returncode == 0
    assert result.lines == ["alpha", "beta"]


# Spec: "Additional positional args after `QUERY [INFILE]` are ignored."
# Context: ignored means never opened — a nonexistent trailing path is fine.
def test_ignored_positionals_are_not_read(run_xjq, write_file):
    decoy = write_file("<root><item>decoy</item></root>", name="decoy.xml")
    result = run_xjq("//item/text()", write_file(DOC), decoy, "/no/such/file.xml")
    assert result.returncode == 0
    assert result.lines == ["alpha", "beta"]


# Spec: "Decode `INFILE` as UTF-8 text"
# Context: non-ASCII content survives the round trip.
def test_utf8_content_is_decoded(run_xjq, write_file):
    source = write_file("<root><item>caffè — ☕</item></root>")
    result = run_xjq("//item/text()", source)
    assert result.returncode == 0
    assert result.lines == ["caffè — ☕"]


# Spec: "a UTF-8 BOM is allowed"
# Context: a BOM ahead of XML does not make the file unparseable.
def test_bom_before_xml_is_allowed(run_xjq, write_file):
    source = write_file(b"\xef\xbb\xbf" + DOC.encode())
    result = run_xjq("//item/text()", source)
    assert result.returncode == 0
    assert result.lines == ["alpha", "beta"]


# Spec: "a UTF-8 BOM is allowed" + "Apply JSON auto-detection to file input"
# Context: the BOM is stripped before detection, so BOM-prefixed JSON is still
# detected as JSON.
def test_bom_before_json_is_allowed(run_xjq, write_file):
    source = write_file(b'\xef\xbb\xbf{"item": "alpha"}', name="doc.json")
    result = run_xjq("//item/text()", source)
    assert result.returncode == 0
    assert result.lines == ["alpha"]


# Spec: "a UTF-8 BOM is allowed"
# Context: the BOM is not content — it never reaches the document text.
def test_bom_is_not_part_of_the_document(run_xjq, write_file):
    source = write_file(b"\xef\xbb\xbf<root><item>alpha</item></root>")
    result = run_xjq("/root/item/text()", source)
    assert result.stdout == "alpha\n"


# Spec: "Decode `INFILE` as UTF-8 text" + "Missing/unreadable file"
# Context: bytes that are not valid UTF-8 cannot be decoded, so the file is
# unreadable. See AMBIGUITIES.md T29.
def test_non_utf8_file_is_an_error(run_xjq, write_file):
    source = write_file(b"<root><item>caff\xe8</item></root>")
    result = run_xjq("//item/text()", source)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr != ""


# Spec: "Apply JSON auto-detection to file input: treat as JSON object/array
# when detected"
# Context: a file holding a JSON object is converted to XML and queried.
def test_json_object_file_is_detected(run_xjq, write_file):
    source = write_file('{"user": {"name": "ada"}}', name="doc.json")
    result = run_xjq("//name/text()", source)
    assert result.returncode == 0
    assert result.lines == ["ada"]


# Spec: "Apply JSON auto-detection to file input"
# Context: a top-level JSON array becomes `<item>` children of `<root>`, the
# same as it does on stdin.
def test_json_array_file_is_detected(run_xjq, write_file):
    source = write_file('[1, 2, 3]', name="doc.json")
    result = run_xjq("//item/text()", source)
    assert result.lines == ["1", "2", "3"]


# Spec: "Apply JSON auto-detection to file input"
# Context: the `type` attributes of the conversion are present for file input
# too, so detection really went through the JSON path.
def test_json_file_conversion_carries_types(run_xjq, write_file):
    source = write_file('{"n": 1, "s": "x"}', name="doc.json")
    result = run_xjq("//n/@type", source)
    assert result.lines == ["int"]


# Spec: "otherwise parse as XML/HTML"
# Context: content that is not a JSON object or array goes to the XML parser,
# which is how an XML file gets parsed at all.
def test_non_json_file_is_parsed_as_xml(run_xjq, write_file):
    result = run_xjq("//item/text()", write_file(DOC))
    assert result.lines == ["alpha", "beta"]


# Spec: "treat as JSON object/array when detected, otherwise parse as XML/HTML"
# Context: a top-level JSON primitive is not an object or array, so it falls
# through to XML — where it fails to parse.
def test_json_primitive_file_falls_through_to_xml(run_xjq, write_file):
    result = run_xjq("//item", write_file('"just a string"', name="doc.json"))
    assert result.returncode == 1
    assert "xml" in result.stderr.lower() or "parse" in result.stderr.lower()


# Spec: "Apply JSON auto-detection to file input"
# Context: detection follows content, not the file extension.
def test_detection_ignores_the_file_extension(run_xjq, write_file):
    source = write_file('{"item": "alpha"}', name="doc.xml")
    result = run_xjq("//item/text()", source)
    assert result.lines == ["alpha"]


# Spec: "Missing/unreadable file: stderr message, exit code `1`."
# Context: the path does not exist.
def test_missing_file_reports_and_exits_one(run_xjq, tmp_path):
    result = run_xjq("//item", str(tmp_path / "absent.xml"))
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() != ""


# Spec: "Missing/unreadable file: stderr message, exit code `1`."
# Context: the message names the path that could not be read.
# See AMBIGUITIES.md T33.
def test_missing_file_message_names_the_path(run_xjq, tmp_path):
    missing = str(tmp_path / "absent.xml")
    result = run_xjq("//item", missing)
    assert "absent.xml" in result.stderr


# Spec: "Missing/unreadable file: stderr message, exit code `1`."
# Context: a directory can be opened but not read as a document.
def test_directory_as_infile_is_an_error(run_xjq, tmp_path):
    result = run_xjq("//item", str(tmp_path))
    assert result.returncode == 1
    assert result.stderr != ""


# Spec: "Missing/unreadable file: stderr message, exit code `1`."
# Context: a file whose permissions deny reading.
@pytest.mark.skipif(os.geteuid() == 0, reason="root reads regardless of mode")
def test_unreadable_file_is_an_error(run_xjq, write_file):
    source = write_file(DOC)
    os.chmod(source, 0o000)
    result = run_xjq("//item", source)
    assert result.returncode == 1
    assert result.stderr != ""


# Spec: "Missing/unreadable file" vs. base spec "Malformed/empty XML input"
# Context: an empty file is readable; it is the document that is empty, so the
# input error reports it. See AMBIGUITIES.md T35.
def test_empty_file_is_an_input_error(run_xjq, write_file):
    result = run_xjq("//item", write_file(""))
    assert result.returncode == 1
    assert "xml" in result.stderr.lower() or "parse" in result.stderr.lower()


# Spec: "`INFILE` takes precedence over stdin"
# Context: `-` is an ordinary path, not a name for stdin.
# See AMBIGUITIES.md T32.
def test_dash_infile_is_treated_as_a_path(run_xjq):
    result = run_xjq("//item/text()", "-", stdin=DOC)
    assert result.returncode == 1
    assert result.stdout == ""


# Spec: "Apply JSON auto-detection to file input"
# Context: an invalid JSON key in a file is invalid input, the same as on
# stdin.
def test_invalid_json_key_in_a_file_is_an_error(run_xjq, write_file):
    source = write_file(json.dumps({"not a name": 1}), name="doc.json")
    result = run_xjq("//item", source)
    assert result.returncode == 1
    assert result.stderr != ""
