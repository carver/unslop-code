"""Spec section: Project Configuration (`project init`, `.sith/project.json`)."""
import json

from conftest import (PY, read_config, run_raw, split_cursor, write_config,
                      write_source, write_tree)


def init(*args, cwd):
    return run_raw("project", "init", *[str(a) for a in args], cwd=cwd)


def init_json(*args, cwd):
    proc = init(*args, cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def goto_defs(tmp_path, code, files=None, project=None, cwd=None,
              name="main.py"):
    write_tree(tmp_path, files or {})
    src, line, col = split_cursor(code)
    path = write_source(tmp_path, src, name)
    args = ["goto", str(path), line, col, "--follow-imports"]
    if project is not None:
        args += ["--project", str(project)]
    proc = run_raw(*args, cwd=cwd or str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["definitions"]


# --- Phrase: "Create or update a project configuration file at
#     `<dir>/.sith/project.json`."
def test_project_init_writes_the_config_file(tmp_path):
    init_json(cwd=str(tmp_path))
    assert (tmp_path / ".sith" / "project.json").is_file()


# --- Phrase: "Creates the `.sith/` directory if needed."
def test_project_init_creates_the_directory(tmp_path):
    assert not (tmp_path / ".sith").exists()
    init_json(cwd=str(tmp_path))
    assert (tmp_path / ".sith").is_dir()


# --- Phrase: "If `<dir>` is omitted, use the current directory."
def test_project_init_defaults_to_the_current_directory(tmp_path):
    init_json(cwd=str(tmp_path))
    assert (tmp_path / ".sith" / "project.json").is_file()


# --- Phrase: "python sith.py project init [<dir>]" — an explicit directory.
def test_project_init_with_explicit_directory(tmp_path):
    target = tmp_path / "sub"
    target.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    init_json(target, cwd=str(other))
    assert (target / ".sith" / "project.json").is_file()
    assert not (other / ".sith").exists()


# --- Phrase: "Default values: `environment_path` = "" (empty string),
#     `added_sys_path` = [], `sys_path` = [], `smart_sys_path` = true."
def test_project_init_defaults(tmp_path):
    init_json(cwd=str(tmp_path))
    cfg = read_config(tmp_path)
    assert cfg["environment_path"] == ""
    assert cfg["sys_path"] == []
    assert cfg["added_sys_path"] == []
    assert cfg["smart_sys_path"] is True


# --- Phrase: "--environment <executable>" sets `environment_path`.
def test_project_init_environment_flag(tmp_path):
    init_json("--environment", PY, cwd=str(tmp_path))
    assert read_config(tmp_path)["environment_path"] == PY


# --- Phrase: "--sys-path <path>[,<path>...]" — a comma separated list.
def test_project_init_sys_path_flag(tmp_path):
    init_json("--sys-path", "libs,vendor", cwd=str(tmp_path))
    assert read_config(tmp_path)["sys_path"] == ["libs", "vendor"]


# --- Phrase: "--added-sys-path <path>[,<path>...]".
def test_project_init_added_sys_path_flag(tmp_path):
    init_json("--added-sys-path", "extra", cwd=str(tmp_path))
    assert read_config(tmp_path)["added_sys_path"] == ["extra"]


# --- Phrase: "If `project.json` already exists, merge the provided flags into
#     the existing config (only overwrite fields that were explicitly passed)."
def test_project_init_merges_into_an_existing_config(tmp_path):
    init_json("--sys-path", "libs", "--environment", PY, cwd=str(tmp_path))
    init_json("--added-sys-path", "extra", cwd=str(tmp_path))
    cfg = read_config(tmp_path)
    assert cfg["sys_path"] == ["libs"]
    assert cfg["environment_path"] == PY
    assert cfg["added_sys_path"] == ["extra"]


# --- Phrase: fields that were not passed keep hand-written values.
def test_project_init_preserves_unpassed_fields(tmp_path):
    write_config(tmp_path, {"environment_path": "/usr/bin/python3",
                            "sys_path": ["a"], "added_sys_path": ["b"],
                            "smart_sys_path": False})
    init_json("--added-sys-path", "c", cwd=str(tmp_path))
    cfg = read_config(tmp_path)
    assert cfg["environment_path"] == "/usr/bin/python3"
    assert cfg["sys_path"] == ["a"]
    assert cfg["added_sys_path"] == ["c"]
    assert cfg["smart_sys_path"] is False


# --- Phrase: the written file is valid JSON holding the four documented
#     fields.
def test_project_init_file_shape(tmp_path):
    payload = init_json(cwd=str(tmp_path))
    cfg = read_config(tmp_path)
    assert set(cfg) == {"environment_path", "sys_path", "added_sys_path",
                        "smart_sys_path"}
    assert payload == cfg


# --- Phrase: "`smart_sys_path` — bool, true" is settable through `--setting`.
def test_project_init_records_smart_sys_path_setting(tmp_path):
    init_json("--setting", "smart_sys_path=false", cwd=str(tmp_path))
    assert read_config(tmp_path)["smart_sys_path"] is False


# --- Phrase: an unknown `project` subcommand is a usage error.
def test_unknown_project_subcommand(tmp_path):
    proc = run_raw("project", "bogus", cwd=str(tmp_path))
    assert proc.returncode == 1
    assert proc.stdout == ""


def test_project_requires_a_subcommand(tmp_path):
    proc = run_raw("project", cwd=str(tmp_path))
    assert proc.returncode == 1


# --- Phrase: "All commands now check for `.sith/project.json` in the project
#     root (determined by `--project` or the file's directory)."
def test_added_sys_path_makes_a_module_importable(tmp_path):
    write_config(tmp_path, {"added_sys_path": ["libs"]})
    defs = goto_defs(
        tmp_path,
        "import helper\nhelper█\n",
        files={"libs/helper.py": "VALUE = 1\n"},
    )
    assert defs
    assert any(d["module_path"] == "libs/helper.py" for d in defs) or \
        any(d["name"] == "helper" for d in defs)


# --- Phrase: "`added_sys_path` appends extra import roots ... and can make
#     otherwise-unimportable project modules resolvable." — without the config
#     the same import stays unresolved.
def test_without_added_sys_path_the_module_is_unimportable(tmp_path):
    defs = goto_defs(
        tmp_path,
        "from helper import VALUE\nVALU█E\n",
        files={"libs/helper.py": "VALUE = 1\n"},
    )
    assert all(d["module_path"] != "libs/helper.py" for d in defs)


def test_added_sys_path_resolves_a_name_through_the_import(tmp_path):
    write_config(tmp_path, {"added_sys_path": ["libs"]})
    defs = goto_defs(
        tmp_path,
        "from helper import VALUE\nVALU█E\n",
        files={"libs/helper.py": "VALUE = 1\n"},
        cwd=str(tmp_path),
    )
    assert any(d["module_path"] == "libs/helper.py" for d in defs)


# --- Phrase: "`sys_path`, when non-empty, replaces the auto-detected search
#     path." — the project root is no longer searched.
def test_sys_path_replaces_the_auto_detected_path(tmp_path):
    write_config(tmp_path, {"sys_path": ["libs"]})
    defs = goto_defs(
        tmp_path,
        "from sibling import A\nfrom helper import VALUE\nVALU█E\n",
        files={"libs/helper.py": "VALUE = 1\n", "sibling.py": "A = 1\n"},
    )
    assert any(d["module_path"] == "libs/helper.py" for d in defs)
    defs2 = goto_defs(
        tmp_path,
        "from sibling import A\n█A\n",
        files={"libs/helper.py": "VALUE = 1\n", "sibling.py": "A = 1\n"},
        name="main2.py",
    )
    assert all(d["module_path"] != "sibling.py" for d in defs2)


# --- Phrase: "`added_sys_path` appends extra import roots after ... the
#     explicit `sys_path` list when `sys_path` is set".
def test_added_sys_path_applies_on_top_of_sys_path(tmp_path):
    write_config(tmp_path, {"sys_path": ["libs"], "added_sys_path": ["more"]})
    defs = goto_defs(
        tmp_path,
        "from second import B\n█B\n",
        files={"libs/helper.py": "VALUE = 1\n", "more/second.py": "B = 2\n"},
    )
    assert any(d["module_path"] == "more/second.py" for d in defs)


# --- Phrase: "`smart_sys_path=false` disables auto-detected path additions;
#     only explicitly configured paths participate in import resolution."
def test_smart_sys_path_false_disables_the_project_root(tmp_path):
    write_config(tmp_path, {"smart_sys_path": False})
    defs = goto_defs(
        tmp_path,
        "from sibling import A\n█A\n",
        files={"sibling.py": "A = 1\n"},
    )
    assert all(d["module_path"] != "sibling.py" for d in defs)


def test_smart_sys_path_false_keeps_explicit_paths(tmp_path):
    write_config(tmp_path, {"smart_sys_path": False,
                            "added_sys_path": ["libs"]})
    defs = goto_defs(
        tmp_path,
        "from helper import VALUE\nVALU█E\n",
        files={"libs/helper.py": "VALUE = 1\n"},
    )
    assert any(d["module_path"] == "libs/helper.py" for d in defs)


# --- Phrase: "the project root (determined by `--project` or the file's
#     directory)" — the config is looked up in the `--project` directory.
def test_config_is_read_from_the_project_directory(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    write_config(proj, {"added_sys_path": ["libs"]})
    write_tree(proj, {"libs/helper.py": "VALUE = 1\n"})
    src, line, col = split_cursor("from helper import VALUE\nVALU█E\n")
    path = write_source(proj, src, "main.py")
    proc = run_raw("goto", str(path), line, col, "--follow-imports",
                   "--project", str(proj), cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    defs = json.loads(proc.stdout)["definitions"]
    assert any(d["module_path"] == "libs/helper.py" for d in defs)


# --- Phrase: the config also applies to `complete`.
def test_config_applies_to_completion(tmp_path):
    write_config(tmp_path, {"added_sys_path": ["libs"]})
    write_tree(tmp_path, {"libs/helper.py": "VALUE = 1\n"})
    src, line, col = split_cursor("import helper\nhelper.█\n")
    path = write_source(tmp_path, src, "main.py")
    proc = run_raw("complete", str(path), line, col, cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    names = [c["name"] for c in json.loads(proc.stdout)["completions"]]
    assert "VALUE" in names


# --- Phrase: a malformed or absent config never breaks a command.
def test_absent_config_is_fine(tmp_path):
    defs = goto_defs(tmp_path, "x = 1\n█x\n")
    assert defs


def test_malformed_config_is_ignored(tmp_path):
    (tmp_path / ".sith").mkdir()
    (tmp_path / ".sith" / "project.json").write_text("{oops", encoding="utf-8")
    defs = goto_defs(tmp_path, "x = 1\n█x\n")
    assert defs
