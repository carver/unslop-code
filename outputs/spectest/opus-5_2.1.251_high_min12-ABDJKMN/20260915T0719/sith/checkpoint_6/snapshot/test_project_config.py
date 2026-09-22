"""`project init` and project-config loading -- spec: "Project Configuration".

See AMBIGUITIES.md T106-T111, T117.
"""

import json
import os
import sys

import pytest

from conftest import (env_json, find, make_project, pcomplete, pinfer, project_init,
                      prun, read_config, run_raw, write_config)


DEFAULTS = {"environment_path": "", "sys_path": [], "added_sys_path": [],
            "smart_sys_path": True}


# =====================================================================
# "Create or update a project configuration file at `<dir>/.sith/project.json`."
# =====================================================================

def test_project_init_writes_the_config_file(tmp_path):
    r = project_init([tmp_path])
    assert r.returncode == 0, "stderr=%r" % r.stderr
    assert (tmp_path / ".sith" / "project.json").is_file()


# "Creates the `.sith/` directory if needed."
def test_project_init_creates_the_sith_directory(tmp_path):
    assert not (tmp_path / ".sith").exists()
    project_init([tmp_path])
    assert (tmp_path / ".sith").is_dir()


# "If `<dir>` is omitted, use the current directory."
def test_project_init_defaults_to_the_current_directory(tmp_path):
    r = project_init([], cwd=str(tmp_path))
    assert r.returncode == 0, "stderr=%r" % r.stderr
    assert (tmp_path / ".sith" / "project.json").is_file()


def test_project_init_on_a_missing_directory_exits_1(tmp_path):
    r = project_init([tmp_path / "nope"])
    assert r.returncode == 1


# =====================================================================
# "Default values: `environment_path` = `""` (empty string),
#  `added_sys_path` = `[]`, `sys_path` = `[]`, `smart_sys_path` = `true`."
# =====================================================================

def test_defaults_are_written(tmp_path):
    project_init([tmp_path])
    assert read_config(tmp_path) == DEFAULTS


@pytest.mark.parametrize("key,value", sorted(DEFAULTS.items(), key=lambda kv: kv[0]))
def test_each_default_value(tmp_path, key, value):
    project_init([tmp_path])
    assert read_config(tmp_path)[key] == value


# =====================================================================
# "[--environment <executable>] [--sys-path <path>[,<path>...]]
#   [--added-sys-path <path>[,<path>...]]"
# =====================================================================

def test_environment_flag_is_stored(tmp_path):
    project_init([tmp_path, "--environment", "/usr/bin/python3"])
    assert read_config(tmp_path)["environment_path"] == "/usr/bin/python3"


def test_sys_path_flag_is_stored(tmp_path):
    project_init([tmp_path, "--sys-path", "/one"])
    assert read_config(tmp_path)["sys_path"] == ["/one"]


# "<path>[,<path>...]" -- comma separated list (T107)
def test_sys_path_splits_on_commas(tmp_path):
    project_init([tmp_path, "--sys-path", "/one,/two,/three"])
    assert read_config(tmp_path)["sys_path"] == ["/one", "/two", "/three"]


def test_added_sys_path_splits_on_commas(tmp_path):
    project_init([tmp_path, "--added-sys-path", "libs,vendor"])
    assert read_config(tmp_path)["added_sys_path"] == ["libs", "vendor"]


def test_flags_accept_the_equals_spelling(tmp_path):
    project_init([tmp_path, "--environment=/usr/bin/python3",
                  "--sys-path=/one", "--added-sys-path=/two"])
    cfg = read_config(tmp_path)
    assert cfg["environment_path"] == "/usr/bin/python3"
    assert cfg["sys_path"] == ["/one"] and cfg["added_sys_path"] == ["/two"]


# T107: relative entries are stored as typed.
def test_relative_entries_are_stored_verbatim(tmp_path):
    project_init([tmp_path, "--added-sys-path", "../libs"])
    assert read_config(tmp_path)["added_sys_path"] == ["../libs"]


def test_config_file_holds_only_the_documented_keys(tmp_path):
    project_init([tmp_path, "--environment", "/usr/bin/python3"])
    assert set(read_config(tmp_path)) == set(DEFAULTS)


# =====================================================================
# "If `project.json` already exists, merge the provided flags into the existing
#  config (only overwrite fields that were explicitly passed)."
# =====================================================================

def test_second_init_keeps_fields_that_were_not_passed(tmp_path):
    project_init([tmp_path, "--environment", "/usr/bin/python3",
                  "--sys-path", "/one"])
    project_init([tmp_path, "--added-sys-path", "/two"])
    cfg = read_config(tmp_path)
    assert cfg["environment_path"] == "/usr/bin/python3"
    assert cfg["sys_path"] == ["/one"]
    assert cfg["added_sys_path"] == ["/two"]


def test_second_init_overwrites_fields_that_were_passed(tmp_path):
    project_init([tmp_path, "--environment", "/usr/bin/python3"])
    project_init([tmp_path, "--environment", "/usr/local/bin/python3.12"])
    assert read_config(tmp_path)["environment_path"] == "/usr/local/bin/python3.12"


def test_init_without_flags_leaves_an_existing_config_alone(tmp_path):
    write_config(tmp_path, {"environment_path": "/usr/bin/python3",
                            "sys_path": ["/one"], "added_sys_path": ["/two"],
                            "smart_sys_path": False})
    project_init([tmp_path])
    assert read_config(tmp_path) == {"environment_path": "/usr/bin/python3",
                                     "sys_path": ["/one"],
                                     "added_sys_path": ["/two"],
                                     "smart_sys_path": False}


def test_missing_fields_are_filled_with_defaults_on_merge(tmp_path):
    write_config(tmp_path, {"environment_path": "/usr/bin/python3"})
    project_init([tmp_path])
    cfg = read_config(tmp_path)
    assert cfg["sys_path"] == [] and cfg["added_sys_path"] == []
    assert cfg["smart_sys_path"] is True


# T108: a corrupt existing config is an error, not something to overwrite.
def test_corrupt_existing_config_exits_1(tmp_path):
    d = tmp_path / ".sith"
    d.mkdir()
    (d / "project.json").write_text("{not json", encoding="utf-8")
    r = project_init([tmp_path])
    assert r.returncode == 1


# T106: the resulting config is echoed as JSON.
def test_project_init_prints_the_resulting_config(tmp_path):
    r = project_init([tmp_path, "--environment", "/usr/bin/python3"])
    payload = json.loads(r.stdout)
    assert payload["environment_path"] == "/usr/bin/python3"
    assert payload["smart_sys_path"] is True


# T117: `--setting` is a runtime override, not something `project init` stores.
def test_setting_flag_is_not_persisted(tmp_path):
    r = project_init([tmp_path, "--setting", "smart_sys_path=false"])
    assert r.returncode == 0, "stderr=%r" % r.stderr
    assert read_config(tmp_path)["smart_sys_path"] is True


def test_unknown_project_subcommand_exits_1(tmp_path):
    r = run_raw(["project", "frobnicate", str(tmp_path)])
    assert r.returncode == 1


def test_project_without_a_subcommand_exits_1():
    assert run_raw(["project"]).returncode == 1


# =====================================================================
# "All commands now check for `.sith/project.json` in the project root
#  (determined by `--project` or the file's directory)."
# =====================================================================

def lib_files(marker="import helper\nhelper.<|>\n"):
    return {"proj/main.py": marker,
            "proj/lib.py": "class Local:\n    pass\n",
            "libs/helper.py": "def hello():\n    pass\n"}


def test_config_is_read_from_the_project_root(tmp_path):
    make_project(tmp_path, lib_files())
    write_config(tmp_path / "proj", dict(DEFAULTS, added_sys_path=["../libs"]))
    comps = pcomplete(tmp_path, lib_files(), project="proj")
    assert find(comps, "hello") is not None


def test_config_is_found_from_a_nested_file(tmp_path):
    files = {"pkg/__init__.py": "", "pkg/main.py": "import helper\nhelper.<|>\n",
             "libs/helper.py": "def hello():\n    pass\n"}
    make_project(tmp_path, files)
    write_config(tmp_path, dict(DEFAULTS, added_sys_path=["libs"]))
    comps = pcomplete(tmp_path, files, project=True)
    assert find(comps, "hello") is not None


def test_without_a_config_the_extra_root_is_not_searched(tmp_path):
    comps = pcomplete(tmp_path, lib_files(), project="proj")
    assert find(comps, "hello") is None


# =====================================================================
# "`added_sys_path` appends extra import roots after the auto-detected search
#  path ... and can make otherwise-unimportable project modules resolvable."
# =====================================================================

def test_added_sys_path_makes_a_module_importable(tmp_path):
    make_project(tmp_path, lib_files())
    write_config(tmp_path / "proj", dict(DEFAULTS, added_sys_path=["../libs"]))
    comps = pcomplete(tmp_path, lib_files(), project="proj")
    assert find(comps, "hello")["type"] == "function"


def test_added_sys_path_accepts_an_absolute_entry(tmp_path):
    make_project(tmp_path, lib_files())
    write_config(tmp_path / "proj",
                 dict(DEFAULTS, added_sys_path=[str(tmp_path / "libs")]))
    comps = pcomplete(tmp_path, lib_files(), project="proj")
    assert find(comps, "hello") is not None


def test_added_sys_path_keeps_the_auto_detected_root(tmp_path):
    files = lib_files("import lib\nlib.<|>\n")
    make_project(tmp_path, files)
    write_config(tmp_path / "proj", dict(DEFAULTS, added_sys_path=["../libs"]))
    comps = pcomplete(tmp_path, files, project="proj")
    assert find(comps, "Local") is not None


# "the auto-detected search path" comes first, so a project module shadows a
# same-named module on an added root.
def test_auto_detected_root_wins_over_an_added_root(tmp_path):
    files = {"proj/main.py": "import dup\ndup.<|>\n",
             "proj/dup.py": "def from_project():\n    pass\n",
             "libs/dup.py": "def from_libs():\n    pass\n"}
    make_project(tmp_path, files)
    write_config(tmp_path / "proj", dict(DEFAULTS, added_sys_path=["../libs"]))
    comps = pcomplete(tmp_path, files, project="proj")
    assert find(comps, "from_project") is not None
    assert find(comps, "from_libs") is None


# =====================================================================
# "`sys_path`, when non-empty, replaces the auto-detected search path."
# =====================================================================

def test_sys_path_replaces_the_project_root(tmp_path):
    files = lib_files("import lib\nlib.<|>\n")
    make_project(tmp_path, files)
    write_config(tmp_path / "proj", dict(DEFAULTS, sys_path=["../libs"]))
    comps = pcomplete(tmp_path, files, project="proj")
    assert find(comps, "Local") is None


def test_sys_path_provides_its_own_roots(tmp_path):
    make_project(tmp_path, lib_files())
    write_config(tmp_path / "proj", dict(DEFAULTS, sys_path=["../libs"]))
    comps = pcomplete(tmp_path, lib_files(), project="proj")
    assert find(comps, "hello") is not None


# "`added_sys_path` appends extra import roots after ... the explicit `sys_path`
#  list when `sys_path` is set"
def test_added_sys_path_applies_on_top_of_sys_path(tmp_path):
    files = {"proj/main.py": "import helper\nimport extra\nhelper.<|>\n",
             "libs/helper.py": "def hello():\n    pass\n",
             "vendor/extra.py": "def extra_fn():\n    pass\n"}
    make_project(tmp_path, files)
    write_config(tmp_path / "proj",
                 dict(DEFAULTS, sys_path=["../libs"], added_sys_path=["../vendor"]))
    comps = pcomplete(tmp_path, files, project="proj")
    assert find(comps, "hello") is not None
    files2 = dict(files, **{"proj/main.py": "import extra\nextra.<|>\n"})
    comps2 = pcomplete(tmp_path, files2, project="proj")
    assert find(comps2, "extra_fn") is not None


# =====================================================================
# "`smart_sys_path=false` disables auto-detected path additions; only
#  explicitly configured paths participate in import resolution."
# =====================================================================

def test_smart_sys_path_false_drops_the_project_root(tmp_path):
    files = lib_files("import lib\nlib.<|>\n")
    make_project(tmp_path, files)
    write_config(tmp_path / "proj", dict(DEFAULTS, smart_sys_path=False))
    comps = pcomplete(tmp_path, files, project="proj")
    assert find(comps, "Local") is None


def test_smart_sys_path_false_still_honours_added_sys_path(tmp_path):
    make_project(tmp_path, lib_files())
    write_config(tmp_path / "proj",
                 dict(DEFAULTS, smart_sys_path=False, added_sys_path=["../libs"]))
    comps = pcomplete(tmp_path, lib_files(), project="proj")
    assert find(comps, "hello") is not None


# T110: the runtime's own modules are not an "auto-detected path addition".
def test_smart_sys_path_false_keeps_stdlib_imports(tmp_path):
    files = {"proj/main.py": "import json\njson.du<|>\n"}
    make_project(tmp_path, files)
    write_config(tmp_path / "proj", dict(DEFAULTS, smart_sys_path=False))
    comps = pcomplete(tmp_path, files, project="proj")
    assert find(comps, "dumps") is not None


def test_smart_sys_path_true_is_the_default_behaviour(tmp_path):
    files = lib_files("import lib\nlib.<|>\n")
    make_project(tmp_path, files)
    write_config(tmp_path / "proj", dict(DEFAULTS))
    comps = pcomplete(tmp_path, files, project="proj")
    assert find(comps, "Local") is not None


# =====================================================================
# "`environment_path` selects which Python executable to use when a command
#  consults project environment metadata." (T104)
# =====================================================================

def test_environment_path_selects_the_env_info_target(tmp_path):
    write_config(tmp_path, dict(DEFAULTS, environment_path=sys.executable))
    payload = env_json(["info", "--project", str(tmp_path)])
    assert os.path.realpath(payload["executable"]) == os.path.realpath(sys.executable)


def test_an_explicit_executable_still_wins_over_the_config(tmp_path):
    write_config(tmp_path, dict(DEFAULTS,
                                environment_path="/definitely/not/python"))
    payload = env_json(["info", sys.executable, "--project", str(tmp_path)])
    assert payload["version"] == "%d.%d.%d" % sys.version_info[:3]


def test_empty_environment_path_falls_back_to_the_system_default(tmp_path):
    write_config(tmp_path, dict(DEFAULTS))
    payload = env_json(["info", "--project", str(tmp_path)])
    assert payload["version"]


# T108: a corrupt config is reported by every command that reads it, not
# silently ignored.
def test_analysis_commands_report_a_corrupt_config(tmp_path):
    files = {"main.py": "x = 1\nx<|>\n"}
    d = tmp_path / ".sith"
    d.mkdir()
    (d / "project.json").write_text("{not json", encoding="utf-8")
    r = prun("infer", tmp_path, files, project=True)
    assert r.returncode == 1
    assert r.stderr.strip()
