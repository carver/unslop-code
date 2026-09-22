"""Spec section: Input Source.

Where the document comes from: `INFILE` when it is given, stdin otherwise,
including decoding, JSON auto-detection and the unreadable-file error.
"""

from conftest import DOC, JSON_OBJECT


# Phrase: "`INFILE` takes precedence over stdin when both are present."
def test_infile_wins_over_stdin(xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_text("<library><book><title>From file</title></book></library>")
    result = xjq("//title/text()", str(infile), stdin=DOC)
    assert result.returncode == 0
    assert result.stdout == "From file\n"


# Phrase: "`INFILE` takes precedence over stdin when both are present."
# With no INFILE the document still comes from stdin.
def test_stdin_is_used_when_no_infile_is_given(xjq):
    assert xjq("//title/text()", stdin=DOC).stdout == "Dune\nLe Petit Prince\n"


# Phrase: "`INFILE` takes precedence over stdin when both are present."
# An empty stdin does not disturb a query answered from the file.
def test_infile_is_read_with_empty_stdin(xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_text(DOC)
    assert xjq("//book/@id", str(infile), stdin="").stdout == "b1\nb2\n"


# Phrase: "Additional positional args after `QUERY [INFILE]` are ignored."
def test_extra_positional_args_are_ignored(xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_text(DOC)
    result = xjq("//title/text()", str(infile), "extra", "more", stdin="")
    assert result.returncode == 0
    assert result.stdout == "Dune\nLe Petit Prince\n"


# Phrase: "Additional positional args after `QUERY [INFILE]` are ignored."
# The ignored args are not opened, so a bogus path among them is harmless.
def test_extra_positional_args_are_never_read(xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_text(DOC)
    result = xjq("//title/text()", str(infile), "/nonexistent/path.xml", stdin="")
    assert result.returncode == 0
    assert result.stderr == ""


# Phrase: "Decode `INFILE` as UTF-8 text"
def test_infile_is_decoded_as_utf8(xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_bytes("<r><v>héllo — wörld</v></r>".encode("utf-8"))
    assert xjq("//v/text()", str(infile)).stdout == "héllo — wörld\n"


# Phrase: "a UTF-8 BOM is allowed"
def test_infile_may_start_with_a_utf8_bom(xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_bytes(b"\xef\xbb\xbf<library><book><title>Dune</title></book></library>")
    result = xjq("//title/text()", str(infile))
    assert result.returncode == 0
    assert result.stdout == "Dune\n"


# Phrase: "Apply JSON auto-detection to file input: treat as JSON
#          object/array when detected"
def test_json_object_file_is_detected(xjq, tmp_path):
    infile = tmp_path / "doc.json"
    infile.write_text(JSON_OBJECT)
    assert xjq("/root/title/text()", str(infile)).stdout == "Dune\n"


# Phrase: "Apply JSON auto-detection to file input"
# A top-level array converts to `<item>` children just as it does on stdin.
def test_json_array_file_is_detected(xjq, tmp_path):
    infile = tmp_path / "doc.json"
    infile.write_text('[{"id": 1}, {"id": 2}]')
    assert xjq("/root/item/id/text()", str(infile)).stdout == "1\n2\n"


# Phrase: "a UTF-8 BOM is allowed" together with JSON auto-detection.
def test_json_file_with_a_bom_is_detected(xjq, tmp_path):
    infile = tmp_path / "doc.json"
    infile.write_bytes(b'\xef\xbb\xbf{"title": "Dune"}')
    assert xjq("/root/title/text()", str(infile)).stdout == "Dune\n"


# Phrase: "otherwise parse as XML/HTML"
def test_non_json_file_is_parsed_as_xml(xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_text(DOC)
    assert xjq("//book[@lang='fr']/title/text()", str(infile)).stdout == "Le Petit Prince\n"


# Phrase: "otherwise parse as XML/HTML"
# A malformed document in a file is the familiar XML parse error.
def test_malformed_file_is_an_xml_parse_error(xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_text("<library><book></library>")
    result = xjq("//book", str(infile))
    assert result.returncode == 1
    assert result.stdout == ""
    assert "xml" in result.stderr.lower() or "parse" in result.stderr.lower()


# Phrase: "Missing/unreadable file: stderr message, exit code `1`."
def test_missing_file_exits_one(xjq, tmp_path):
    result = xjq("//title/text()", str(tmp_path / "absent.xml"), stdin=DOC)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr != ""


# Phrase: "Missing/unreadable file: stderr message, exit code `1`."
# A directory cannot be read as a document either.
def test_unreadable_file_exits_one(xjq, tmp_path):
    result = xjq("//title/text()", str(tmp_path), stdin=DOC)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr != ""


# Phrase: "Missing/unreadable file: stderr message, exit code `1`."
# The message names the path that could not be read.
def test_missing_file_message_names_the_path(xjq, tmp_path):
    missing = tmp_path / "absent.xml"
    result = xjq("//title/text()", str(missing), stdin=DOC)
    assert "absent.xml" in result.stderr
