"""Spec: Global Settings."""

from conftest import invoke, run_command, write_config, write_files, write_source

HELPER = "class Thing:\n    pass\n"


def at_cursor(command, tmp_path, source, *settings, extra=None, project=None):
    """Run a cursor command with `--setting` flags applied."""
    path, line, col = write_source(tmp_path, source, extra=extra)
    flags = [part for setting in settings for part in ("--setting", setting)]
    return invoke(command, path, line, col, flags=flags, project=project)


# Spec: "All commands accept zero or more `--setting key=value` flags to
# override default behavior"
def test_setting_is_accepted_by_complete(tmp_path):
    assert at_cursor("complete", tmp_path, "value = 1\nval$\n", "add_bracket=true").code == 0


def test_setting_is_accepted_by_names(tmp_path):
    path, _, _ = write_source(tmp_path, "value = 1$\n")
    assert run_command("names", path, flags=["--setting", "case_insensitive=false"]).code == 0


def test_setting_is_accepted_by_context(tmp_path):
    assert at_cursor("context", tmp_path, "def run():\n    pa$ss\n", "add_bracket=true").code == 0


def test_setting_is_accepted_by_search(tmp_path):
    write_files(tmp_path, {"a.py": "value = 1\n"})
    result = run_command(
        "search", "value", project=tmp_path, flags=["--setting", "dynamic_params=false"]
    )
    assert result.code == 0


def test_setting_is_accepted_by_env_list():
    assert run_command("env", "list", flags=["--setting", "smart_sys_path=false"]).code == 0


def test_several_settings_are_accepted(tmp_path):
    result = at_cursor(
        "complete", tmp_path, "value = 1\nval$\n", "add_bracket=true", "case_insensitive=false"
    )
    assert result.code == 0


# Spec: "`case_insensitive` | bool | true | Case-insensitive completion
# matching."
def test_case_insensitive_matching_is_on_by_default(complete):
    assert "Value" in complete("Value = 1\nval$\n").names


def test_case_insensitive_can_be_turned_off(tmp_path):
    result = at_cursor("complete", tmp_path, "Value = 1\nvalue2 = 2\nval$\n", "case_insensitive=false")
    assert result.names == ["value2"]


# Spec: "`add_bracket` | bool | false | Append `(` to function/class
# completions in the `complete` field."
def test_add_bracket_is_off_by_default(complete):
    assert complete("def run():\n    pass\nru$\n").by_name("run")["complete"] == "n"


def test_add_bracket_appends_to_a_function(tmp_path):
    result = at_cursor("complete", tmp_path, "def run():\n    pass\nru$\n", "add_bracket=true")
    assert result.by_name("run")["complete"] == "n("


def test_add_bracket_appends_to_a_class(tmp_path):
    result = at_cursor("complete", tmp_path, "class Widget:\n    pass\nWidg$\n", "add_bracket=true")
    assert result.by_name("Widget")["complete"] == "et("


def test_add_bracket_leaves_other_completions_alone(tmp_path):
    result = at_cursor("complete", tmp_path, "value = 1\nval$\n", "add_bracket=true")
    assert result.by_name("value")["complete"] == "ue"


# Spec: "`dynamic_params` | bool | true | Infer parameter types from call
# sites."
def test_dynamic_params_is_on_by_default(infer):
    assert infer("def apply(value):\n    val$ue\n\napply(3)\n").only["name"] == "int"


def test_dynamic_params_can_be_turned_off(tmp_path):
    source = "def apply(value):\n    val$ue\n\napply(3)\n"
    result = at_cursor("infer", tmp_path, source, "dynamic_params=false")
    assert result.definitions == []


# Spec: "`smart_sys_path` | bool | true | Auto-detect sys.path entries."
def test_smart_sys_path_is_on_by_default(infer):
    result = infer("import helper\nhelper.Thin$g\n", extra={"helper.py": HELPER}, project=".")
    assert result.only["module_path"] == "helper.py"


def test_smart_sys_path_can_be_turned_off(tmp_path):
    result = at_cursor(
        "infer", tmp_path, "import helper\nhelper.Thin$g\n",
        "smart_sys_path=false", extra={"helper.py": HELPER}, project=tmp_path,
    )
    assert result.definitions == []


# Spec: "Boolean settings accept `true`/`false` (case-insensitive)."
def test_boolean_values_are_case_insensitive(tmp_path):
    result = at_cursor("complete", tmp_path, "def run():\n    pass\nru$\n", "add_bracket=TRUE")
    assert result.by_name("run")["complete"] == "n("


def test_false_is_accepted_in_any_case(tmp_path):
    result = at_cursor("complete", tmp_path, "Value = 1\nval$\n", "case_insensitive=False")
    assert result.names == []


# Spec: "Invalid setting names or values: exit 1."
def test_an_unknown_setting_name_exits_one(tmp_path):
    result = at_cursor("complete", tmp_path, "val$\n", "unknown_setting=true")
    assert result.code == 1
    assert result.stderr.strip()


def test_an_invalid_boolean_value_exits_one(tmp_path):
    result = at_cursor("complete", tmp_path, "val$\n", "add_bracket=maybe")
    assert result.code == 1


def test_a_setting_without_a_value_exits_one(tmp_path):
    result = at_cursor("complete", tmp_path, "val$\n", "add_bracket")
    assert result.code == 1


# Spec: "Settings from `--setting` override project config, which overrides
# defaults."
def test_cli_setting_overrides_the_project_config(tmp_path):
    write_config(tmp_path, {"smart_sys_path": False})
    result = at_cursor(
        "infer", tmp_path, "import helper\nhelper.Thin$g\n",
        "smart_sys_path=true", extra={"helper.py": HELPER}, project=tmp_path,
    )
    assert result.only["module_path"] == "helper.py"


def test_the_project_config_overrides_the_default(tmp_path):
    write_config(tmp_path, {"smart_sys_path": False})
    result = at_cursor(
        "infer", tmp_path, "import helper\nhelper.Thin$g\n",
        extra={"helper.py": HELPER}, project=tmp_path,
    )
    assert result.definitions == []
