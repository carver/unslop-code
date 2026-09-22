"""Interpretation choices recorded in AMBIGUITIES.md for file input,
`--first` and `--compact`.

Each section names the ambiguity entry it pins down.
"""

from conftest import CSS_DOC, DOC

FLAT_DOC = '<library><book id="b1"><title>Dune</title></book></library>'


# T27: XML node output is first-node-only with or without `--first`, so the
# flag is a no-op for node results.
def test_first_is_a_no_op_for_xml_nodes(xjq):
    assert xjq("-f", "//book", stdin=DOC).stdout == xjq("//book", stdin=DOC).stdout


# T28: `--first` truncates the result list before results that normalize to
# nothing are dropped, so a whitespace-only first result prints nothing.
def test_first_truncates_before_empty_results_are_dropped(xjq):
    result = xjq("-f", "//text()", stdin="<r>\n  <v>alpha</v>\n</r>")
    assert result.stdout == ""
    assert result.returncode == 0


# T29: compact XML output is newline-terminated like every other result.
def test_compact_output_ends_with_a_newline(xjq):
    assert xjq("-c", "//book", stdin=FLAT_DOC).stdout.endswith("</book>\n")


# T30: "no added pretty-print formatting" leaves the whitespace the source
# document already had; compact does not strip it either.
def test_compact_preserves_source_whitespace(xjq):
    out = xjq("-c", "//book", stdin=DOC).stdout
    assert out.startswith('<book id="b1" lang="en">\n    <title>Dune</title>')
    assert out.endswith("  </book>\n")


# T31: `--first` is applied to the final results, after `--text` extraction,
# so it always yields a single line.
def test_first_truncates_extracted_text_to_one_line(xjq):
    assert xjq("-f", "--text", "//p", stdin=CSS_DOC).stdout == "Hello\n"


# T32: a file that is not valid UTF-8 counts as unreadable.
def test_non_utf8_file_exits_one(xjq, tmp_path):
    infile = tmp_path / "doc.xml"
    infile.write_bytes(b"<r><v>\xff\xfe</v></r>")
    result = xjq("//v/text()", str(infile))
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr != ""


# T33: decoding as UTF-8 is a property of file input; stdin stays byte-exact,
# so a document that declares another encoding still parses there.
def test_stdin_keeps_its_declared_encoding(xjq):
    doc = '<?xml version="1.0" encoding="iso-8859-1"?><r><v>caf\xe9</v></r>'
    result = xjq("//v/text()", stdin=doc.encode("iso-8859-1"))
    assert result.returncode == 0
    assert result.stdout == "caf\xe9\n"


# T33: a BOM in front of a JSON document on stdin is tolerated as well, by
# json's own encoding detection rather than by the file-input rule.
def test_bom_on_stdin_is_tolerated(xjq):
    assert xjq("/root/title/text()", stdin='\ufeff{"title": "Dune"}').stdout == "Dune\n"


# T34: `-` is an ordinary path, not an alias for stdin.
def test_dash_infile_is_treated_as_a_path(xjq):
    result = xjq("//title/text()", "-", stdin=DOC)
    assert result.returncode == 1
    assert result.stderr != ""
