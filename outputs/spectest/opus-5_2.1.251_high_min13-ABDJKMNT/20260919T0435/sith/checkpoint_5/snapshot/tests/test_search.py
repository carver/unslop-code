"""`search`: project-wide lookup of the names a project defines."""


def paths_and_names(result):
    return [(d["module_path"], d["name"]) for d in result.definitions]


# "Search for names matching `<query>` across the project."
def test_finds_a_name_in_another_file(search):
    result = search("helper", {"tools.py": "def helper():\n    pass\n"}, project=".")
    assert paths_and_names(result) == [("tools.py", "helper")]


# "Returns definitions (not usages)."
def test_usages_are_not_returned(search):
    result = search("helper", {"tools.py": "def helper():\n    pass\n\nhelper()\n"},
                    project=".")
    assert len(result.definitions) == 1


# "Each result has the same fields as a definition object (from `infer`/`goto`),
#  minus `docstring`."
def test_result_fields(search):
    result = search("helper", {"tools.py": "def helper(a):\n    \"\"\"Doc.\"\"\"\n"},
                    project=".")
    assert result.definitions[0] == {
        "name": "helper",
        "type": "function",
        "full_name": "tools.helper",
        "module_path": "tools.py",
        "line": 1,
        "column": 4,
        "description": "def helper(a)",
    }


# "Match is by substring, case-insensitive: query `calc` matches `Calculator`,
#  `recalculate`."
def test_substring_match(search):
    files = {"tools.py": "class Calculator:\n    pass\n\ndef recalculate():\n    pass\n"}
    result = search("calc", files, project=".")
    assert [d["name"] for d in result.definitions] == ["Calculator", "recalculate"]


def test_match_is_case_insensitive(search):
    result = search("CALC", {"tools.py": "def calculate():\n    pass\n"}, project=".")
    assert [d["name"] for d in result.definitions] == ["calculate"]


# "Search all `def`, `class`, and top-level assignment names across project files."
def test_finds_classes(search):
    result = search("Box", {"tools.py": "class Box:\n    pass\n"}, project=".")
    assert [d["type"] for d in result.definitions] == ["class"]


def test_finds_top_level_assignments(search):
    result = search("LIMIT", {"tools.py": "LIMIT = 10\n"}, project=".")
    assert [d["name"] for d in result.definitions] == ["LIMIT"]


def test_finds_methods(search):
    files = {"tools.py": "class Box:\n    def pack(self):\n        pass\n"}
    result = search("pack", files, project=".")
    assert [d["full_name"] for d in result.definitions] == ["tools.Box.pack"]


# "Do not search inside function/method bodies (local variables are not
#  searchable)."
def test_locals_are_not_searchable(search):
    files = {"tools.py": "def run():\n    packed = 1\n    return packed\n"}
    result = search("packed", files, project=".")
    assert result.definitions == []


def test_nested_functions_are_not_searchable(search):
    files = {"tools.py": "def run():\n    def packer():\n        pass\n"}
    result = search("packer", files, project=".")
    assert result.definitions == []


# "Sort by: exact match first, then prefix match, then substring match."
def test_exact_match_comes_first(search):
    files = {"tools.py": "def recalc():\n    pass\n\ndef calc():\n    pass\n\n"
                         "def calculate():\n    pass\n"}
    result = search("calc", files, project=".")
    assert [d["name"] for d in result.definitions] == ["calc", "calculate", "recalc"]


# "Within each group, sort by `(module_path, line)`."
def test_ties_sort_by_path_then_line(search):
    files = {
        "beta.py": "def calc_two():\n    pass\n",
        "alpha.py": "def calc_one():\n    pass\n\ndef calc_three():\n    pass\n",
    }
    result = search("calc", files, project=".")
    assert paths_and_names(result) == [
        ("alpha.py", "calc_one"),
        ("alpha.py", "calc_three"),
        ("beta.py", "calc_two"),
    ]


# "across the project": files in packages are searched too.
def test_searches_subdirectories(search):
    files = {"pkg/__init__.py": "", "pkg/tool.py": "def calculate():\n    pass\n"}
    result = search("calc", files, project=".")
    assert paths_and_names(result) == [("pkg/tool.py", "calculate")]


def test_no_match_returns_nothing(search):
    result = search("zzz", {"tools.py": "def helper():\n    pass\n"}, project=".")
    assert result.definitions == []
