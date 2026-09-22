"""Spec section: Project Root (`--project <dir>`)."""
import json

from conftest import (CURSOR, comps_in, defs_in, has, one, run_cmd,
                      write_tree)

C = CURSOR


# --- Phrase: "All commands now accept an optional `--project <dir>` flag."
#     Context: `complete` accepts the flag and still exits 0.
def test_complete_accepts_project_flag(tmp_path):
    data = comps_in(tmp_path, {"main.py": "x = 1\n" + C + "\n"},
                    project=tmp_path)
    assert has(data, "x")


# --- Phrase: "All commands now accept an optional `--project <dir>` flag."
#     Context: `infer` accepts the flag.
def test_infer_accepts_project_flag(tmp_path):
    defs = defs_in(tmp_path, {"main.py": "x = 1\n" + C + "x\n"}, "infer",
                   project=tmp_path)
    assert one(defs)["name"] == "int"


# --- Phrase: "All commands now accept an optional `--project <dir>` flag."
#     Context: `goto` accepts the flag.
def test_goto_accepts_project_flag(tmp_path):
    defs = defs_in(tmp_path, {"main.py": "x = 1\n" + C + "x\n"}, "goto",
                   project=tmp_path)
    assert one(defs)["line"] == 1


# --- Phrase: "All commands now accept an optional `--project <dir>` flag."
#     Context: the flag is optional - omitting it still works.
def test_project_flag_is_optional(tmp_path):
    data = comps_in(tmp_path, {"main.py": "x = 1\n" + C + "\n"})
    assert has(data, "x")


# --- Phrase: "When provided, the project root is `<dir>`."
#     Context: file lives in a package below the root; imports resolve from the root.
def test_project_root_used_for_module_search(tmp_path):
    files = {
        "lib.py": "def helper():\n    pass\n",
        "pkg/__init__.py": "",
        "pkg/app.py": "from lib import helper\n" + C + "helper\n",
    }
    defs = defs_in(tmp_path, files, "infer", project=tmp_path)
    assert one(defs)["module_path"] == "lib.py"


# --- Phrase: "When omitted, the project root is the directory containing `<file>`."
#     Context: without --project, `lib.py` at the tree root is NOT reachable from pkg/app.py.
def test_default_root_is_file_directory(tmp_path):
    files = {
        "lib.py": "def helper():\n    pass\n",
        "pkg/__init__.py": "",
        "pkg/app.py": "from lib import helper\n" + C + "helper\n",
    }
    defs = defs_in(tmp_path, files, "infer")
    assert defs == []


# --- Phrase: "When omitted, the project root is the directory containing `<file>`."
#     Context: a sibling module of the analysed file resolves without --project.
def test_default_root_resolves_siblings(tmp_path):
    files = {
        "pkg/lib.py": "def helper():\n    pass\n",
        "pkg/app.py": "from lib import helper\n" + C + "helper\n",
    }
    defs = defs_in(tmp_path, files, "infer")
    assert one(defs)["module_path"] == "lib.py"


# --- Phrase: "The project root determines: ... The base for computing module
#              qualified names."
#     Context: module_path is relative to the project root, not to the file.
def test_module_path_relative_to_project_root(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/lib.py": "def helper():\n    pass\n",
        "main.py": "from pkg.lib import helper\n" + C + "helper\n",
    }
    defs = defs_in(tmp_path, files, "infer", project=tmp_path)
    assert one(defs)["module_path"] == "pkg/lib.py"


# --- Phrase: "The base for computing module qualified names."
#     Context: full_name is the dotted path from the project root.
def test_full_name_from_project_root(tmp_path):
    files = {
        "pkg/__init__.py": "",
        "pkg/lib.py": "def helper():\n    pass\n",
        "main.py": "from pkg.lib import helper\n" + C + "helper\n",
    }
    defs = defs_in(tmp_path, files, "infer", project=tmp_path)
    assert one(defs)["full_name"] == "pkg.lib.helper"


# --- Phrase: "When provided, the project root is `<dir>`."
#     Context: a relative --project argument is interpreted from the process cwd.
def test_project_flag_accepts_relative_dir(tmp_path):
    files = {
        "lib.py": "VALUE = 1\n",
        "pkg/app.py": "from lib import VALUE\n" + C + "VALUE\n",
    }
    write_tree(tmp_path, {k: v.replace(C, "") for k, v in files.items()})
    proc = run_cmd("infer", tmp_path / "pkg" / "app.py", 2, 0, project=".",
                   cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["definitions"][0]["name"] == "int"
