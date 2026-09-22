"""Spec: New Subcommands / `search`."""


def found(result):
    return [item["name"] for item in result.definitions]


# Spec: "Search for names matching `<query>` across the project. Returns
# definitions (not usages)."
def test_definitions_are_returned_not_usages(search):
    result = search("helper", {"a.py": "def helper():\n    pass\n", "b.py": "helper()\n"})
    assert result.code == 0
    assert [(item["name"], item["module_path"], item["line"]) for item in result.definitions] == [
        ("helper", "a.py", 1)
    ]


# Spec: "Each result has the same fields as a definition object (from
# `infer`/`goto`), minus `docstring`."
def test_result_fields(search):
    result = search("helper", {"a.py": 'def helper():\n    """Doc."""\n'})
    assert result.definitions[0] == {
        "name": "helper",
        "type": "function",
        "full_name": "a.helper",
        "module_path": "a.py",
        "line": 1,
        "column": 4,
        "description": "def helper()",
    }


# Spec: "Match is by substring, case-insensitive: query `calc` matches
# `Calculator`, `recalculate`."
def test_substring_match_is_case_insensitive(search):
    files = {"a.py": "class Calculator:\n    pass\n", "b.py": "def recalculate():\n    pass\n"}
    assert found(search("calc", files)) == ["Calculator", "recalculate"]


# Spec: "Search all `def`, `class`, and top-level assignment names across
# project files."
def test_functions_classes_and_assignments_are_searched(search):
    files = {"a.py": "LIMIT_TOKEN = 1\n\ndef limit_token():\n    pass\n\nclass LimitToken:\n    pass\n"}
    assert found(search("limit", files)) == ["LIMIT_TOKEN", "limit_token", "LimitToken"]


def test_methods_are_searched(search):
    files = {"a.py": "class Widget:\n    def resize(self):\n        pass\n"}
    assert found(search("resize", files)) == ["resize"]


# Spec: "Do not search inside function/method bodies (local variables are not
# searchable)."
def test_local_variables_are_not_searchable(search):
    files = {"a.py": "def run():\n    hidden_value = 1\n    return hidden_value\n"}
    assert found(search("hidden_value", files)) == []


# Spec: "Sort by: exact match first, then prefix match, then substring match."
def test_exact_prefix_then_substring(search):
    files = {
        "a.py": "def alpha_calc():\n    pass\n",
        "b.py": "def calc():\n    pass\n",
        "c.py": "def calculate():\n    pass\n",
    }
    assert found(search("calc", files)) == ["calc", "calculate", "alpha_calc"]


# Spec: "Within each group, sort by `(module_path, line)`."
def test_ties_are_broken_by_path_and_line(search):
    files = {
        "b.py": "def calc_one():\n    pass\n",
        "a.py": "def calc_two():\n    pass\n\ndef calc_three():\n    pass\n",
    }
    assert [(item["module_path"], item["line"]) for item in search("calc", files).definitions] == [
        ("a.py", 1),
        ("a.py", 4),
        ("b.py", 1),
    ]


def test_query_matching_nothing_is_empty(search):
    assert search("nothing_here", {"a.py": "value = 1\n"}).definitions == []
