"""The global `--setting key=value` flag."""
from conftest import run_cli

WIDGET = 'class Widget:\n    """A widget."""\n'


# "All commands accept zero or more `--setting key=value` flags to override default
#  behavior"
def test_setting_flag_is_accepted_by_every_command(workdir, complete):
    assert complete("x = 1\nx|\n", settings=["case_insensitive=true"]).returncode == 0
    (workdir / "sample.py").write_text("x = 1\n", encoding="utf-8")
    for args in (
        ("names", str(workdir / "sample.py")),
        ("errors", str(workdir / "sample.py")),
        ("search", "x"),
        ("context", str(workdir / "sample.py"), "1", "0"),
        ("env", "list"),
        ("project", "init"),
    ):
        result = run_cli(*args, "--setting", "add_bracket=true", cwd=workdir)
        assert result.returncode == 0, result.stderr


def test_several_settings_can_be_given(complete):
    result = complete("x = 1\nx|\n", settings=["add_bracket=true", "case_insensitive=false"])
    assert result.returncode == 0


# "| `case_insensitive` | bool | true | Case-insensitive completion matching. |"
def test_case_insensitive_is_on_by_default(complete):
    assert "Value" in complete("Value = 1\nval|\n").names


def test_case_insensitive_false_requires_the_exact_case(complete):
    result = complete("Value = 1\nval|\n", settings=["case_insensitive=false"])
    assert "Value" not in result.names


def test_case_sensitive_matching_still_offers_an_exact_prefix(complete):
    result = complete("value = 1\nval|\n", settings=["case_insensitive=false"])
    assert "value" in result.names


# "| `dynamic_params` | bool | true | Infer parameter types from call sites. |"
def test_dynamic_params_is_on_by_default(infer):
    source = "def process(items):\n    return ite|ms\n\nprocess([1, 2])\n"
    assert infer(source).only["full_name"] == "builtins.list"


def test_dynamic_params_false_stops_reading_call_sites(infer):
    source = "def process(items):\n    return ite|ms\n\nprocess([1, 2])\n"
    assert infer(source, settings=["dynamic_params=false"]).definitions == []


# "| `smart_sys_path` | bool | true | Auto-detect sys.path entries. |"
def test_smart_sys_path_is_on_by_default(infer):
    source = "from helpers import Widget\nWid|get\n"
    assert infer(source, files={"helpers.py": WIDGET}, project=".").only["name"] == "Widget"


def test_smart_sys_path_false_stops_auto_detection(infer):
    source = "from helpers import Widget\nWid|get\n"
    result = infer(source, files={"helpers.py": WIDGET}, project=".",
                   settings=["smart_sys_path=false"])
    assert result.definitions == []


# "| `add_bracket` | bool | false | Append `(` to function/class completions in the
#  `complete` field. |"
def test_add_bracket_is_off_by_default(complete):
    assert complete("def helper():\n    pass\n\nhelp|\n").by_name("helper")["complete"] == "er"


def test_add_bracket_appends_to_a_function(complete):
    result = complete("def helper():\n    pass\n\nhelp|\n", settings=["add_bracket=true"])
    assert result.by_name("helper")["complete"] == "er("


def test_add_bracket_appends_to_a_class(complete):
    result = complete("class Widget:\n    pass\n\nWidg|\n", settings=["add_bracket=true"])
    assert result.by_name("Widget")["complete"] == "et("


def test_add_bracket_leaves_other_completions_alone(complete):
    result = complete("value = 1\nval|\n", settings=["add_bracket=true"])
    assert result.by_name("value")["complete"] == "ue"


def test_add_bracket_leaves_the_name_field_alone(complete):
    result = complete("def helper():\n    pass\n\nhelp|\n", settings=["add_bracket=true"])
    assert result.by_name("helper")["name"] == "helper"


# "Boolean settings accept `true`/`false` (case-insensitive)."
def test_boolean_values_are_case_insensitive(complete):
    assert complete("Value = 1\nval|\n", settings=["case_insensitive=FALSE"]).returncode == 0
    assert "Value" not in complete("Value = 1\nval|\n", settings=["case_insensitive=False"]).names
    assert "Value" in complete("Value = 1\nval|\n", settings=["case_insensitive=TRUE"]).names


# "Invalid setting names or values: exit 1."
def test_an_unknown_setting_name_exits_one(complete):
    result = complete("x|\n", settings=["no_such_setting=true"], expect_ok=False)
    assert result.returncode == 1
    assert result.stderr.strip() != ""


def test_an_invalid_boolean_value_exits_one(complete):
    result = complete("x|\n", settings=["add_bracket=yes"], expect_ok=False)
    assert result.returncode == 1


def test_a_setting_without_a_value_exits_one(complete):
    assert complete("x|\n", settings=["add_bracket"], expect_ok=False).returncode == 1


# "Settings from `--setting` override project config, which overrides defaults."
def test_setting_overrides_the_project_config(infer, project_config):
    project_config({"smart_sys_path": False})
    source = "from helpers import Widget\nWid|get\n"
    result = infer(source, files={"helpers.py": WIDGET}, project=".",
                   settings=["smart_sys_path=true"])
    assert result.only["name"] == "Widget"


def test_the_project_config_overrides_the_default(infer, project_config):
    project_config({"smart_sys_path": False})
    source = "from helpers import Widget\nWid|get\n"
    assert infer(source, files={"helpers.py": WIDGET}, project=".").definitions == []
