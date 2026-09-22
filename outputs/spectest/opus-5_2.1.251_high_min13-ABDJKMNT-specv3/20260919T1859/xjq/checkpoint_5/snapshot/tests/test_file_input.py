"""Input source: reading INFILE, its precedence over stdin, and read failures."""

from conftest import BOOKS

JSON_DOC = '{"title": "From File", "n": 2}'


# Spec: "`INFILE` takes precedence over stdin when both are present."
def test_infile_wins_over_stdin(run_xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_text("<other><title>From File</title></other>")
    result = run_xjq("//title/text()", str(infile), stdin=BOOKS)
    assert result.returncode == 0
    assert result.stdout == "From File"


# Spec: "`INFILE` takes precedence over stdin when both are present." -- with no
# file argument stdin is still the input source.
def test_stdin_is_used_without_an_infile(run_xjq):
    assert run_xjq("//title/text()", stdin=BOOKS).stdout == "Dune\nLes Miserables"


# Spec: "`INFILE` takes precedence over stdin when both are present." -- stdin is
# not consulted at all, so unparseable stdin alongside a good file is harmless.
def test_broken_stdin_is_ignored_when_infile_is_given(run_xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_text("<r><title>Fine</title></r>")
    result = run_xjq("//title/text()", str(infile), stdin="<not well formed")
    assert result.returncode == 0
    assert result.stdout == "Fine"


# Spec: "Additional positional args after `QUERY [INFILE]` are ignored."
def test_extra_positional_args_are_ignored(run_xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_text("<r><title>Used</title></r>")
    result = run_xjq("//title/text()", str(infile), "extra", "/no/such/file", stdin="")
    assert result.returncode == 0
    assert result.stdout == "Used"


# Spec: "Additional positional args after `QUERY [INFILE]` are ignored." -- they
# are ignored with stdin as the source as well.
def test_extra_positional_args_after_a_stdin_run(run_xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_text("<r><title>Used</title></r>")
    result = run_xjq("//title/text()", str(infile), "ignored", stdin=BOOKS)
    assert result.stdout == "Used"


# Spec: "Decode `INFILE` as UTF-8 text"
def test_infile_is_decoded_as_utf8(run_xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_bytes("<r><t>café ☕</t></r>".encode("utf-8"))
    assert run_xjq("//t/text()", str(infile)).stdout == "café ☕"


# Spec: "a UTF-8 BOM is allowed" -- an XML file that starts with a BOM parses.
def test_utf8_bom_is_allowed_on_xml(run_xjq, tmp_path):
    infile = tmp_path / "bom.xml"
    infile.write_bytes(b"\xef\xbb\xbf<r><t>Boom</t></r>")
    result = run_xjq("//t/text()", str(infile))
    assert result.returncode == 0
    assert result.stdout == "Boom"


# Spec: "a UTF-8 BOM is allowed" -- the mark is not treated as document content,
# so JSON detection still sees a JSON object behind it.
def test_utf8_bom_is_allowed_on_json(run_xjq, tmp_path):
    infile = tmp_path / "bom.json"
    infile.write_bytes(b"\xef\xbb\xbf" + JSON_DOC.encode("utf-8"))
    result = run_xjq("//title/text()", str(infile))
    assert result.returncode == 0
    assert result.stdout == "From File"


# Spec: "Decode `INFILE` as UTF-8 text" -- bytes that are not UTF-8 cannot be
# decoded, which is an unreadable file (AMBIGUITIES T29).
def test_non_utf8_infile_is_an_error(run_xjq, tmp_path):
    infile = tmp_path / "latin1.xml"
    infile.write_bytes(b"<r><t>caf\xe9</t></r>")
    result = run_xjq("//t/text()", str(infile))
    assert result.returncode == 1
    assert result.stderr != ""
    assert result.stdout == ""


# Spec: "Apply JSON auto-detection to file input: treat as JSON object/array
# when detected"
def test_json_object_file_is_detected(run_xjq, tmp_path):
    infile = tmp_path / "doc.json"
    infile.write_text(JSON_DOC)
    assert run_xjq("//title/text()", str(infile)).stdout == "From File"
    assert run_xjq("//n/@type", str(infile)).stdout == "int"


# Spec: "Apply JSON auto-detection to file input" -- a top-level array too.
def test_json_array_file_is_detected(run_xjq, tmp_path):
    infile = tmp_path / "doc.json"
    infile.write_text('["a", "b"]')
    assert run_xjq("//item/text()", str(infile)).stdout == "a\nb"


# Spec: "otherwise parse as XML/HTML."
def test_non_json_file_is_parsed_as_xml(run_xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_text(BOOKS)
    assert run_xjq("//title/text()", str(infile)).stdout == "Dune\nLes Miserables"


# Spec: "otherwise parse as XML/HTML." -- a file that is neither JSON nor
# well-formed XML fails the way stdin does.
def test_unparseable_file_content_is_an_error(run_xjq, tmp_path):
    infile = tmp_path / "broken.xml"
    infile.write_text("<r><t></r>")
    result = run_xjq("//t", str(infile))
    assert result.returncode == 1
    assert "xml" in result.stderr.lower() or "parse" in result.stderr.lower()


# Spec: "Missing/unreadable file: stderr message, exit code `1`."
def test_missing_file_reports_and_exits_1(run_xjq, tmp_path):
    result = run_xjq("//t", str(tmp_path / "absent.xml"), stdin=BOOKS)
    assert result.returncode == 1
    assert result.stderr != ""
    assert result.stdout == ""


# Spec: "Missing/unreadable file: stderr message, exit code `1`." -- the message
# names the file that could not be read.
def test_missing_file_message_names_the_path(run_xjq, tmp_path):
    missing = tmp_path / "absent.xml"
    assert str(missing) in run_xjq("//t", str(missing)).stderr


# Spec: "Missing/unreadable file: stderr message, exit code `1`." -- a directory
# is not readable as a document either.
def test_directory_infile_is_an_error(run_xjq, tmp_path):
    result = run_xjq("//t", str(tmp_path))
    assert result.returncode == 1
    assert result.stderr != ""


# Spec: "Missing/unreadable file: stderr message, exit code `1`." -- a file whose
# permissions deny reading.
def test_unreadable_file_is_an_error(run_xjq, tmp_path):
    infile = tmp_path / "denied.xml"
    infile.write_text("<r/>")
    infile.chmod(0o000)
    try:
        result = run_xjq("//r", str(infile))
    finally:
        infile.chmod(0o644)
    assert result.returncode == 1
    assert result.stderr != ""
