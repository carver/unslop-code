"""Spec: Project Configuration."""

import json
import sys

from conftest import invoke, run_command, write_config, write_files, write_source

HELPER = "class Thing:\n    pass\n"


def config_of(root):
    """The configuration document written under a project root."""
    return json.loads((root / ".sith" / "project.json").read_text(encoding="utf-8"))


def init(*arguments, **options):
    result = run_command("project", "init", *arguments, **options)
    assert result.code == 0, result.stderr
    return result


# Spec: "python sith.py project init [<dir>] ..." - "Create or update a project
# configuration file at `<dir>/.sith/project.json`."
def test_project_init_writes_the_configuration_file(tmp_path):
    init(tmp_path)
    assert (tmp_path / ".sith" / "project.json").is_file()


# Spec: "Creates the `.sith/` directory if needed."
def test_project_init_creates_the_directory(tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()
    init(root)
    assert (root / ".sith").is_dir()


# Spec: "If `<dir>` is omitted, use the current directory."
def test_project_init_defaults_to_the_current_directory(tmp_path):
    result = run_command("project", "init", cwd=tmp_path)
    assert result.code == 0
    assert config_of(tmp_path)["smart_sys_path"] is True


# Spec: "Default values: `environment_path` = `""` (empty string),
# `added_sys_path` = `[]`, `sys_path` = `[]`, `smart_sys_path` = `true`."
def test_default_configuration(tmp_path):
    init(tmp_path)
    assert config_of(tmp_path) == {
        "environment_path": "",
        "sys_path": [],
        "added_sys_path": [],
        "smart_sys_path": True,
    }


# Spec: "`environment_path` | string or null | Path to the Python executable to
# use for this project."
def test_environment_flag_is_stored(tmp_path):
    init(tmp_path, flags=["--environment", sys.executable])
    assert config_of(tmp_path)["environment_path"] == sys.executable


# Spec: "[--sys-path <path>[,<path>...]]"
def test_sys_path_flag_takes_a_comma_separated_list(tmp_path):
    init(tmp_path, flags=["--sys-path", "libs,vendor"])
    assert config_of(tmp_path)["sys_path"] == ["libs", "vendor"]


# Spec: "[--added-sys-path <path>[,<path>...]]"
def test_added_sys_path_flag_takes_a_comma_separated_list(tmp_path):
    init(tmp_path, flags=["--added-sys-path", "extra"])
    assert config_of(tmp_path)["added_sys_path"] == ["extra"]


# Spec: "If `project.json` already exists, merge the provided flags into the
# existing config (only overwrite fields that were explicitly passed)."
def test_existing_settings_survive_a_second_init(tmp_path):
    init(tmp_path, flags=["--sys-path", "libs"])
    init(tmp_path, flags=["--added-sys-path", "extra"])
    written = config_of(tmp_path)
    assert written["sys_path"] == ["libs"]
    assert written["added_sys_path"] == ["extra"]


def test_a_passed_flag_overwrites_the_existing_value(tmp_path):
    init(tmp_path, flags=["--environment", "/usr/bin/python3"])
    init(tmp_path, flags=["--environment", "/usr/local/bin/python3"])
    assert config_of(tmp_path)["environment_path"] == "/usr/local/bin/python3"


def test_unknown_fields_of_an_existing_config_are_kept(tmp_path):
    write_config(tmp_path, {"smart_sys_path": False, "extra_field": 7})
    init(tmp_path)
    written = config_of(tmp_path)
    assert written["extra_field"] == 7
    assert written["smart_sys_path"] is False


# Spec: "All commands now check for `.sith/project.json` in the project root
# ... `added_sys_path` appends extra import roots after the auto-detected
# search path ... and can make otherwise-unimportable project modules
# resolvable."
def test_added_sys_path_makes_a_module_importable(infer, tmp_path):
    write_config(tmp_path, {"added_sys_path": ["libs"]})
    result = infer(
        "import helper\nhelper.Thin$g\n",
        extra={"libs/helper.py": HELPER},
        project=".",
    )
    assert result.only["module_path"] == "libs/helper.py"


def test_without_the_configuration_the_module_is_unimportable(infer):
    result = infer(
        "import helper\nhelper.Thin$g\n", extra={"libs/helper.py": HELPER}, project="."
    )
    assert result.definitions == []


# Spec: "`sys_path`, when non-empty, replaces the auto-detected search path."
def test_sys_path_replaces_the_project_root(infer, tmp_path):
    write_config(tmp_path, {"sys_path": [str(tmp_path / "libs")]})
    result = infer(
        "import helper\nhelper.Thin$g\n",
        extra={"libs/helper.py": HELPER, "helper.py": "class Thing:\n    pass\n"},
        name="app/main.py",
        project=".",
    )
    assert result.only["module_path"] == "libs/helper.py"


def test_sys_path_leaves_the_root_out_of_the_search(infer, tmp_path):
    write_config(tmp_path, {"sys_path": [str(tmp_path / "libs")]})
    result = infer(
        "import other\nother.Thin$g\n", extra={"other.py": HELPER}, project="."
    )
    assert result.definitions == []


# Spec: "`smart_sys_path=false` disables auto-detected path additions; only
# explicitly configured paths participate in import resolution."
def test_smart_sys_path_false_drops_the_project_root(infer, tmp_path):
    write_config(tmp_path, {"smart_sys_path": False})
    result = infer("import helper\nhelper.Thin$g\n", extra={"helper.py": HELPER}, project=".")
    assert result.definitions == []


def test_smart_sys_path_false_still_uses_added_paths(infer, tmp_path):
    write_config(tmp_path, {"smart_sys_path": False, "added_sys_path": ["libs"]})
    result = infer(
        "import helper\nhelper.Thin$g\n", extra={"libs/helper.py": HELPER}, project="."
    )
    assert result.only["module_path"] == "libs/helper.py"


# Spec: "When true, automatically add the project root and directories
# containing `__init__.py` to sys.path."
def test_smart_sys_path_adds_package_directories(infer, tmp_path):
    result = infer(
        "import helper\nhelper.Thin$g\n",
        extra={"pkg/__init__.py": "", "pkg/helper.py": HELPER},
        project=".",
    )
    assert result.only["module_path"] == "pkg/helper.py"


# Spec: "`environment_path` selects which Python executable to use when a
# command consults project environment metadata."
def test_environment_path_selects_the_interpreter_env_info_describes(tmp_path):
    write_config(tmp_path, {"environment_path": sys.executable})
    payload = run_command("env", "info", project=tmp_path).data
    assert payload["executable"] == sys.executable


def test_an_empty_environment_path_falls_back_to_the_system_default(tmp_path):
    write_config(tmp_path, {"environment_path": ""})
    payload = run_command("env", "info", project=tmp_path).data
    assert payload["version"].split(".")[0].isdigit()


def test_a_null_environment_path_falls_back_to_the_system_default(tmp_path):
    write_config(tmp_path, {"environment_path": None})
    payload = run_command("env", "info", project=tmp_path).data
    assert payload["version"].split(".")[0].isdigit()


# Spec: "All commands now check for `.sith/project.json` in the project root
# (determined by `--project` or the file's directory)."
def test_the_configuration_is_found_beside_the_analysed_file(tmp_path):
    write_config(tmp_path, {"added_sys_path": ["libs"]})
    write_files(tmp_path, {"libs/helper.py": HELPER})
    path, line, col = write_source(tmp_path, "import helper\nhelper.Thin$g\n")
    result = invoke("infer", path, line, col)
    assert result.only["module_path"] == "libs/helper.py"
