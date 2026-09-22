"""`rename` -- spec: New Subcommands / rename.

Each section quotes the spec phrase it covers.
"""

import json


# ---------------------------------------------------------------------------
# "python sith.py rename <file> <line> <col> --new-name <name>
#  [--diff] [--project <dir>]"
# ---------------------------------------------------------------------------

def test_rename_accepts_the_documented_argument_shape(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("rename", tmp_path, {
        "main.py": "x<|> = 1\nprint(x)\n",
    }, ["--new-name", "y"])
    assert r.returncode == 0, "stderr=%r" % r.stderr
    payload = json.loads(r.stdout)
    assert set(payload) >= {"changed_files", "renames"}


def test_rename_works_without_an_explicit_project_flag(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("rename", tmp_path, {
        "main.py": "x<|> = 1\nprint(x)\n",
    }, ["--new-name", "y"], project=False)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    assert json.loads(r.stdout)["changed_files"]["main.py"] == "y = 1\nprint(y)\n"


# ---------------------------------------------------------------------------
# "Rename the name at the cursor and all its references across the project."
# ---------------------------------------------------------------------------

def test_rename_renames_definition_and_references_in_one_file(rhelpers, tmp_path):
    out = rhelpers.changed("rename", tmp_path, {
        "main.py": "def fo<|>o():\n    pass\n\nfoo()\nprint(foo)\n",
    }, ["--new-name", "bar"])
    assert out["main.py"] == "def bar():\n    pass\n\nbar()\nprint(bar)\n"


def test_rename_reaches_across_files_in_the_project(rhelpers, tmp_path):
    out = rhelpers.changed("rename", tmp_path, {
        "lib.py": "def hel<|>per():\n    pass\n",
        "app.py": "from lib import helper\n\nhelper()\n",
    }, ["--new-name", "assist"])
    assert out["lib.py"] == "def assist():\n    pass\n"
    assert out["app.py"] == "from lib import assist\n\nassist()\n"


def test_rename_leaves_an_unrelated_same_spelled_name_alone(rhelpers, tmp_path):
    out = rhelpers.changed("rename", tmp_path, {
        "main.py": "def f():\n    val<|>ue = 1\n    return value\n\n"
                   "def g():\n    value = 2\n    return value\n",
    }, ["--new-name", "v"])
    assert out["main.py"] == ("def f():\n    v = 1\n    return v\n\n"
                             "def g():\n    value = 2\n    return value\n")


def test_rename_renames_a_local_variable_only_in_its_own_scope(rhelpers, tmp_path):
    out = rhelpers.changed("rename", tmp_path, {
        "main.py": "count = 0\n\ndef f():\n    cou<|>nt = 1\n    return count\n",
    }, ["--new-name", "n"])
    assert out["main.py"] == "count = 0\n\ndef f():\n    n = 1\n    return n\n"


def test_rename_covers_a_parameter_and_its_uses(rhelpers, tmp_path):
    out = rhelpers.changed("rename", tmp_path, {
        "main.py": "def f(ar<|>g):\n    return arg + 1\n",
    }, ["--new-name", "value"])
    assert out["main.py"] == "def f(value):\n    return value + 1\n"


def test_rename_updates_a_class_and_its_constructor_calls(rhelpers, tmp_path):
    out = rhelpers.changed("rename", tmp_path, {
        "main.py": "class Th<|>ing:\n    pass\n\nt = Thing()\n",
    }, ["--new-name", "Widget"])
    assert out["main.py"] == "class Widget:\n    pass\n\nt = Widget()\n"


# ---------------------------------------------------------------------------
# "`changed_files` | object | Map of file path (relative to project root) to
#  new file content."
# ---------------------------------------------------------------------------

def test_changed_files_keys_are_relative_to_the_project_root(rhelpers, tmp_path):
    out = rhelpers.changed("rename", tmp_path, {
        "pkg/__init__.py": "",
        "pkg/mod.py": "def he<|>y():\n    pass\n",
        "app.py": "from pkg.mod import hey\n\nhey()\n",
    }, ["--new-name", "yo"])
    assert set(out) == {"pkg/mod.py", "app.py"}
    assert out["pkg/mod.py"] == "def yo():\n    pass\n"


def test_changed_files_values_are_whole_new_file_contents(rhelpers, tmp_path):
    out = rhelpers.changed("rename", tmp_path, {
        "main.py": "HEADER = 1\n\n\ndef ta<|>rget():\n    pass\n\n\nEND = 2\n",
    }, ["--new-name", "renamed"])
    assert out["main.py"] == ("HEADER = 1\n\n\ndef renamed():\n    pass\n\n\n"
                              "END = 2\n")


# ---------------------------------------------------------------------------
# "Only files that actually changed are included." / clarification:
# "`changed_files` must include only files whose content actually changed."
# ---------------------------------------------------------------------------

def test_untouched_project_files_are_not_in_changed_files(rhelpers, tmp_path):
    out = rhelpers.changed("rename", tmp_path, {
        "main.py": "def to<|>uch():\n    pass\n",
        "other.py": "def unrelated():\n    pass\n",
        "third.py": "X = 1\n",
    }, ["--new-name", "touched"])
    assert list(out) == ["main.py"]


def test_a_file_that_only_mentions_an_unrelated_homonym_is_excluded(rhelpers, tmp_path):
    out = rhelpers.changed("rename", tmp_path, {
        "main.py": "def f():\n    tmp<|> = 1\n    return tmp\n",
        "other.py": "tmp = 5\nprint(tmp)\n",
    }, ["--new-name", "scratch"])
    assert list(out) == ["main.py"]


# ---------------------------------------------------------------------------
# "`renames` | object | Map of old path to new path, for file/directory
#  renames (see below). Empty if no paths changed."
# ---------------------------------------------------------------------------

def test_renames_is_empty_when_no_paths_change(rhelpers, tmp_path):
    payload = rhelpers.refactor("rename", tmp_path, {
        "main.py": "x<|> = 1\nprint(x)\n",
    }, ["--new-name", "y"])
    assert payload["renames"] == {}


# ---------------------------------------------------------------------------
# "**Module renames:** ... Renaming a module `foo` renames `foo.py` to
#  `<new_name>.py`."
# ---------------------------------------------------------------------------

def test_renaming_a_module_renames_its_file(rhelpers, tmp_path):
    payload = rhelpers.refactor("rename", tmp_path, {
        "foo.py": "VALUE = 1\n",
        "app.py": "import f<|>oo\n\nprint(foo.VALUE)\n",
    }, ["--new-name", "bar"])
    assert payload["renames"] == {"foo.py": "bar.py"}


def test_module_rename_updates_the_import_and_its_usages(rhelpers, tmp_path):
    payload = rhelpers.refactor("rename", tmp_path, {
        "foo.py": "VALUE = 1\n",
        "app.py": "import f<|>oo\n\nprint(foo.VALUE)\n",
    }, ["--new-name", "bar"])
    assert payload["changed_files"]["app.py"] == "import bar\n\nprint(bar.VALUE)\n"


def test_module_rename_from_a_from_import(rhelpers, tmp_path):
    payload = rhelpers.refactor("rename", tmp_path, {
        "foo.py": "VALUE = 1\n",
        "app.py": "from f<|>oo import VALUE\n\nprint(VALUE)\n",
    }, ["--new-name", "bar"])
    assert payload["renames"] == {"foo.py": "bar.py"}
    assert payload["changed_files"]["app.py"] == ("from bar import VALUE\n\n"
                                                  "print(VALUE)\n")


# ---------------------------------------------------------------------------
# "Renaming a package `foo` (directory with `__init__.py`) renames the
#  directory."
# ---------------------------------------------------------------------------

def test_renaming_a_package_renames_the_directory(rhelpers, tmp_path):
    payload = rhelpers.refactor("rename", tmp_path, {
        "pkg/__init__.py": "",
        "pkg/mod.py": "X = 1\n",
        "app.py": "import p<|>kg.mod\n\nprint(pkg.mod.X)\n",
    }, ["--new-name", "package"])
    assert payload["renames"] == {"pkg": "package"}


def test_package_rename_updates_dotted_imports(rhelpers, tmp_path):
    payload = rhelpers.refactor("rename", tmp_path, {
        "pkg/__init__.py": "",
        "pkg/mod.py": "X = 1\n",
        "app.py": "import p<|>kg.mod\n\nprint(pkg.mod.X)\n",
    }, ["--new-name", "package"])
    assert payload["changed_files"]["app.py"] == ("import package.mod\n\n"
                                                  "print(package.mod.X)\n")


# ---------------------------------------------------------------------------
# "All import statements referencing the old name are updated."
# ---------------------------------------------------------------------------

def test_every_importing_file_is_updated(rhelpers, tmp_path):
    payload = rhelpers.refactor("rename", tmp_path, {
        "foo.py": "VALUE = 1\n",
        "a.py": "import f<|>oo\n",
        "b.py": "from foo import VALUE\n",
        "c.py": "import foo as f\nprint(f.VALUE)\n",
    }, ["--new-name", "bar"])
    out = payload["changed_files"]
    assert out["a.py"] == "import bar\n"
    assert out["b.py"] == "from bar import VALUE\n"
    assert out["c.py"] == "import bar as f\nprint(f.VALUE)\n"


def test_submodule_rename_updates_the_package_relative_import(rhelpers, tmp_path):
    payload = rhelpers.refactor("rename", tmp_path, {
        "pkg/__init__.py": "",
        "pkg/mod.py": "X = 1\n",
        "app.py": "from pkg import m<|>od\n\nprint(mod.X)\n",
    }, ["--new-name", "core"])
    assert payload["renames"] == {"pkg/mod.py": "pkg/core.py"}
    assert payload["changed_files"]["app.py"] == ("from pkg import core\n\n"
                                                  "print(core.X)\n")


# ---------------------------------------------------------------------------
# "**With `--diff`:** Output a unified diff instead of full file contents"
# "With `--diff`, output is plain text to STDOUT (not JSON)."
# ---------------------------------------------------------------------------

def test_diff_output_is_not_json(rhelpers, tmp_path):
    out = rhelpers.diff_text("rename", tmp_path, {
        "main.py": "x<|> = 1\nprint(x)\n",
    }, ["--new-name", "y"])
    try:
        json.loads(out)
    except ValueError:
        pass
    else:
        raise AssertionError("--diff emitted JSON: %r" % out)


def test_diff_output_contains_the_unified_diff_markers(rhelpers, tmp_path):
    out = rhelpers.diff_text("rename", tmp_path, {
        "main.py": "x<|> = 1\nprint(x)\n",
    }, ["--new-name", "y"])
    assert "---" in out and "+++" in out
    assert "@@" in out
    assert "-x = 1" in out and "+y = 1" in out
    assert "-print(x)" in out and "+print(y)" in out


def test_diff_names_the_changed_file(rhelpers, tmp_path):
    out = rhelpers.diff_text("rename", tmp_path, {
        "main.py": "x<|> = 1\nprint(x)\n",
    }, ["--new-name", "y"])
    assert "main.py" in out


def test_diff_covers_every_changed_file(rhelpers, tmp_path):
    out = rhelpers.diff_text("rename", tmp_path, {
        "lib.py": "def hel<|>per():\n    pass\n",
        "app.py": "from lib import helper\n\nhelper()\n",
    }, ["--new-name", "assist"])
    assert "lib.py" in out and "app.py" in out
    assert "+def assist():" in rhelpers.added(out) or "def assist():" in rhelpers.added(out)


# ---------------------------------------------------------------------------
# "**Rename scope:** All references found via the same logic as
#  `references --scope project` are renamed."
# ---------------------------------------------------------------------------

def test_rename_touches_exactly_the_reference_positions(rhelpers, tmp_path):
    files = {
        "lib.py": "def hel<|>per():\n    pass\n",
        "app.py": "from lib import helper\n\nhelper()\nhelper()\n",
    }
    body, cursor, _ = rhelpers.split_markers(files["lib.py"])
    rhelpers.make_project(tmp_path, {"lib.py": body, "app.py": files["app.py"]})
    r = rhelpers.run_raw(["references", str(tmp_path / "lib.py"),
                          str(cursor[0]), str(cursor[1]),
                          "--scope", "project", "--project", str(tmp_path)])
    assert r.returncode == 0, "stderr=%r" % r.stderr
    refs = json.loads(r.stdout)["references"]
    touched = {r["module_path"] for r in refs}
    out = rhelpers.changed("rename", tmp_path, files, ["--new-name", "assist"])
    assert set(out) == touched


# ---------------------------------------------------------------------------
# "`--new-name` must be a valid Python identifier. If not, exit 1."
# ---------------------------------------------------------------------------

def test_invalid_identifier_exits_one(rhelpers, tmp_path):
    for bad in ("1abc", "with-dash", "", "a b", "x.y"):
        r = rhelpers.refactor_raw("rename", tmp_path, {
            "main.py": "x<|> = 1\nprint(x)\n",
        }, ["--new-name", bad])
        assert r.returncode == 1, "accepted %r" % bad


def test_python_keyword_is_not_a_valid_new_name(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("rename", tmp_path, {
        "main.py": "x<|> = 1\nprint(x)\n",
    }, ["--new-name", "class"])
    assert r.returncode == 1


def test_invalid_identifier_emits_no_edit_output(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("rename", tmp_path, {
        "main.py": "x<|> = 1\nprint(x)\n",
    }, ["--new-name", "1abc"])
    assert r.returncode == 1
    assert "changed_files" not in r.stdout


# ---------------------------------------------------------------------------
# "If the cursor is not on a name, exit 1."
# ---------------------------------------------------------------------------

def test_cursor_not_on_a_name_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("rename", tmp_path, {
        "main.py": "x = 1 <|>+ 2\n",
    }, ["--new-name", "y"])
    assert r.returncode == 1


def test_cursor_on_a_number_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("rename", tmp_path, {
        "main.py": "x = 12<|>3\n",
    }, ["--new-name", "y"])
    assert r.returncode == 1


# ---------------------------------------------------------------------------
# "If the new name would collide with an existing name in scope, exit 1 with
#  a descriptive message."
# ---------------------------------------------------------------------------

def test_collision_in_the_same_scope_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("rename", tmp_path, {
        "main.py": "def f():\n    a<|> = 1\n    b = 2\n    return a + b\n",
    }, ["--new-name", "b"])
    assert r.returncode == 1


def test_collision_message_is_descriptive(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("rename", tmp_path, {
        "main.py": "def f():\n    a<|> = 1\n    b = 2\n    return a + b\n",
    }, ["--new-name", "b"])
    assert r.returncode == 1
    assert r.stderr.strip(), "expected a descriptive message on stderr"
    assert "b" in r.stderr


def test_collision_emits_no_edit_output(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("rename", tmp_path, {
        "main.py": "def f():\n    a<|> = 1\n    b = 2\n    return a + b\n",
    }, ["--new-name", "b"])
    assert "changed_files" not in r.stdout


def test_module_level_collision_exits_one(rhelpers, tmp_path):
    r = rhelpers.refactor_raw("rename", tmp_path, {
        "main.py": "def fir<|>st():\n    pass\n\ndef second():\n    pass\n",
    }, ["--new-name", "second"])
    assert r.returncode == 1


def test_a_name_in_a_different_scope_is_not_a_collision(rhelpers, tmp_path):
    out = rhelpers.changed("rename", tmp_path, {
        "main.py": "def f():\n    a<|> = 1\n    return a\n\ndef g():\n    b = 2\n",
    }, ["--new-name", "b"])
    assert out["main.py"] == ("def f():\n    b = 1\n    return b\n\n"
                              "def g():\n    b = 2\n")
