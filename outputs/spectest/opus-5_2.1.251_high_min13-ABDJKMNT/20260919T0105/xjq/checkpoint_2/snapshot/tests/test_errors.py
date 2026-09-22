"""Failure modes.

Spec section: "## Errors"
"""


# Spec: "Invalid XPath: stderr message, exit code `1`"
# Context: a syntactically broken expression fails before producing output.
def test_invalid_xpath_syntax_exits_one(run_xjq):
    result = run_xjq("//[", stdin="<r><a>x</a></r>")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr != ""


# Spec: "message should reference `xpath`"
# Context: the diagnostic names the thing that was wrong.
def test_invalid_xpath_message_references_xpath(run_xjq):
    result = run_xjq("//[", stdin="<r><a>x</a></r>")
    assert "xpath" in result.stderr.lower()


# Spec: "Invalid XPath: stderr message, exit code `1`"
# Context: an unbalanced predicate is rejected.
def test_unbalanced_predicate_is_invalid(run_xjq):
    result = run_xjq("//a[@id='1'", stdin="<r><a id='1'/></r>")
    assert result.returncode == 1
    assert "xpath" in result.stderr.lower()


# Spec: "Invalid XPath: stderr message, exit code `1`"
# Context: an unknown function is an evaluation-time XPath error.
def test_unknown_function_is_invalid(run_xjq):
    result = run_xjq("nosuchfunction(//a)", stdin="<r><a>x</a></r>")
    assert result.returncode == 1
    assert "xpath" in result.stderr.lower()


# Spec: "Invalid XPath: stderr message, exit code `1`"
# Context: an undeclared namespace prefix cannot be resolved.
def test_unknown_namespace_prefix_is_invalid(run_xjq):
    result = run_xjq("//ns:a", stdin="<r><a>x</a></r>")
    assert result.returncode == 1
    assert "xpath" in result.stderr.lower()


# Spec: "Invalid XPath: ... exit code `1`"
# Context: an empty expression is not a valid XPath.
def test_empty_query_is_invalid(run_xjq):
    result = run_xjq("", stdin="<r><a>x</a></r>")
    assert result.returncode == 1
    assert "xpath" in result.stderr.lower()


# Spec: "Malformed/empty XML input: stderr message, exit code `1`"
# Context: mismatched tags are rejected rather than recovered.
# See AMBIGUITIES.md T2.
def test_mismatched_tags_exit_one(run_xjq):
    result = run_xjq("//a", stdin="<r><a>x</r>")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr != ""


# Spec: "message should reference `xml`/`parse`"
# Context: the diagnostic names the input format and the failed operation.
def test_malformed_xml_message_references_xml_and_parse(run_xjq):
    stderr = run_xjq("//a", stdin="<r><a>x</r>").stderr.lower()
    assert "xml" in stderr
    assert "parse" in stderr


# Spec: "Malformed/empty XML input: stderr message, exit code `1`"
# Context: an unclosed root element is malformed.
def test_unclosed_root_exits_one(run_xjq):
    result = run_xjq("//a", stdin="<r><a>x</a>")
    assert result.returncode == 1
    assert "xml" in result.stderr.lower()


# Spec: "Malformed/empty XML input: stderr message, exit code `1`"
# Context: input that is not markup at all is malformed.
def test_non_markup_input_exits_one(run_xjq):
    result = run_xjq("//a", stdin="this is not xml")
    assert result.returncode == 1
    assert "xml" in result.stderr.lower()


# Spec: "Malformed/empty XML input: stderr message, exit code `1`"
# Context: a zero-byte stream has no document to query.
def test_empty_input_exits_one(run_xjq):
    result = run_xjq("//a", stdin="")
    assert result.returncode == 1
    assert result.stdout == ""
    assert "xml" in result.stderr.lower()


# Spec: "Malformed/empty XML input: stderr message, exit code `1`"
# Context: whitespace-only input is treated as empty.
# See AMBIGUITIES.md T9.
def test_whitespace_only_input_exits_one(run_xjq):
    result = run_xjq("//a", stdin="   \n\t  ")
    assert result.returncode == 1
    assert "xml" in result.stderr.lower()


# Spec: "Malformed/empty XML input ..." + "Invalid XPath ..."
# Context: when both are broken the input is parsed first, so the XML error is
# the one reported. See AMBIGUITIES.md T8.
def test_bad_input_takes_precedence_over_bad_query(run_xjq):
    result = run_xjq("//[", stdin="<r><a>x</r>")
    assert result.returncode == 1
    assert "xml" in result.stderr.lower()


# Spec: "Invalid XPath: stderr message" / "Malformed ... stderr message"
# Context: errors never pollute stdout, so the CLI stays pipe-safe.
def test_errors_keep_stdout_clean(run_xjq):
    assert run_xjq("//[", stdin="<r/>").stdout == ""
    assert run_xjq("//a", stdin="<r>").stdout == ""
