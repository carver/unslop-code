"""CLI surface of the `signatures`, `references`, `search` and `names` commands."""

from conftest import run_cli


# "python sith.py signatures <file> <line> <col> [--project <dir>]"
def test_signatures_payload_is_one_array(signatures):
    payload = signatures("def f(a):\n    pass\n\nf(|)\n").payload
    assert list(payload) == ["signatures"]


def test_signature_object_field_set(signatures):
    signature = signatures("def f(a):\n    pass\n\nf(|)\n").signature
    assert set(signature) == {"name", "params", "index", "description", "docstring"}


# "python sith.py references <file> <line> <col> [--scope file|project]"
def test_references_payload_is_one_array(references):
    payload = references("va|lue = 1\n").payload
    assert list(payload) == ["references"]


def test_reference_object_field_set(references):
    reference = references("va|lue = 1\n").references[0]
    assert set(reference) == {"module_path", "line", "column", "is_definition"}


# "python sith.py search <query> [--project <dir>]"
def test_search_payload_is_one_array(search):
    payload = search("f", {"tools.py": "def f():\n    pass\n"}, project=".").payload
    assert list(payload) == ["definitions"]


# "python sith.py names <file> [--all-scopes] [--project <dir>]"
def test_names_payload_is_one_array(names):
    payload = names("value = 1\n").payload
    assert list(payload) == ["definitions"]


# "On error, print a message to STDERR and exit 1."
def test_signatures_on_a_missing_file_fails(workdir):
    result = run_cli("signatures", str(workdir / "missing.py"), 1, 0)
    assert result.returncode == 1
    assert result.stdout == ""


def test_references_out_of_range_position_fails(references):
    result = references("value = 1\n", line=9, col=0, expect_ok=False)
    assert result.returncode == 1


def test_names_on_a_missing_file_fails(workdir):
    result = run_cli("names", str(workdir / "missing.py"))
    assert result.returncode == 1


def test_unknown_scope_is_rejected(references):
    result = references("va|lue = 1\n", scope="everywhere", expect_ok=False)
    assert result.returncode == 1


def test_search_requires_a_query():
    assert run_cli("search").returncode == 1


# "[--project <dir>]" places the root the paths are reported from.
def test_project_option_sets_the_reported_paths(names):
    result = names("value = 1\n", name="pkg/mod.py", files={"pkg/__init__.py": ""}, project=".")
    assert result.definitions[0]["module_path"] == "pkg/mod.py"
