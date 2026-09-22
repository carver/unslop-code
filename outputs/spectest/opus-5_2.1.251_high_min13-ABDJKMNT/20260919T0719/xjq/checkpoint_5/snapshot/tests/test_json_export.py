"""Spec section: CLI Addition / JSON Export Contract.

`-j`/`--json` turns a node set of XML elements into a JSON array of
`{tag_name: immediate_text_content}` objects.
"""

import json

from conftest import DOC, EXPORT_DOC


# Phrase: "`-j`, `--json`: JSON export mode for XML element results."
def test_json_flag_exports_matched_elements(xjq):
    result = xjq("--json", "//title", stdin=DOC)
    assert result.returncode == 0
    assert json.loads(result.stdout) == [{"title": "Dune"}, {"title": "Le Petit Prince"}]


# Phrase: "`-j`, `--json`" -- the short spelling is the same option.
def test_short_json_flag_matches_long_spelling(xjq):
    short = xjq("-j", "//title", stdin=DOC)
    long = xjq("--json", "//title", stdin=DOC)
    assert short.stdout == long.stdout
    assert short.returncode == 0


# Phrase: "Export shape: JSON array of objects `{tag_name: immediate_text_content}`."
def test_export_shape_is_one_single_key_object_per_element(xjq):
    payload = json.loads(xjq("-j", "//item", stdin=EXPORT_DOC).stdout)
    assert isinstance(payload, list)
    assert [list(entry) for entry in payload] == [["item"], ["item"], ["item"]]


# Phrase: "Export shape: JSON array of objects `{tag_name: ...}`."
# The key is the element's own tag name, not its path or its parent's.
def test_export_key_is_the_element_tag_name(xjq):
    payload = json.loads(xjq("-j", "//book/*", stdin=DOC).stdout)
    assert [key for entry in payload for key in entry] == [
        "title",
        "author",
        "title",
        "author",
    ]


# Phrase: "Use immediate text only (exclude descendant text from child elements)."
def test_export_excludes_descendant_text(xjq):
    payload = json.loads(xjq("-j", "//item", stdin=EXPORT_DOC).stdout)
    assert payload[0]["item"] == "Alpha"
    assert payload[1]["item"] == "Beta tail"
    assert payload[2]["item"] == ""


# Phrase: "Use immediate text only ..." -- an element that only wraps children
# exports as empty rather than as its descendants' text (T36).
def test_export_of_a_container_element_has_no_text(xjq):
    payload = json.loads(xjq("-j", "/catalog", stdin=EXPORT_DOC).stdout)
    assert payload == [{"catalog": ""}]


# Phrase: "Default JSON formatting: 2-space indent."
def test_default_json_formatting_uses_two_space_indent(xjq):
    assert xjq("-j", "//title", stdin=DOC).stdout == (
        "[\n"
        '  {\n'
        '    "title": "Dune"\n'
        "  },\n"
        "  {\n"
        '    "title": "Le Petit Prince"\n'
        "  }\n"
        "]\n"
    )


# Phrase: "With `--compact`, produce zero-indent JSON layout (no leading whitespace)."
def test_compact_json_layout_has_no_leading_whitespace(xjq):
    output = xjq("-j", "--compact", "//title", stdin=DOC).stdout
    assert json.loads(output) == [{"title": "Dune"}, {"title": "Le Petit Prince"}]
    assert all(line == line.lstrip() for line in output.splitlines())


# Phrase: "With `--compact`, produce zero-indent JSON layout" (T37).
def test_compact_json_layout_is_exactly_zero_indent(xjq):
    assert xjq("-j", "-c", "//title", stdin=DOC).stdout == (
        "[\n"
        "{\n"
        '"title": "Dune"\n'
        "},\n"
        "{\n"
        '"title": "Le Petit Prince"\n'
        "}\n"
        "]\n"
    )


# Phrase: "With `--first`, still return a JSON array containing one exported element."
def test_first_keeps_the_array_wrapper(xjq):
    result = xjq("-j", "--first", "//title", stdin=DOC)
    assert result.returncode == 0
    assert json.loads(result.stdout) == [{"title": "Dune"}]


# Phrase: "With `--first`, still return a JSON array containing one exported
# element." -- `--compact` does not unwrap it either.
def test_first_and_compact_still_export_an_array(xjq):
    payload = json.loads(xjq("-j", "-f", "-c", "//item", stdin=EXPORT_DOC).stdout)
    assert payload == [{"item": "Alpha"}]


# Phrase: "JSON export mode for XML element results."
# No matched element means no export and a clean exit (T39).
def test_json_export_of_no_matches_prints_nothing(xjq):
    result = xjq("-j", "//missing", stdin=DOC)
    assert result.stdout == ""
    assert result.returncode == 0
