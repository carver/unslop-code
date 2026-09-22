"""Spec tests for file input, --first and --compact, one section per phrase."""

import subprocess
import sys
from pathlib import Path

XJQ = Path(__file__).resolve().parent.parent / "xjq.py"

DOC = b"""<Root>
  <Item id="a">first</Item>
  <Item id="b">second</Item>
</Root>"""

FILE_DOC = "<Root><Item id='f'>from file</Item><Item id='g'>also file</Item></Root>"


def run(*args, stdin=b""):
    """Invoke `python xjq.py <args>` with `stdin` piped in."""
    return subprocess.run(
        [sys.executable, str(XJQ), *args],
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def out(result):
    return result.stdout.decode()


def err(result):
    return result.stderr.decode()


def write(tmp_path, content, name="doc.xml"):
    """Write `content` (str or bytes) to a file in `tmp_path` and return its path."""
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return str(path)


# --- CLI: "`-f`, `--first`: return only first result." --------------------


def test_short_first_flag_returns_only_the_first_result():
    assert out(run("-f", "//Item/text()", stdin=DOC)) == "first"


def test_long_first_flag_returns_only_the_first_result():
    assert out(run("--first", "//Item/text()", stdin=DOC)) == "first"


def test_without_first_all_results_are_returned():
    assert out(run("//Item/text()", stdin=DOC)) == "first\nsecond"


def test_first_result_is_document_order_first():
    doc = b"<r><a>one</a><a>two</a><a>three</a></r>"
    assert out(run("-f", "//a/text()", stdin=doc)) == "one"


def test_first_has_no_trailing_newline():
    assert not out(run("-f", "//Item/text()", stdin=DOC)).endswith("\n")


def test_first_exits_zero():
    assert run("-f", "//Item/text()", stdin=DOC).returncode == 0


def test_first_leaves_a_single_result_unchanged():
    assert out(run("-f", "//Item[@id='b']/text()", stdin=DOC)) == "second"


# --- CLI: "`-c`, `--compact`: compact output mode." -----------------------


def test_short_compact_flag_is_accepted():
    assert run("-c", "//Item", stdin=DOC).returncode == 0


def test_long_compact_flag_is_accepted():
    assert run("--compact", "//Item", stdin=DOC).returncode == 0


def test_compact_flags_agree():
    doc = b"<root><parent><child>hi</child></parent></root>"
    assert out(run("-c", "//parent", stdin=doc)) == out(
        run("--compact", "//parent", stdin=doc)
    )


def test_first_and_compact_combine():
    doc = b"<r><a><b>1</b></a><a><b>2</b></a></r>"
    assert out(run("-f", "-c", "//a", stdin=doc)) == "<a><b>1</b></a>"


def test_combined_short_flags_are_accepted():
    doc = b"<r><a><b>1</b></a></r>"
    assert out(run("-fc", "//a", stdin=doc)) == "<a><b>1</b></a>"


# --- Input Source: "`INFILE` takes precedence over stdin when both are ----
# --- present." ------------------------------------------------------------


def test_file_wins_over_stdin(tmp_path):
    path = write(tmp_path, FILE_DOC)
    assert out(run("//Item[1]/text()", path, stdin=DOC)) == "from file"


def test_stdin_is_used_when_no_file_is_given():
    assert out(run("//Item[1]/text()", stdin=DOC)) == "first"


def test_file_is_used_when_stdin_is_empty(tmp_path):
    path = write(tmp_path, FILE_DOC)
    assert out(run("//Item/@id", path, stdin=b"")) == "f\ng"


def test_file_is_used_when_stdin_is_malformed(tmp_path):
    # The unread stdin document cannot make a valid file input fail.
    path = write(tmp_path, FILE_DOC)
    result = run("//Item[2]/text()", path, stdin=b"<broken>")
    assert result.returncode == 0
    assert out(result) == "also file"


def test_json_file_wins_over_xml_stdin(tmp_path):
    path = write(tmp_path, '{"name": "widget"}', name="doc.json")
    assert out(run("/root/name/text()", path, stdin=DOC)) == "widget"


# --- Input Source: "Additional positional args after `QUERY [INFILE]` are -
# --- ignored." ------------------------------------------------------------


def test_extra_positional_arg_is_ignored(tmp_path):
    path = write(tmp_path, FILE_DOC)
    result = run("//Item[1]/text()", path, "extra", stdin=DOC)
    assert result.returncode == 0
    assert out(result) == "from file"


def test_several_extra_positional_args_are_ignored(tmp_path):
    path = write(tmp_path, FILE_DOC)
    result = run("//Item[1]/text()", path, "one", "two", "three", stdin=DOC)
    assert result.returncode == 0
    assert out(result) == "from file"


def test_extra_args_are_not_opened_as_files(tmp_path):
    # An ignored argument is never read, so a bad path among them is harmless.
    path = write(tmp_path, FILE_DOC)
    result = run("//Item[1]/text()", path, "/no/such/file.xml", stdin=DOC)
    assert result.returncode == 0
    assert out(result) == "from file"


def test_extra_args_do_not_replace_the_infile(tmp_path):
    path = write(tmp_path, FILE_DOC)
    other = write(tmp_path, "<Root><Item>second file</Item></Root>", name="other.xml")
    assert out(run("//Item[1]/text()", path, other, stdin=DOC)) == "from file"


def test_unknown_option_is_still_an_error(tmp_path):
    # Only positionals are ignored -- see AMBIGUITIES T33.
    path = write(tmp_path, FILE_DOC)
    assert run("//Item", path, "--nope", stdin=DOC).returncode != 0


# --- Input Source: "Decode `INFILE` as UTF-8 text; a UTF-8 BOM is ---------
# --- allowed." ------------------------------------------------------------


def test_utf8_file_content_is_decoded(tmp_path):
    path = write(tmp_path, "<Root><Item>café ☕</Item></Root>")
    assert out(run("//Item/text()", path)) == "café ☕"


def test_bom_prefixed_xml_file_is_accepted(tmp_path):
    path = write(tmp_path, "﻿<Root><Item>bom</Item></Root>")
    result = run("//Item/text()", path)
    assert result.returncode == 0
    assert out(result) == "bom"


def test_bom_prefixed_json_file_is_still_detected_as_json(tmp_path):
    path = write(tmp_path, '﻿{"name": "widget"}', name="doc.json")
    result = run("/root/name/text()", path)
    assert result.returncode == 0
    assert out(result) == "widget"


def test_bom_is_not_part_of_the_document(tmp_path):
    path = write(tmp_path, "﻿<Root><Item>bom</Item></Root>")
    assert "﻿" not in out(run("//Item/text()", path))


def test_stdin_is_not_governed_by_the_file_decoding_rule():
    # Stdin still reaches the parser as bytes, so a document that declares
    # another encoding keeps working -- see AMBIGUITIES T34.
    doc = "<?xml version='1.0' encoding='utf-16'?><r><a>caf\xe9</a></r>".encode("utf-16")
    assert out(run("//a/text()", stdin=doc)) == "caf\xe9"


def test_non_utf8_file_is_rejected(tmp_path):
    # Latin-1 bytes are not UTF-8 text -- see AMBIGUITIES T31.
    path = write(tmp_path, b"<Root><Item>caf\xe9</Item></Root>")
    result = run("//Item/text()", path)
    assert result.returncode == 1
    assert err(result).strip() != ""


# --- Input Source: "Apply JSON auto-detection to file input: treat as -----
# --- JSON object/array when detected, otherwise parse as XML/HTML." -------


def test_json_object_file_is_converted(tmp_path):
    path = write(tmp_path, '{"name": "widget", "count": 2}', name="doc.json")
    assert out(run("/root/count/text()", path)) == "2"


def test_json_array_file_is_converted(tmp_path):
    path = write(tmp_path, "[10, 20]", name="doc.json")
    assert out(run("/root/item/text()", path)) == "10\n20"


def test_json_file_elements_carry_types(tmp_path):
    path = write(tmp_path, '{"v": 1.5}', name="doc.json")
    assert out(run("/root/v/@type", path)) == "float"


def test_xml_file_is_parsed_as_xml(tmp_path):
    path = write(tmp_path, FILE_DOC)
    assert out(run("//Item/@id", path)) == "f\ng"


def test_html_shaped_file_is_parsed_as_markup(tmp_path):
    path = write(tmp_path, "<html><body><p>hi</p></body></html>", name="doc.html")
    assert out(run("//p/text()", path)) == "hi"


def test_json_primitive_file_falls_back_to_xml(tmp_path):
    path = write(tmp_path, "123", name="doc.json")
    result = run("/root", path)
    assert result.returncode == 1
    assert any(term in err(result).lower() for term in ("xml", "parse"))


def test_malformed_json_file_falls_back_to_xml(tmp_path):
    path = write(tmp_path, '{"name": }', name="doc.json")
    assert run("/root", path).returncode == 1


def test_invalid_json_key_in_a_file_is_rejected(tmp_path):
    path = write(tmp_path, '{"my key": 1}', name="doc.json")
    result = run("/root", path)
    assert result.returncode == 1
    assert "key" in err(result).lower()


def test_empty_file_is_an_error(tmp_path):
    path = write(tmp_path, "")
    result = run("//a", path)
    assert result.returncode == 1
    assert any(term in err(result).lower() for term in ("xml", "parse"))


# --- Input Source: "Missing/unreadable file: stderr message, exit code ----
# --- `1`." ----------------------------------------------------------------


def test_missing_file_exits_one():
    assert run("//Item", "/no/such/file.xml", stdin=DOC).returncode == 1


def test_missing_file_writes_to_stderr():
    assert err(run("//Item", "/no/such/file.xml", stdin=DOC)).strip() != ""


def test_missing_file_writes_nothing_to_stdout():
    assert out(run("//Item", "/no/such/file.xml", stdin=DOC)) == ""


def test_missing_file_message_names_the_file(tmp_path):
    message = err(run("//Item", str(tmp_path / "gone.xml"), stdin=DOC)).lower()
    assert "file" in message


def test_directory_as_infile_is_unreadable(tmp_path):
    result = run("//Item", str(tmp_path), stdin=DOC)
    assert result.returncode == 1
    assert err(result).strip() != ""


def test_unreadable_file_exits_one(tmp_path):
    path = Path(write(tmp_path, FILE_DOC))
    path.chmod(0o000)
    try:
        result = run("//Item", str(path), stdin=DOC)
    finally:
        path.chmod(0o644)
    assert result.returncode == 1
    assert err(result).strip() != ""


def test_dash_is_treated_as_a_path_not_as_stdin():
    # No special "-" spelling for stdin -- see AMBIGUITIES T35.
    result = run("//Item/text()", "-", stdin=DOC)
    assert result.returncode == 1
    assert out(result) == ""


def test_missing_file_is_not_a_fallback_to_stdin():
    # A bad path is an error, not a reason to read the piped document.
    assert out(run("//Item/text()", "/no/such/file.xml", stdin=DOC)) == ""


# --- Output: "`--first` applies across text, attribute, and XML-node ------
# --- results." ------------------------------------------------------------


def test_first_applies_to_text_results():
    assert out(run("--first", "//Item/text()", stdin=DOC)) == "first"


def test_first_applies_to_attribute_results():
    assert out(run("--first", "//Item/@id", stdin=DOC)) == "a"


def test_first_applies_to_xml_node_results():
    assert out(run("--first", "//Item", stdin=DOC)) == '<Item id="a">first</Item>'


def test_first_xml_node_result_matches_the_default(tmp_path):
    # XML node output is already limited to the first match -- see AMBIGUITIES T28.
    assert out(run("--first", "//Item", stdin=DOC)) == out(run("//Item", stdin=DOC))


def test_first_applies_to_css_results():
    assert out(run("--css", "-f", "-t", "Item", stdin=DOC)) == "first"


def test_first_applies_to_text_node_extraction():
    # `-f` keeps the first extracted text node -- see AMBIGUITIES T29.
    doc = b"<Root><div>Hello <b>World</b>!</div></Root>"
    assert out(run("--css", "-f", "div ::text", stdin=doc)) == "Hello"


def test_first_applies_to_a_union_result():
    assert out(run("-f", "//Item/@id | //Item/text()", stdin=DOC)) == "a"


def test_first_applies_to_json_derived_results(tmp_path):
    path = write(tmp_path, "[10, 20]", name="doc.json")
    assert out(run("-f", "/root/item/text()", path)) == "10"


def test_first_leaves_scalar_results_unchanged():
    # A scalar is a single result already -- see AMBIGUITIES T30.
    assert out(run("-f", "count(//Item)", stdin=DOC)) == "2"


def test_first_applies_to_file_input(tmp_path):
    path = write(tmp_path, FILE_DOC)
    assert out(run("-f", "//Item/text()", path, stdin=DOC)) == "from file"


# --- Output: "`--first` with no matches remains silent (no output)." ------


def test_first_with_no_matches_writes_nothing_to_stdout():
    assert out(run("-f", "//Missing", stdin=DOC)) == ""


def test_first_with_no_matches_writes_nothing_to_stderr():
    assert err(run("-f", "//Missing", stdin=DOC)) == ""


def test_first_with_no_matches_exits_zero():
    assert run("-f", "//Missing", stdin=DOC).returncode == 0


def test_first_with_no_matching_attribute_is_silent():
    result = run("-f", "//Item/@missing", stdin=DOC)
    assert (out(result), err(result), result.returncode) == ("", "", 0)


def test_first_with_no_matching_text_is_silent():
    result = run("--css", "-f", "-t", "Missing", stdin=DOC)
    assert (out(result), err(result), result.returncode) == ("", "", 0)


# --- Output: "`--compact` affects XML serialization only: compact XML -----
# --- output has no added pretty-print formatting." ------------------------


def test_compact_xml_has_no_indentation():
    doc = b"<root><parent><child a='1'>hi</child></parent></root>"
    assert out(run("-c", "//parent", stdin=doc)) == '<parent><child a="1">hi</child></parent>'


def test_pretty_print_is_the_default():
    doc = b"<root><parent><child a='1'>hi</child></parent></root>"
    assert out(run("//parent", stdin=doc)) == '<parent>\n  <child a="1">hi</child>\n</parent>'


def test_compact_xml_has_no_newlines():
    doc = b"<r><a><b/><c><d/></c></a></r>"
    assert "\n" not in out(run("-c", "//a", stdin=doc))


def test_compact_drops_source_indentation():
    doc = b"<root><parent>\n    <child/>\n</parent></root>"
    assert out(run("-c", "//parent", stdin=doc)) == "<parent><child/></parent>"


def test_compact_keeps_element_text():
    assert out(run("-c", "//Item[1]", stdin=DOC)) == '<Item id="a">first</Item>'


def test_compact_excludes_tail_text():
    assert out(run("-c", "//a", stdin=b"<r><a>keep</a>tail</r>")) == "<a>keep</a>"


def test_compact_does_not_change_text_results():
    assert out(run("-c", "//Item/text()", stdin=DOC)) == "first\nsecond"


def test_compact_does_not_change_attribute_results():
    assert out(run("-c", "//Item/@id", stdin=DOC)) == "a\nb"


def test_compact_does_not_change_scalar_results():
    assert out(run("-c", "count(//Item)", stdin=DOC)) == "2"


def test_compact_with_no_matches_is_silent():
    result = run("-c", "//Missing", stdin=DOC)
    assert (out(result), err(result), result.returncode) == ("", "", 0)


def test_compact_output_has_no_trailing_newline():
    assert not out(run("-c", "//Item[1]", stdin=DOC)).endswith("\n")


# --- Output: "For JSON-derived input, `--compact` still applies to --------
# --- resulting XML output." -----------------------------------------------


def test_compact_json_object_serialization(tmp_path):
    path = write(tmp_path, '{"b": 1, "a": 2}', name="doc.json")
    expected = '<root><b type="int">1</b><a type="int">2</a></root>'
    assert out(run("-c", "/root", path)) == expected


def test_compact_json_array_serialization():
    expected = '<root><item type="int">10</item><item type="int">20</item></root>'
    assert out(run("-c", "/root", stdin=b"[10, 20]")) == expected


def test_compact_nested_json_serialization(tmp_path):
    path = write(tmp_path, '{"o": {"z": [1]}}', name="doc.json")
    expected = '<o type="dict"><z type="list"><item type="int">1</item></z></o>'
    assert out(run("-c", "/root/o", path)) == expected


def test_compact_json_null_is_not_self_closing():
    # The no-self-closing contract survives compact output -- see AMBIGUITIES T32.
    assert out(run("-c", "/root/v", stdin=b'{"v": null}')) == '<v type="null"></v>'


def test_compact_json_empty_object_is_not_self_closing():
    assert out(run("-c", "/root/v", stdin=b'{"v": {}}')) == '<v type="dict"></v>'


def test_pretty_json_output_is_the_default(tmp_path):
    path = write(tmp_path, '{"b": 1}', name="doc.json")
    assert out(run("/root", path)) == '<root>\n  <b type="int">1</b>\n</root>'
