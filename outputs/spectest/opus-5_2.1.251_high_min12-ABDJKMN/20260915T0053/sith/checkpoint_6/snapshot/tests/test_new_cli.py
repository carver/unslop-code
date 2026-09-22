"""Spec section: CLI framing for the four new subcommands."""
import json

from conftest import run_raw, write_source


# --- Phrase: "python sith.py signatures <file> <line> <col>" — missing
#     arguments are a usage error.
def test_signatures_requires_three_arguments(tmp_path):
    p = write_source(tmp_path, "x = 1\n")
    proc = run_raw("signatures", str(p), 1, cwd=str(tmp_path))
    assert proc.returncode == 1
    assert proc.stdout == ""
    assert proc.stderr


# --- Phrase: "python sith.py references <file> <line> <col>" — missing
#     arguments are a usage error.
def test_references_requires_three_arguments(tmp_path):
    p = write_source(tmp_path, "x = 1\n")
    proc = run_raw("references", str(p), cwd=str(tmp_path))
    assert proc.returncode == 1


# --- Phrase: "python sith.py search <query>" — exactly one argument.
def test_search_requires_a_query(tmp_path):
    proc = run_raw("search", cwd=str(tmp_path))
    assert proc.returncode == 1


# --- Phrase: "python sith.py names <file>" — exactly one argument.
def test_names_requires_a_file(tmp_path):
    proc = run_raw("names", cwd=str(tmp_path))
    assert proc.returncode == 1


# --- Phrase: the new commands still reject unknown options.
def test_unknown_option(tmp_path):
    p = write_source(tmp_path, "x = 1\n")
    proc = run_raw("signatures", str(p), 1, 0, "--nope", cwd=str(tmp_path))
    assert proc.returncode == 1


# --- Phrase: output is a single compact, newline-terminated JSON object.
def test_output_framing(tmp_path):
    p = write_source(tmp_path, "def f(a):\n    return a\n\n\nf()\n")
    proc = run_raw("signatures", str(p), 5, 2, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.endswith("\n")
    assert proc.stdout.count("\n") == 1
    assert ", " not in proc.stdout
    json.loads(proc.stdout)


# --- Phrase: `signatures` reports file and position errors like the other
#     cursor commands.
def test_signatures_missing_file(tmp_path):
    proc = run_raw("signatures", str(tmp_path / "gone.py"), 1, 0,
                   cwd=str(tmp_path))
    assert proc.returncode == 1
    assert proc.stdout == ""


# --- Phrase: `signatures` reports an out-of-range line as an error.
def test_signatures_line_out_of_range(tmp_path):
    p = write_source(tmp_path, "x = 1\n")
    proc = run_raw("signatures", str(p), 99, 0, cwd=str(tmp_path))
    assert proc.returncode == 1


# --- Phrase: `search` over a project with no files is an empty array.
def test_search_empty_project(tmp_path):
    proc = run_raw("search", "anything", "--project", str(tmp_path),
                   cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"results": []}
