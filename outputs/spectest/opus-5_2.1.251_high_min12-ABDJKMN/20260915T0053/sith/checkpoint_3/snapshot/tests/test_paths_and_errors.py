"""Spec sections: Path Convention and Error Handling."""
from conftest import CURSOR, comps_in, defs_in, has, in_project, one

C = CURSOR


# --- Phrase: "All paths in output fields (`module_path`, ...) use forward-slash
#              separators (POSIX convention) regardless of the host operating system."
#     Context: a definition inside a nested package.
def test_module_path_uses_forward_slashes(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/sub/__init__.py": "",
        "pkg/sub/deep.py": "def inner():\n    pass\n",
        "main.py": "from pkg.sub.deep import inner\n" + C + "inner\n",
    }
    got = one(defs_in(tmp_path, files, "infer", project=tmp_path))
    assert got["module_path"] == "pkg/sub/deep.py"
    assert "\\" not in got["module_path"]


# --- Phrase: "All paths in output fields ... use forward-slash separators"
#     Context: `goto` output for the file under the cursor.
def test_goto_module_path_forward_slashes(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/app.py": "def local():\n    pass\n\n\n" + C + "local()\n",
    }
    got = one(defs_in(tmp_path, files, "goto", project=tmp_path))
    assert got["module_path"] == "pkg/app.py"


# --- Phrase: "Circular imports: do not infinite-loop."
#     Context: A imports B, B imports A; the tool still answers.
def test_circular_imports_terminate(tmp_path):
    files = {
        "a.py": "from b import beta\n\n\ndef alpha():\n    pass\n",
        "b.py": "from a import alpha\n\n\ndef beta():\n    pass\n",
        "main.py": "from a import alpha\n" + C + "alpha\n",
    }
    got = one(defs_in(tmp_path, files, "infer"))
    assert got["module_path"] == "a.py"


# --- Phrase: "If module A imports B and B imports A, resolve what is available at
#              the point of the circular reference and move on."
#     Context: inference through the cycle still finds the real definition.
def test_circular_import_resolves_available_name(tmp_path):
    files = {
        "a.py": "from b import beta\n\n\ndef alpha():\n    pass\n",
        "b.py": "from a import alpha\n\n\ndef beta():\n    pass\n",
        "main.py": "from a import beta\n" + C + "beta\n",
    }
    got = one(defs_in(tmp_path, files, "infer"))
    assert got["module_path"] == "b.py"


# --- Phrase: "Circular imports: do not infinite-loop."
#     Context: `goto --follow-imports` across the cycle terminates.
def test_circular_import_follow_terminates(tmp_path):
    files = {
        "a.py": "from b import thing\n",
        "b.py": "from a import thing\n",
        "main.py": "from a import thing\n" + C + "thing\n",
    }
    proc = in_project(tmp_path, files, "goto", follow=True)
    assert proc.returncode == 0, proc.stderr


# --- Phrase: "Import of nonexistent module: not an error - return empty results
#              for that module's names."
#     Context: exit status stays 0.
def test_nonexistent_module_is_not_an_error(tmp_path):
    files = {"main.py": "from nope_zzz import thing\n" + C + "thing\n"}
    proc = in_project(tmp_path, files, "infer")
    assert proc.returncode == 0
    assert proc.stdout.strip() == '{"definitions":[]}'


# --- Phrase: "Import of nonexistent module: ... return empty results for that
#              module's names."
#     Context: completion still succeeds and lists the local names.
def test_nonexistent_module_completion_still_works(tmp_path):
    files = {"main.py": "from nope_zzz import thing\nlocal = 1\n" + C + "\n"}
    data = comps_in(tmp_path, files)
    assert has(data, "local")
    assert has(data, "thing")


# --- Phrase: "Syntax errors in imported files: parse as much as possible
#              (same tolerance as the main file)."
#     Context: the imported module has a broken line but a valid def.
def test_syntax_error_in_imported_file_is_tolerated(tmp_path):
    files = {
        "broken.py": "def good():\n    pass\n\n\ndef bad(:\n    pass\n",
        "main.py": "from broken import good\n" + C + "good\n",
    }
    got = one(defs_in(tmp_path, files, "infer"))
    assert (got["module_path"], got["line"]) == ("broken.py", 1)


# --- Phrase: "Syntax errors in imported files: parse as much as possible"
#     Context: completion of the broken module's attributes.
def test_syntax_error_in_imported_file_completion(tmp_path):
    files = {
        "broken.py": "def good():\n    pass\n\nx = = 3\n\nOTHER = 5\n",
        "main.py": "import broken\nbroken." + C + "\n",
    }
    data = comps_in(tmp_path, files)
    assert has(data, "good")
    assert has(data, "OTHER")
