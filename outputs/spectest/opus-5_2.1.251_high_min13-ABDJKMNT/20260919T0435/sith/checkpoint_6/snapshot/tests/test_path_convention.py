"""Paths in output fields use forward slashes on every host."""
import os


# Spec: "All paths in output fields (`module_path`, ...) use forward-slash separators
#        (POSIX convention) regardless of the host operating system."
def test_module_path_of_a_nested_module_uses_slashes(infer):
    files = {"pkg/__init__.py": "", "pkg/tools.py": "class Widget:\n    pass\n"}
    definition = infer("from pkg.tools import Widget\nWid|get\n", files=files).only
    assert definition["module_path"] == "pkg/tools.py"
    assert "\\" not in definition["module_path"]


def test_module_path_of_the_analysed_file_uses_slashes(infer):
    files = {"pkg/__init__.py": ""}
    source = "class Widget:\n    pass\n\n\nw = Widget()\n|w\n"
    definition = infer(source, name="pkg/app.py", files=files, project=".").only
    assert definition["module_path"] == "pkg/app.py"


def test_every_returned_path_uses_slashes(infer):
    files = {"pkg/__init__.py": "", "pkg/deep/__init__.py": "",
             "pkg/deep/tools.py": "class Widget:\n    pass\n"}
    definition = infer("from pkg.deep.tools import Widget\nWid|get\n", files=files).only
    assert definition["module_path"] == "pkg/deep/tools.py"
    assert os.sep == "/" or "\\" not in definition["module_path"]
