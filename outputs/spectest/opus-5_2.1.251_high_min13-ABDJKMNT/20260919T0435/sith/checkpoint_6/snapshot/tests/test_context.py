"""The `context` subcommand: the scopes the cursor sits inside."""


# "python sith.py context <file> <line> <col> [--project <dir>]"
def test_context_subcommand_accepts_file_line_col(context):
    assert context("x = 1\n|\n").returncode == 0


# "Return the scope context at the cursor position"
def test_payload_is_an_object_with_a_context_array(context):
    payload = context("x = 1\n|\n").payload
    assert list(payload) == ["context"]
    assert isinstance(payload["context"], list)


# "If the cursor is at module level, the array is empty."
def test_module_level_cursor_has_no_context(context):
    assert context("x = 1\n|\n").context == []


# "| `name` | string | Name of the scope (class name, function name). |"
# "| `type` | string | `\"class\"` or `\"function\"`. |"
# "| `line` | int | 1-based line of the scope's definition. |"
# "| `column` | int | 0-based column. |"
def test_function_scope_record(context):
    found = context("def run():\n    val|ue = 1\n").context
    assert found == [{"name": "run", "type": "function", "line": 1, "column": 0}]


def test_class_scope_record(context):
    found = context("class Widget:\n    size| = 1\n").context
    assert found == [{"name": "Widget", "type": "class", "line": 1, "column": 0}]


# "The `context` array is ordered from outermost to innermost scope."
def test_nested_scopes_run_outermost_first(context):
    source = "class Widget:\n    def render(self):\n        def inner():\n            |pass\n"
    assert [scope["name"] for scope in context(source).context] == ["Widget", "render", "inner"]


# "The first element is the outermost non-module scope."
def test_the_module_scope_is_not_reported(context):
    source = "def run():\n    |pass\n"
    assert [scope["type"] for scope in context(source).context] == ["function"]


# "1-based line of the scope's definition" / "0-based column"
def test_positions_are_those_of_the_definition_statement(context):
    source = "if True:\n\n    class Widget:\n        def render(self):\n            pa|ss\n"
    assert context(source).context == [
        {"name": "Widget", "type": "class", "line": 3, "column": 4},
        {"name": "render", "type": "function", "line": 4, "column": 8},
    ]


# A method of a class reports the class it belongs to as its outer scope.
def test_method_reports_its_class(context):
    source = "class Widget:\n    def render(self):\n        return sel|f\n"
    assert [scope["name"] for scope in context(source).context] == ["Widget", "render"]


# "[--project <dir>]"
def test_project_flag_is_accepted(context):
    result = context("def run():\n    |pass\n", name="pkg/app.py", files={"pkg/__init__.py": ""},
                     project=".")
    assert result.returncode == 0
    assert [scope["name"] for scope in result.context] == ["run"]


# The cursor resting on the definition line itself is already inside that scope.
def test_cursor_on_the_definition_line(context):
    source = "def ru|n():\n    pass\n"
    assert [scope["name"] for scope in context(source).context] == ["run"]
