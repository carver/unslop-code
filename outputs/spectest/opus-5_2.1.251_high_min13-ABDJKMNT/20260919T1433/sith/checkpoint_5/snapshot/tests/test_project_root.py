"""Spec: the project root, set by `--project` or by the file's own directory."""

HELPER = "class Thing:\n    pass\n"


# Spec: "All commands now accept an optional `--project <dir>` flag."
def test_complete_accepts_the_project_flag(complete):
    result = complete("value = 1\nvalu$\n", project=".")
    assert result.code == 0
    assert "value" in result.names


def test_infer_accepts_the_project_flag(infer):
    assert infer("value = 1\nvalu$e\n", project=".").code == 0


def test_goto_accepts_the_project_flag(goto):
    assert goto("value = 1\nvalu$e\n", project=".").code == 0


# Spec: "When provided, the project root is `<dir>`" - a module beside the
# root resolves for a file that lives in a subdirectory.
def test_project_flag_sets_where_modules_are_searched(infer):
    result = infer(
        "import helper\nhelper.Thin$g\n",
        name="app/main.py",
        extra={"helper.py": HELPER},
        project=".",
    )
    assert result.only["module_path"] == "helper.py"


# Spec: "When omitted, the project root is the directory containing `<file>`."
def test_without_the_flag_the_root_is_the_files_directory(infer):
    result = infer(
        "import helper\nhelper.Thin$g\n",
        name="app/main.py",
        extra={"app/helper.py": HELPER},
    )
    assert result.only["module_path"] == "helper.py"


# Spec: a module that is only beside the project root is out of reach when the
# root is the file's own directory.
def test_without_the_flag_a_root_level_module_is_unreachable(infer):
    result = infer(
        "import helper\nhelper.Thin$g\n",
        name="app/main.py",
        extra={"helper.py": HELPER},
    )
    assert result.definitions == []


# Spec: "The project root determines ... The base for computing module
# qualified names."
def test_module_path_is_relative_to_the_project_root(infer):
    result = infer(
        "from app.helper import Thing\nThin$g\n",
        extra={"app/helper.py": HELPER, "app/__init__.py": ""},
        project=".",
    )
    assert result.only["module_path"] == "app/helper.py"


def test_full_name_is_built_from_the_project_root(infer):
    result = infer(
        "from app.helper import Thing\nThin$g\n",
        extra={"app/helper.py": HELPER, "app/__init__.py": ""},
        project=".",
    )
    assert result.only["full_name"] == "app.helper.Thing"


# Spec: "All paths in output fields (`module_path`, ...) use forward-slash
# separators (POSIX convention) regardless of the host operating system."
def test_paths_use_forward_slashes(infer):
    result = infer(
        "from deep.nested.helper import Thing\nThin$g\n",
        extra={"deep/nested/helper.py": HELPER},
        project=".",
    )
    assert result.only["module_path"] == "deep/nested/helper.py"
    assert "\\" not in result.only["module_path"]
