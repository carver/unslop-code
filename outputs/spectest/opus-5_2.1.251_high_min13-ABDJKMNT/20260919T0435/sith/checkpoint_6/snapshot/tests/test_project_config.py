"""`project init` and the `.sith/project.json` a command reads back."""
import json
import shutil

from conftest import run_cli

WIDGET = 'class Widget:\n    """A widget."""\n'
DEFAULTS = {
    "environment_path": "",
    "sys_path": [],
    "added_sys_path": [],
    "smart_sys_path": True,
}


def written(directory):
    return json.loads((directory / ".sith" / "project.json").read_text(encoding="utf-8"))


# "python sith.py project init [<dir>] ..." / "Create or update a project configuration
#  file at `<dir>/.sith/project.json`."
def test_project_init_writes_the_configuration_file(workdir):
    result = run_cli("project", "init", str(workdir / "app"), cwd=workdir)
    assert result.returncode == 0, result.stderr
    assert (workdir / "app" / ".sith" / "project.json").is_file()


# "If `<dir>` is omitted, use the current directory."
def test_project_init_defaults_to_the_current_directory(workdir):
    run_cli("project", "init", cwd=workdir)
    assert (workdir / ".sith" / "project.json").is_file()


# "Creates the `.sith/` directory if needed."
def test_project_init_creates_the_sith_directory(workdir):
    assert not (workdir / ".sith").exists()
    run_cli("project", "init", cwd=workdir)
    assert (workdir / ".sith").is_dir()


# "Default values: `environment_path` = `\"\"` (empty string), `added_sys_path` = `[]`,
#  `sys_path` = `[]`, `smart_sys_path` = `true`."
def test_project_init_defaults(workdir):
    run_cli("project", "init", cwd=workdir)
    assert written(workdir) == DEFAULTS


# "| `environment_path` | string or null | Path to the Python executable to use for
#  this project. |"
def test_environment_flag_is_recorded(workdir):
    run_cli("project", "init", "--environment", "/usr/bin/python3", cwd=workdir)
    assert written(workdir)["environment_path"] == "/usr/bin/python3"


# "[--sys-path <path>[,<path>...]]" / "| `sys_path` | array of string | Explicit
#  sys.path entries. |"
def test_sys_path_flag_is_split_on_commas(workdir):
    run_cli("project", "init", "--sys-path", "/one,/two", cwd=workdir)
    assert written(workdir)["sys_path"] == ["/one", "/two"]


# "[--added-sys-path <path>[,<path>...]]"
def test_added_sys_path_flag_is_split_on_commas(workdir):
    run_cli("project", "init", "--added-sys-path", "/extra", cwd=workdir)
    assert written(workdir)["added_sys_path"] == ["/extra"]


# "If `project.json` already exists, merge the provided flags into the existing config
#  (only overwrite fields that were explicitly passed)."
def test_a_second_init_keeps_the_fields_it_was_not_given(workdir):
    run_cli("project", "init", "--sys-path", "/one", cwd=workdir)
    run_cli("project", "init", "--environment", "/usr/bin/python3", cwd=workdir)
    config = written(workdir)
    assert config["sys_path"] == ["/one"]
    assert config["environment_path"] == "/usr/bin/python3"


def test_a_second_init_overwrites_the_fields_it_was_given(workdir):
    run_cli("project", "init", "--sys-path", "/one", cwd=workdir)
    run_cli("project", "init", "--sys-path", "/two", cwd=workdir)
    assert written(workdir)["sys_path"] == ["/two"]


def test_merging_preserves_unknown_settings(workdir, project_config):
    project_config({"smart_sys_path": False})
    run_cli("project", "init", "--environment", "/usr/bin/python3", cwd=workdir)
    assert written(workdir)["smart_sys_path"] is False


# "All commands now check for `.sith/project.json` in the project root ... `sys_path`,
#  when non-empty, replaces the auto-detected search path."
def test_sys_path_replaces_the_auto_detected_root(infer, project_config, workdir):
    project_config({"sys_path": [str(workdir / "extra")]})
    files = {"helpers.py": WIDGET, "extra/vendor.py": WIDGET}
    source = "from helpers import Widget\nWid|get\n"
    assert infer(source, files=files, project=".").definitions == []


def test_sys_path_entries_are_searched(infer, project_config, workdir):
    project_config({"sys_path": [str(workdir / "extra")]})
    files = {"extra/vendor.py": WIDGET}
    source = "from vendor import Widget\nWid|get\n"
    assert infer(source, files=files, project=".").only["name"] == "Widget"


# "`added_sys_path` appends extra import roots after the auto-detected search path ...
#  and can make otherwise-unimportable project modules resolvable."
def test_added_sys_path_makes_a_module_importable(infer, project_config, workdir):
    files = {"extra/vendor.py": WIDGET}
    source = "from vendor import Widget\nWid|get\n"
    assert infer(source, files=files, project=".").definitions == []
    project_config({"added_sys_path": [str(workdir / "extra")]})
    assert infer(source, files=files, project=".").only["name"] == "Widget"


def test_added_sys_path_keeps_the_auto_detected_root(infer, project_config, workdir):
    project_config({"added_sys_path": [str(workdir / "extra")]})
    files = {"helpers.py": WIDGET, "extra/vendor.py": WIDGET}
    source = "from helpers import Widget\nWid|get\n"
    assert infer(source, files=files, project=".").only["name"] == "Widget"


# "`smart_sys_path=false` disables auto-detected path additions; only explicitly
#  configured paths participate in import resolution."
def test_smart_sys_path_false_drops_the_project_root(infer, project_config):
    project_config({"smart_sys_path": False})
    source = "from helpers import Widget\nWid|get\n"
    assert infer(source, files={"helpers.py": WIDGET}, project=".").definitions == []


def test_smart_sys_path_false_still_uses_configured_paths(infer, project_config, workdir):
    project_config({"smart_sys_path": False, "added_sys_path": [str(workdir / "extra")]})
    files = {"extra/vendor.py": WIDGET}
    source = "from vendor import Widget\nWid|get\n"
    assert infer(source, files=files, project=".").only["name"] == "Widget"


# "All commands now check for `.sith/project.json` in the project root (determined by
#  `--project` or the file's directory)."
def test_the_config_is_read_from_the_files_own_directory(infer, workdir, project_config):
    project_config({"smart_sys_path": False})
    source = "from helpers import Widget\nWid|get\n"
    assert infer(source, files={"helpers.py": WIDGET}).definitions == []


# "`environment_path` selects which Python executable to use when a command consults
#  project environment metadata."
def test_environment_path_is_what_env_info_reports(workdir, virtualenv):
    executable = str(virtualenv / "bin" / "python")
    run_cli("project", "init", "--environment", executable, cwd=workdir)
    environment = run_cli("env", "info", cwd=workdir).payload["environment"]
    assert environment["executable"] == executable


# "If null or empty string, use the system default."
def test_an_empty_environment_path_falls_back_to_the_system_default(workdir):
    run_cli("project", "init", cwd=workdir)
    environment = run_cli("env", "info", cwd=workdir).payload["environment"]
    assert environment["executable"] == shutil.which("python3")
