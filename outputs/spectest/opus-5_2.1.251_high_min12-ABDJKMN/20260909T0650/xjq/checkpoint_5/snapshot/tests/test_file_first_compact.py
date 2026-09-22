"""Spec conformance tests for file input, --first, and --compact.

Spec: "File Input, First-Result, and Compact Output".

The spec is split into minimal logical phrases; each section quotes the phrase
(and the minimal context it needs) in a comment above the tests covering it.
Interpretation choices are cross-referenced as Tn -> AMBIGUITIES.md.
"""

import os
import textwrap

import pytest

from conftest import run_argv

# ---------------------------------------------------------------------------
# Documents used across sections.
# ---------------------------------------------------------------------------

SIMPLE = '<root><item id="one">a</item><item id="two">b</item>' \
         '<item id="three">c</item></root>'

FILE_DOC = '<root><item id="f1">file-a</item><item id="f2">file-b</item></root>'

STDIN_DOC = '<root><item id="s1">stdin-a</item><item id="s2">stdin-b</item></root>'

# Already-indented source: the difference between "pretty-print" and "compact"
# is visible only when the serializer either adds or does not add layout.
INDENTED = textwrap.dedent(
    """\
    <root>
      <a><b>x</b></a>
      <a><b>y</b></a>
    </root>
    """
)

JSON_DOC = '{"name": "widget", "count": 2, "tags": ["red", "blue"]}'


def write(tmp_path, name, data, encoding="utf-8"):
    """Write `data` (str or bytes) to tmp_path/name and return the path str."""
    path = tmp_path / name
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding=encoding)
    return str(path)


# ===========================================================================
# Section 1
# Phrase: "`-f`, `--first`: return only first result."
# Context: CLI Additions -- a new option on `python xjq.py [OPTIONS] QUERY [INFILE]`.
# ===========================================================================


def test_short_flag_f_is_accepted():
    r = run_argv(["-f", "//item/text()"], SIMPLE)
    assert r.returncode == 0, r.stderr
    assert r.stderr == ""


def test_long_flag_first_is_accepted():
    r = run_argv(["--first", "//item/text()"], SIMPLE)
    assert r.returncode == 0, r.stderr
    assert r.stderr == ""


def test_first_returns_only_the_first_result():
    # Three text results without the flag; exactly one with it.
    plain = run_argv(["//item/text()"], SIMPLE)
    assert plain.lines == ["a", "b", "c"]
    r = run_argv(["--first", "//item/text()"], SIMPLE)
    assert r.returncode == 0
    assert r.lines == ["a"]


def test_short_and_long_first_agree():
    short = run_argv(["-f", "//item/text()"], SIMPLE)
    long = run_argv(["--first", "//item/text()"], SIMPLE)
    assert short.stdout == long.stdout


def test_first_result_is_the_first_in_document_order():
    doc = "<root><a>1</a><a>2</a><a>3</a></root>"
    r = run_argv(["-f", "//a/text()"], doc)
    assert r.lines == ["1"]


def test_first_is_a_no_op_when_only_one_result_matches():
    r = run_argv(["-f", "//item[1]/text()"], SIMPLE)
    assert r.lines == ["a"]


def test_first_may_follow_the_query_argument():
    # argparse accepts interspersed options; the flag need not come first.
    r = run_argv(["//item/text()", "-f"], SIMPLE)
    assert r.returncode == 0
    assert r.lines == ["a"]


# ===========================================================================
# Section 2
# Phrase: "`-c`, `--compact`: compact output mode."
# Context: CLI Additions.
# ===========================================================================


def test_short_flag_c_is_accepted():
    r = run_argv(["-c", "//item"], SIMPLE)
    assert r.returncode == 0, r.stderr
    assert r.stderr == ""


def test_long_flag_compact_is_accepted():
    r = run_argv(["--compact", "//item"], SIMPLE)
    assert r.returncode == 0, r.stderr
    assert r.stderr == ""


def test_short_and_long_compact_agree():
    short = run_argv(["-c", "/root"], INDENTED)
    long = run_argv(["--compact", "/root"], INDENTED)
    assert short.stdout == long.stdout


def test_first_and_compact_combine():
    r = run_argv(["-f", "-c", "//a"], INDENTED)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "<a><b>x</b></a>"


def test_flags_can_be_bundled():
    r = run_argv(["-fc", "//a"], INDENTED)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "<a><b>x</b></a>"


# ===========================================================================
# Section 3
# Phrase: "`INFILE` takes precedence over stdin when both are present."
# Context: Input Source -- `python xjq.py [OPTIONS] QUERY [INFILE]`.
# ===========================================================================


def test_infile_wins_over_stdin_when_both_are_present(tmp_path):
    path = write(tmp_path, "doc.xml", FILE_DOC)
    r = run_argv(["//item/text()", path], STDIN_DOC)
    assert r.returncode == 0, r.stderr
    assert r.lines == ["file-a", "file-b"]


def test_stdin_is_used_when_no_infile_is_given():
    r = run_argv(["//item/text()"], STDIN_DOC)
    assert r.returncode == 0
    assert r.lines == ["stdin-a", "stdin-b"]


def test_infile_is_read_when_stdin_is_empty(tmp_path):
    path = write(tmp_path, "doc.xml", FILE_DOC)
    r = run_argv(["//item/@id", path], "")
    assert r.returncode == 0, r.stderr
    assert r.lines == ["f1", "f2"]


def test_malformed_stdin_is_ignored_when_infile_is_present(tmp_path):
    # Precedence means stdin is not consulted at all, not merged (T27).
    path = write(tmp_path, "doc.xml", FILE_DOC)
    r = run_argv(["//item/text()", path], "<not well formed")
    assert r.returncode == 0, r.stderr
    assert r.lines == ["file-a", "file-b"]


def test_infile_works_with_css_mode(tmp_path):
    path = write(tmp_path, "doc.xml", FILE_DOC)
    r = run_argv(["--css", "item::text", path], STDIN_DOC)
    assert r.returncode == 0, r.stderr
    assert r.lines == ["file-a", "file-b"]


# ===========================================================================
# Section 4
# Phrase: "Additional positional args after `QUERY [INFILE]` are ignored."
# Context: Input Source.
# ===========================================================================


def test_third_positional_argument_is_ignored(tmp_path):
    path = write(tmp_path, "doc.xml", FILE_DOC)
    r = run_argv(["//item/text()", path, "extra"], "")
    assert r.returncode == 0, r.stderr
    assert r.lines == ["file-a", "file-b"]


def test_many_extra_positional_arguments_are_ignored(tmp_path):
    path = write(tmp_path, "doc.xml", FILE_DOC)
    r = run_argv(["//item/text()", path, "a", "b", "c"], "")
    assert r.returncode == 0, r.stderr
    assert r.lines == ["file-a", "file-b"]


def test_extra_positional_naming_a_missing_file_is_still_ignored(tmp_path):
    # Only the second positional is INFILE; later ones are never opened (T28).
    path = write(tmp_path, "doc.xml", FILE_DOC)
    r = run_argv(["//item/text()", path, str(tmp_path / "nope.xml")], "")
    assert r.returncode == 0, r.stderr
    assert r.lines == ["file-a", "file-b"]


def test_extra_positional_with_stdin_input():
    # QUERY, then INFILE-position arg... there is none to skip here: the second
    # positional is INFILE, so a lone extra beyond it is required to be ignored.
    r = run_argv(["//item/text()", "-", "ignored"], STDIN_DOC)
    # Whatever "-" means (T29), the third arg must not change the outcome.
    same = run_argv(["//item/text()", "-"], STDIN_DOC)
    assert r.returncode == same.returncode
    assert r.stdout == same.stdout


def test_unknown_option_is_still_an_error():
    # "Additional positional args" are ignored; unknown *options* are not (T28).
    r = run_argv(["--bogus", "//item/text()"], SIMPLE)
    assert r.returncode != 0
    assert r.stdout == ""


# ===========================================================================
# Section 5
# Phrase: "Decode `INFILE` as UTF-8 text; a UTF-8 BOM is allowed."
# Context: Input Source.
# ===========================================================================


def test_infile_is_decoded_as_utf8(tmp_path):
    doc = "<root><item>café über 中文</item></root>"
    path = write(tmp_path, "utf8.xml", doc)
    r = run_argv(["//item/text()", path], "")
    assert r.returncode == 0, r.stderr
    assert r.lines == ["café über 中文"]


def test_utf8_bom_is_allowed_on_xml_input(tmp_path):
    path = write(tmp_path, "bom.xml", b"\xef\xbb\xbf" + FILE_DOC.encode("utf-8"))
    r = run_argv(["//item/text()", path], "")
    assert r.returncode == 0, r.stderr
    assert r.lines == ["file-a", "file-b"]


def test_utf8_bom_is_allowed_on_json_input(tmp_path):
    # The BOM must not defeat JSON auto-detection (T30).
    path = write(tmp_path, "bom.json", b"\xef\xbb\xbf" + JSON_DOC.encode("utf-8"))
    r = run_argv(["//name/text()", path], "")
    assert r.returncode == 0, r.stderr
    assert r.lines == ["widget"]


def test_bom_is_not_emitted_in_output(tmp_path):
    path = write(tmp_path, "bom.xml", b"\xef\xbb\xbf" + FILE_DOC.encode("utf-8"))
    r = run_argv(["//item[1]", path], "")
    assert "﻿" not in r.stdout


def test_xml_declaration_in_file_is_accepted(tmp_path):
    doc = '<?xml version="1.0" encoding="UTF-8"?>\n' + FILE_DOC
    path = write(tmp_path, "decl.xml", doc)
    r = run_argv(["//item/text()", path], "")
    assert r.returncode == 0, r.stderr
    assert r.lines == ["file-a", "file-b"]


def test_non_utf8_file_is_an_error(tmp_path):
    # Latin-1 bytes are not decodable as UTF-8: unreadable as UTF-8 text (T31).
    path = write(tmp_path, "latin1.xml", "<root><a>café</a></root>".encode("latin-1"))
    r = run_argv(["//a/text()", path], "")
    assert r.returncode == 1
    assert r.stdout == ""
    assert r.stderr != ""


# ===========================================================================
# Section 6
# Phrase: "Apply JSON auto-detection to file input: treat as JSON object/array
#          when detected, otherwise parse as XML/HTML."
# Context: Input Source.
# ===========================================================================


def test_json_object_file_is_converted(tmp_path):
    path = write(tmp_path, "doc.json", JSON_DOC)
    r = run_argv(["//name/text()", path], "")
    assert r.returncode == 0, r.stderr
    assert r.lines == ["widget"]


def test_json_array_file_is_converted(tmp_path):
    path = write(tmp_path, "arr.json", '["x", "y"]')
    r = run_argv(["//item/text()", path], "")
    assert r.returncode == 0, r.stderr
    assert r.lines == ["x", "y"]


def test_json_file_conversion_matches_stdin_conversion(tmp_path):
    path = write(tmp_path, "doc.json", JSON_DOC)
    from_file = run_argv(["/root", path], "")
    from_stdin = run_argv(["/root"], JSON_DOC)
    assert from_file.stdout == from_stdin.stdout


def test_json_type_attributes_are_present_for_file_input(tmp_path):
    path = write(tmp_path, "doc.json", JSON_DOC)
    r = run_argv(["//count/@type", path], "")
    assert r.lines == ["int"]


def test_non_json_file_is_parsed_as_xml(tmp_path):
    path = write(tmp_path, "doc.xml", FILE_DOC)
    r = run_argv(["//item/@id", path], "")
    assert r.lines == ["f1", "f2"]


def test_json_primitive_file_is_not_treated_as_json(tmp_path):
    # Only objects/arrays are JSON; a bare string falls through to XML (T19).
    path = write(tmp_path, "prim.json", '"hello"')
    r = run_argv(["//x", path], "")
    assert r.returncode == 1
    assert r.stderr != ""


def test_html_like_file_is_parsed_as_xml(tmp_path):
    path = write(tmp_path, "doc.html", "<html><body><p>hi</p></body></html>")
    r = run_argv(["//p/text()", path], "")
    assert r.returncode == 0, r.stderr
    assert r.lines == ["hi"]


# ===========================================================================
# Section 7
# Phrase: "Missing/unreadable file: stderr message, exit code `1`."
# Context: Input Source.
# ===========================================================================


def test_missing_file_exits_one(tmp_path):
    r = run_argv(["//item/text()", str(tmp_path / "nope.xml")], "")
    assert r.returncode == 1


def test_missing_file_writes_a_message_to_stderr(tmp_path):
    r = run_argv(["//item/text()", str(tmp_path / "nope.xml")], "")
    assert r.stderr.strip() != ""
    assert r.stdout == ""


def test_missing_file_message_names_the_path(tmp_path):
    missing = str(tmp_path / "nope.xml")
    r = run_argv(["//item/text()", missing], "")
    assert "nope.xml" in r.stderr


def test_missing_file_does_not_fall_back_to_stdin(tmp_path):
    r = run_argv(["//item/text()", str(tmp_path / "nope.xml")], STDIN_DOC)
    assert r.returncode == 1
    assert r.stdout == ""


def test_directory_as_infile_is_an_error(tmp_path):
    r = run_argv(["//item/text()", str(tmp_path)], "")
    assert r.returncode == 1
    assert r.stderr != ""
    assert r.stdout == ""


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any file")
def test_unreadable_file_is_an_error(tmp_path):
    path = write(tmp_path, "secret.xml", FILE_DOC)
    os.chmod(path, 0o000)
    try:
        r = run_argv(["//item/text()", path], "")
    finally:
        os.chmod(path, 0o644)
    assert r.returncode == 1
    assert r.stderr != ""
    assert r.stdout == ""


# ===========================================================================
# Section 8
# Phrase: "`--first` applies across text, attribute, and XML-node results."
# Context: Output Rules.
# ===========================================================================


def test_first_applies_to_text_results():
    r = run_argv(["-f", "//item/text()"], SIMPLE)
    assert r.lines == ["a"]


def test_first_applies_to_attribute_results():
    r = run_argv(["-f", "//item/@id"], SIMPLE)
    assert r.lines == ["one"]


def test_first_applies_to_xml_node_results():
    r = run_argv(["-f", "//item"], SIMPLE)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == '<item id="one">a</item>'
    assert "two" not in r.stdout


def test_first_applies_to_css_text_results():
    r = run_argv(["--css", "-f", "item::text"], SIMPLE)
    assert r.lines == ["a"]


def test_first_applies_to_css_node_results():
    r = run_argv(["--css", "-f", "item"], SIMPLE)
    assert r.stdout.strip() == '<item id="one">a</item>'


def test_first_applies_after_text_extraction_flag():
    # -t turns each matched element into its text nodes; --first keeps one
    # result of the final set (T32).
    doc = "<root><a>one<b/>two</a><a>three</a></root>"
    r = run_argv(["-t", "-f", "//a"], doc)
    assert r.lines == ["one"]


def test_first_on_a_scalar_result_is_unchanged():
    plain = run_argv(["count(//item)"], SIMPLE)
    r = run_argv(["-f", "count(//item)"], SIMPLE)
    assert r.stdout == plain.stdout


def test_first_applies_to_json_derived_results():
    r = run_argv(["-f", "//item/text()"], '["x", "y", "z"]')
    assert r.lines == ["x"]


def test_without_first_all_text_results_are_printed():
    r = run_argv(["//item/text()"], SIMPLE)
    assert r.lines == ["a", "b", "c"]


# ===========================================================================
# Section 9
# Phrase: "`--first` with no matches remains silent (no output)."
# Context: Output Rules.
# ===========================================================================


def test_first_with_no_matches_writes_nothing():
    r = run_argv(["-f", "//missing/text()"], SIMPLE)
    assert r.stdout == ""
    assert r.stderr == ""


def test_first_with_no_matches_exits_zero():
    r = run_argv(["-f", "//missing/text()"], SIMPLE)
    assert r.returncode == 0


def test_first_with_no_node_matches_writes_nothing():
    r = run_argv(["-f", "//missing"], SIMPLE)
    assert r.stdout == ""
    assert r.stderr == ""
    assert r.returncode == 0


def test_first_with_no_css_matches_writes_nothing():
    r = run_argv(["--css", "-f", "nosuch"], SIMPLE)
    assert r.stdout == ""
    assert r.stderr == ""
    assert r.returncode == 0


# ===========================================================================
# Section 10
# Phrase: "`--compact` affects XML serialization only: compact XML output has
#          no added pretty-print formatting."
# Context: Output Rules.
# ===========================================================================


def test_compact_node_output_is_a_single_line_for_single_line_source():
    doc = "<root><a>1</a><b>2</b></root>"
    r = run_argv(["-c", "/root"], doc)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "<root><a>1</a><b>2</b></root>"


def test_pretty_output_adds_formatting_that_compact_does_not():
    doc = "<root><a>1</a><b>2</b></root>"
    pretty = run_argv(["/root"], doc)
    compact = run_argv(["-c", "/root"], doc)
    assert len(pretty.stdout.splitlines()) > 1
    assert len(compact.stdout.splitlines()) == 1


def test_compact_does_not_reformat_nested_nodes():
    r = run_argv(["-c", "//a[1]"], INDENTED)
    assert r.stdout.strip() == "<a><b>x</b></a>"


def test_compact_preserves_whitespace_already_in_the_source():
    # "no *added* formatting": existing layout is neither added to nor removed.
    doc = "<root>\n  <a/>\n</root>"
    r = run_argv(["-c", "/root"], doc)
    assert r.stdout.rstrip("\n") == "<root>\n  <a/>\n</root>"


def test_compact_does_not_change_text_results():
    plain = run_argv(["//item/text()"], SIMPLE)
    compact = run_argv(["-c", "//item/text()"], SIMPLE)
    assert compact.stdout == plain.stdout


def test_compact_does_not_change_attribute_results():
    plain = run_argv(["//item/@id"], SIMPLE)
    compact = run_argv(["-c", "//item/@id"], SIMPLE)
    assert compact.stdout == plain.stdout


def test_compact_does_not_change_scalar_results():
    plain = run_argv(["count(//item)"], SIMPLE)
    compact = run_argv(["-c", "count(//item)"], SIMPLE)
    assert compact.stdout == plain.stdout


def test_compact_does_not_change_css_text_results():
    plain = run_argv(["--css", "item::text"], SIMPLE)
    compact = run_argv(["--css", "-c", "item::text"], SIMPLE)
    assert compact.stdout == plain.stdout


def test_compact_applies_to_css_node_results():
    r = run_argv(["--css", "-c", "a"], INDENTED)
    assert r.stdout.strip() == "<a><b>x</b></a>"


def test_compact_node_output_is_newline_terminated():
    # T33: compact output is still a line of output.
    r = run_argv(["-c", "//a[1]"], INDENTED)
    assert r.stdout.endswith("\n")


def test_compact_omits_the_xml_declaration():
    doc = '<?xml version="1.0" encoding="UTF-8"?><root><a>1</a></root>'
    r = run_argv(["-c", "/root"], doc)
    assert "<?xml" not in r.stdout


def test_compact_keeps_attributes_and_empty_elements():
    doc = '<root><a id="1"/><a id="2"/></root>'
    r = run_argv(["-c", "/root"], doc)
    assert r.stdout.strip() == '<root><a id="1"/><a id="2"/></root>'


def test_compact_does_not_include_the_tail_text():
    doc = "<root><a>1</a>tail-text</root>"
    r = run_argv(["-c", "//a"], doc)
    assert r.stdout.strip() == "<a>1</a>"


# ===========================================================================
# Section 11
# Phrase: "For JSON-derived input, `--compact` still applies to resulting XML
#          output."
# Context: Output Rules.
# ===========================================================================


def test_compact_applies_to_json_derived_xml():
    r = run_argv(["-c", "/root"], '{"a": 1}')
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == '<root><a type="int">1</a></root>'


def test_json_derived_pretty_output_differs_from_compact():
    pretty = run_argv(["/root"], JSON_DOC)
    compact = run_argv(["-c", "/root"], JSON_DOC)
    assert len(pretty.stdout.splitlines()) > 1
    assert len(compact.stdout.splitlines()) == 1


def test_compact_applies_to_a_json_derived_subtree():
    r = run_argv(["-c", "//tags"], JSON_DOC)
    assert r.stdout.strip() == (
        '<tags type="list"><item type="str">red</item>'
        '<item type="str">blue</item></tags>'
    )


def test_compact_applies_to_json_from_a_file(tmp_path):
    path = write(tmp_path, "doc.json", '{"a": 1}')
    r = run_argv(["-c", "/root", path], "")
    assert r.stdout.strip() == '<root><a type="int">1</a></root>'


def test_first_and_compact_on_json_derived_nodes():
    r = run_argv(["-f", "-c", "//item"], '["x", "y"]')
    assert r.stdout.strip() == '<item type="str">x</item>'


def test_compact_json_text_results_are_unaffected():
    plain = run_argv(["//item/text()"], '["x", "y"]')
    compact = run_argv(["-c", "//item/text()"], '["x", "y"]')
    assert compact.stdout == plain.stdout


# ===========================================================================
# Section 12
# Phrase: cross-cutting -- new flags combine with the file input source.
# Context: whole spec.
# ===========================================================================


def test_first_with_infile(tmp_path):
    path = write(tmp_path, "doc.xml", FILE_DOC)
    r = run_argv(["-f", "//item/text()", path], STDIN_DOC)
    assert r.lines == ["file-a"]


def test_compact_with_infile(tmp_path):
    path = write(tmp_path, "doc.xml", INDENTED)
    r = run_argv(["-c", "//a[1]", path], "")
    assert r.stdout.strip() == "<a><b>x</b></a>"


def test_all_flags_together_with_infile(tmp_path):
    path = write(tmp_path, "doc.xml", INDENTED)
    r = run_argv(["--css", "-f", "-c", "a", path], "")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "<a><b>x</b></a>"


def test_first_and_compact_do_not_break_error_reporting(tmp_path):
    r = run_argv(["-f", "-c", "//item", str(tmp_path / "nope.xml")], "")
    assert r.returncode == 1
    assert r.stdout == ""
    assert r.stderr != ""
