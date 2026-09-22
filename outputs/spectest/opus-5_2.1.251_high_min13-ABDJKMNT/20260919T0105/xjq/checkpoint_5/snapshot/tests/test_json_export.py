"""`-j`/`--json` export mode.

Spec sections: "## CLI Addition", "## Output Precedence", and
"## JSON Export Contract".
"""

import json
import textwrap

PAIR = "<r><a>one</a><a>two</a></r>"
MIXED = "<r><div>Hello <b>World</b>!</div></r>"


# Spec: "`-j`, `--json`: JSON export mode for XML element results."
# Context: the short flag turns matched elements into a JSON document.
def test_short_json_flag_exports_elements(run_xjq):
    result = run_xjq("-j", "//a", stdin=PAIR)
    assert result.returncode == 0
    assert json.loads(result.stdout) == [{"a": "one"}, {"a": "two"}]


# Spec: "`-j`, `--json`: JSON export mode for XML element results."
# Context: the long spelling behaves identically.
def test_long_json_flag_exports_elements(run_xjq):
    assert run_xjq("--json", "//a", stdin=PAIR).stdout == run_xjq(
        "-j", "//a", stdin=PAIR
    ).stdout


# Spec: "Export shape: JSON array of objects `{tag_name: immediate_text_content}`."
# Context: one object per matched element, keyed by that element's tag name.
def test_export_is_an_array_of_one_key_objects(run_xjq):
    doc = "<r><title>Dune</title><author>Herbert</author></r>"
    exported = json.loads(run_xjq("-j", "//title|//author", stdin=doc).stdout)
    assert exported == [{"title": "Dune"}, {"author": "Herbert"}]


# Spec: "Export shape: JSON array of objects ..."
# Context: every match is exported, not just the first one XML output prints.
# See AMBIGUITIES.md T45.
def test_export_covers_every_match(run_xjq):
    doc = "<r><a>1</a><a>2</a><a>3</a></r>"
    assert len(json.loads(run_xjq("-j", "//a", stdin=doc).stdout)) == 3


# Spec: "Use immediate text only (exclude descendant text from child elements)."
# Context: the text of a child element stays out, while the matched element's
# own text on either side of that child stays in. See AMBIGUITIES.md T37.
def test_export_uses_immediate_text_only(run_xjq):
    exported = json.loads(run_xjq("-j", "//div", stdin=MIXED).stdout)
    assert exported == [{"div": "Hello !"}]


# Spec: "Use immediate text only ..."
# Context: an element holding nothing but children exports an empty string.
def test_element_without_own_text_exports_empty_string(run_xjq):
    doc = "<r><a><b>x</b></a></r>"
    assert json.loads(run_xjq("-j", "//a", stdin=doc).stdout) == [{"a": ""}]


# Spec: "Use immediate text only ..." with the base spec's "Strip each result
#        and collapse internal whitespace runs to single spaces."
# Context: exported text is normalized like any other text result, so an
# indented document does not export its layout. See AMBIGUITIES.md T38.
def test_exported_text_is_normalized(run_xjq):
    doc = "<r><a>  padded\n\ttext  </a>\n  <b>\n  </b></r>"
    exported = json.loads(run_xjq("-j", "//a|//b", stdin=doc).stdout)
    assert exported == [{"a": "padded text"}, {"b": ""}]


# Spec: "Default JSON formatting: 2-space indent."
# Context: the exact layout of an export without `--compact`.
def test_default_export_uses_two_space_indent(run_xjq):
    expected = textwrap.dedent(
        """\
        [
          {
            "a": "one"
          },
          {
            "a": "two"
          }
        ]
        """
    )
    assert run_xjq("-j", "//a", stdin=PAIR).stdout == expected


# Spec: "With `--compact`, produce zero-indent JSON layout (no leading
#        whitespace)."
# Context: the same structure with every line flush left.
# See AMBIGUITIES.md T36.
def test_compact_export_has_no_leading_whitespace(run_xjq):
    expected = textwrap.dedent(
        """\
        [
        {
        "a": "one"
        },
        {
        "a": "two"
        }
        ]
        """
    )
    result = run_xjq("-j", "-c", "//a", stdin=PAIR)
    assert result.stdout == expected
    assert not any(line.startswith(" ") for line in result.lines)


# Spec: "With `--first`, still return a JSON array containing one exported
#        element."
# Context: the result stays an array rather than collapsing to a bare object.
def test_first_exports_a_one_element_array(run_xjq):
    exported = json.loads(run_xjq("-j", "--first", "//a", stdin=PAIR).stdout)
    assert exported == [{"a": "one"}]


# Spec: "With `--first`, still return a JSON array ..." and "With `--compact`
#        ... zero-indent JSON layout"
# Context: the two flags combine.
def test_first_and_compact_together(run_xjq):
    result = run_xjq("-j", "--first", "--compact", "//a", stdin=PAIR)
    assert result.stdout == '[\n{\n"a": "one"\n}\n]\n'


# Spec: "When multiple output flags are present: 1. `--text-all` 2. `--text`
#        3. `--json` 4. default auto-format behavior"
# Context: either text flag outranks `--json`.
def test_text_flags_outrank_json(run_xjq):
    assert run_xjq("-j", "-t", "//div", stdin=MIXED).lines == ["Hello", "!"]
    assert run_xjq("-j", "--text-all", "//div", stdin=MIXED).lines == [
        "Hello",
        "World",
        "!",
    ]


# Spec: "When multiple output flags are present: 1. `--text-all` 2. `--text` ..."
# Context: the existing `--text-all` over `--text` ordering is unchanged by the
# new flag joining the list.
def test_text_all_still_wins_over_text_with_json(run_xjq):
    result = run_xjq("-j", "-t", "--text-all", "//div", stdin=MIXED)
    assert result.lines == ["Hello", "World", "!"]


# Spec: "... 3. `--json` 4. default auto-format behavior"
# Context: without `--json` the same query keeps printing XML.
def test_default_output_without_the_flag(run_xjq):
    assert run_xjq("//a", stdin=PAIR).stdout.strip() == "<a>one</a>"


# Spec: "`--json` has no effect when results are already auto-detected as text
#        (e.g., text()/attribute outputs)."
# Context: a `text()` query prints its lines exactly as it would without `-j`.
def test_json_has_no_effect_on_text_results(run_xjq):
    with_flag = run_xjq("-j", "//a/text()", stdin=PAIR)
    assert with_flag.stdout == run_xjq("//a/text()", stdin=PAIR).stdout
    assert with_flag.lines == ["one", "two"]


# Spec: "`--json` has no effect when results are already auto-detected as text
#        (e.g., text()/attribute outputs)."
# Context: attribute results are the other named case.
def test_json_has_no_effect_on_attribute_results(run_xjq):
    doc = "<r><a id='1'/><a id='2'/></r>"
    assert run_xjq("-j", "//a/@id", stdin=doc).lines == ["1", "2"]


# Spec: "`--json` has no effect when results are already auto-detected as text"
# Context: a scalar result has no tag name to export either.
# See AMBIGUITIES.md T46.
def test_json_has_no_effect_on_scalar_results(run_xjq):
    assert run_xjq("-j", "count(//a)", stdin=PAIR).stdout == "2\n"


# Spec: "In `--css` mode, `--json` has no effect and output follows the normal
#        CSS rules for the query."
# Context: a CSS element match keeps its pretty-printed XML output.
def test_json_has_no_effect_in_css_mode(run_xjq):
    with_flag = run_xjq("--css", "-j", "a", stdin=PAIR)
    assert with_flag.stdout == run_xjq("--css", "a", stdin=PAIR).stdout
    assert with_flag.stdout.strip() == "<a>one</a>"


# Spec: "In `--css` mode, `--json` has no effect and output follows the normal
#        CSS rules for the query."
# Context: a `::text` selector is likewise untouched by the flag.
def test_json_leaves_css_text_queries_alone(run_xjq):
    assert run_xjq("--css", "-j", "a::text", stdin=PAIR).lines == ["one", "two"]


# Spec: "`-j`, `--json`: JSON export mode for XML element results." with the
#        base spec's "No matches: no output, exit code `0`."
# Context: an empty match set stays silent instead of exporting `[]`.
# See AMBIGUITIES.md T39.
def test_json_export_of_no_matches_is_silent(run_xjq):
    result = run_xjq("-j", "//missing", stdin=PAIR)
    assert result.returncode == 0
    assert result.stdout == ""


# Spec: "Export shape: JSON array of objects `{tag_name: immediate_text_content}`."
# Context: non-ASCII text is escaped the way Python's JSON writer does by
# default, and still decodes to the original string.
# See AMBIGUITIES.md T40.
def test_non_ascii_text_is_escaped(run_xjq):
    result = run_xjq("-j", "//a", stdin="<r><a>café</a></r>")
    assert "caf\\u00e9" in result.stdout
    assert json.loads(result.stdout) == [{"a": "café"}]


# Spec: "`-j`, `--json`: JSON export mode for XML element results."
# Context: a JSON input document is XML by the time the query runs, so its
# elements export like any others.
def test_json_input_exports_as_elements(run_xjq):
    result = run_xjq("-j", "//name", stdin='{"user": {"name": "ada"}}')
    assert json.loads(result.stdout) == [{"name": "ada"}]
