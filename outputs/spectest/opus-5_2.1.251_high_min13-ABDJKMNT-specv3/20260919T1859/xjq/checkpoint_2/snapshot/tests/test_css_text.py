"""The custom ``::text`` pseudo-element in CSS query mode."""

import pytest

from conftest import MIXED, PAGE


# Spec: "Define custom `::text` pseudo-element: `selector::text` returns direct
# text"
def test_direct_text_pseudo_element(run_xjq):
    result = run_xjq("--css", "p::text", stdin=MIXED)
    assert result.returncode == 0
    assert result.stdout == "Hello\n!"


# Spec: "`selector::text` returns direct text" -- text held by descendants is
# not part of an element's direct text.
def test_direct_text_excludes_descendants(run_xjq):
    assert "World" not in run_xjq("--css", "p::text", stdin=MIXED).stdout


# Spec: "`selector::text` returns direct text" -- one element per match, in
# document order.
def test_direct_text_over_several_matches(run_xjq):
    result = run_xjq("--css", "p.body::text", stdin=PAGE)
    assert result.stdout == "Hello\n!\nSecond line\nSpaced out text"


# Spec: "`selector ::text` returns all descendant text nodes (one text node per
# line)."
def test_descendant_text_pseudo_element(run_xjq):
    result = run_xjq("--css", "p ::text", stdin=MIXED)
    assert result.stdout == "Hello\nWorld\n!"


# Spec: "`selector ::text` returns all descendant text nodes (one text node per
# line)." -- across a whole subtree, in document order.
def test_descendant_text_of_a_subtree(run_xjq):
    result = run_xjq("--css", "#p1 ::text", stdin=PAGE)
    assert result.stdout == "First\nPost\nHello\nWorld\n!\nSecond line"


# Spec: "`selector::text` returns direct text; `selector ::text` returns all
# descendant text nodes" -- the space before `::text` is what distinguishes the
# two modes.
def test_space_before_pseudo_element_selects_descendant_mode(run_xjq):
    assert run_xjq("--css", "doc::text", stdin=MIXED).stdout == ""
    assert run_xjq("--css", "doc ::text", stdin=MIXED).stdout == "Hello\nWorld\n!"


# Spec: "Comma-separated selectors are supported for `::text` queries when all
# selectors use the same `::text` mode." -- direct mode on both sides.
def test_comma_separated_direct_text(run_xjq):
    result = run_xjq("--css", "h1::text, p.body::text", stdin=PAGE)
    assert result.stdout == (
        "First\nHello\n!\nSecond line\nSecond\nSpaced out text"
    )


# Spec: "Comma-separated selectors are supported for `::text` queries when all
# selectors use the same `::text` mode." -- descendant mode on both sides.
def test_comma_separated_descendant_text(run_xjq):
    result = run_xjq("--css", "h1 ::text, b ::text", stdin=PAGE)
    assert result.stdout == "First\nPost\nWorld\nSecond"


# Spec: "Mixing direct and descendant `::text` modes in one comma-separated CSS
# query is invalid (stderr message, exit code `1`)."
@pytest.mark.parametrize(
    "selector", ["h1::text, p ::text", "h1 ::text, p::text", "a ::text, b::text, c ::text"]
)
def test_mixed_text_modes_are_invalid(run_xjq, selector):
    result = run_xjq("--css", selector, stdin=PAGE)
    assert result.returncode == 1
    assert result.stderr != ""
    assert result.stdout == ""


# Spec: "Comma-separated selectors are supported for `::text` queries when all
# selectors use the same `::text` mode." -- a text selector combined with a
# plain node selector is not one mode either (AMBIGUITIES T13).
def test_text_mode_mixed_with_node_selector_is_invalid(run_xjq):
    result = run_xjq("--css", "h1::text, p", stdin=PAGE)
    assert result.returncode == 1
    assert result.stdout == ""


# Spec: "Strip each result and collapse internal whitespace runs to single
# spaces." -- applied to `::text` results as well.
def test_text_pseudo_element_results_are_normalized(run_xjq):
    result = run_xjq("--css", "p.body::text", stdin=PAGE)
    assert "Spaced out text" in result.stdout
    assert not result.stdout.endswith("\n")


# Spec: "`selector ::text` returns all descendant text nodes" -- a selector
# matching no element produces no output and a successful exit.
def test_text_pseudo_element_without_matches(run_xjq):
    result = run_xjq("--css", ".missing ::text", stdin=PAGE)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
