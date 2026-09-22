"""Tests for the cross-file import-resolution extension of the spec.

Every test names the spec phrase it pins down; where the spec leaves a choice
open the matching AMBIGUITIES.md entry (T39+) is referenced.
"""

import json
import sys

import pytest

from conftest import (assert_ordering, find, make_project, names, one, pcomplete,
                      pdefs, pgoto, pinfer, prun, run_raw, split_cursor, write)


def kinds(comps, name):
    c = find(comps, name)
    return None if c is None else c["type"]


# =====================================================================
# Project Root
# =====================================================================

# Spec: "All commands now accept an optional `--project <dir>` flag."
@pytest.mark.parametrize("cmd", ["complete", "infer", "goto"])
def test_all_commands_accept_project_flag(tmp_path, cmd):
    files = {"pkg/__init__.py": "", "pkg/main.py": "x = 1\nx<|>\n"}
    r = prun(cmd, tmp_path, files, project=True)
    assert r.returncode == 0, "stderr=%r" % r.stderr
    payload = json.loads(r.stdout)
    assert ("completions" if cmd == "complete" else "definitions") in payload


# Spec: "All commands now accept an optional `--project <dir>` flag."
# Context: the `--project=<dir>` spelling is accepted too.
def test_project_flag_equals_spelling(tmp_path):
    files = {"pkg/__init__.py": "", "pkg/main.py": "x = 1\nx<|>\n"}
    path = tmp_path / "pkg" / "main.py"
    make_project(tmp_path, {"pkg/__init__.py": "", "pkg/main.py": "x = 1\nx\n"})
    r = run_raw(["goto", str(path), "2", "0", "--project=%s" % tmp_path])
    assert r.returncode == 0, "stderr=%r" % r.stderr


# Spec: "When provided, the project root is `<dir>`."
# Context: module_path is then relative to that root, not to the file's folder.
def test_project_root_sets_module_path_base(tmp_path):
    files = {"pkg/__init__.py": "",
             "pkg/mod.py": "class Thing:\n    pass\n",
             "pkg/main.py": "from pkg.mod import Thing\nThi<|>ng\n"}
    d = one(pinfer(tmp_path, files, project=True))
    assert d["module_path"] == "pkg/mod.py"


# Spec: "When omitted, the project root is the directory containing `<file>`."
def test_project_root_defaults_to_file_directory(tmp_path):
    files = {"lib.py": "class Thing:\n    pass\n",
             "main.py": "from lib import Thing\nThi<|>ng\n"}
    d = one(pinfer(tmp_path, files))
    assert d["module_path"] == "lib.py" and d["full_name"] == "lib.Thing"


# Spec: "The project root determines: Where to search for modules when
#        resolving imports."
def test_project_root_is_the_module_search_base(tmp_path):
    files = {"lib.py": "class Thing:\n    pass\n",
             "pkg/__init__.py": "",
             "pkg/main.py": "import lib\nl<|>ib.Thing\n"}
    # With the root at tmp_path, `lib` is found; the search does not start from
    # the importing file's own directory.
    d = one(pinfer(tmp_path, files, project=True))
    assert d["type"] == "module" and d["module_path"] == "lib.py"


# Spec: "Where to search for modules when resolving imports."
# Context: a sibling of the importing file is NOT found when the root is elsewhere.
def test_sibling_is_not_searched_when_root_is_above(tmp_path):
    files = {"pkg/__init__.py": "",
             "pkg/sibling.py": "class Thing:\n    pass\n",
             "pkg/main.py": "import sibling\nsibling.Thi<|>ng\n"}
    assert pinfer(tmp_path, files, project=True) == []


# Spec: "The base for computing module qualified names."
def test_qualified_name_uses_dotted_path_from_root(tmp_path):
    files = {"pkg/__init__.py": "",
             "pkg/sub/__init__.py": "",
             "pkg/sub/mod.py": "class Thing:\n    pass\n",
             "main.py": "from pkg.sub.mod import Thing\nThi<|>ng\n"}
    d = one(pinfer(tmp_path, files, project=True))
    assert d["full_name"] == "pkg.sub.mod.Thing"
    assert d["module_path"] == "pkg/sub/mod.py"


# Spec: "The base for computing module qualified names." Context: a package's
# `__init__.py` is qualified by the package name alone (T45).
def test_package_init_qualified_name(tmp_path):
    files = {"pkg/__init__.py": "class Thing:\n    pass\n",
             "main.py": "from pkg import Thing\nThi<|>ng\n"}
    d = one(pinfer(tmp_path, files, project=True))
    assert d["full_name"] == "pkg.Thing"
    assert d["module_path"] == "pkg/__init__.py"


# =====================================================================
# Import Resolution -- absolute imports
# =====================================================================

# Spec: "Project root -- scan for `.py` files ..."
def test_absolute_import_of_top_level_module(tmp_path):
    files = {"lib.py": "def helper():\n    pass\n",
             "main.py": "from lib import helper\nhelp<|>er\n"}
    d = one(pinfer(tmp_path, files))
    assert (d["type"], d["line"], d["module_path"]) == ("function", 1, "lib.py")


# Spec: "... and packages (directories containing `__init__.py`)."
def test_absolute_import_of_package(tmp_path):
    files = {"pkg/__init__.py": "def helper():\n    pass\n",
             "main.py": "import pkg\npkg.help<|>er\n"}
    d = one(pinfer(tmp_path, files))
    assert d["type"] == "function" and d["module_path"] == "pkg/__init__.py"


# Spec: "... and packages (directories containing `__init__.py`)."
# Context: a dotted submodule import.
def test_absolute_import_of_submodule(tmp_path):
    files = {"pkg/__init__.py": "",
             "pkg/mod.py": "class Thing:\n    pass\n",
             "main.py": "import pkg.mod\npkg.mod.Thi<|>ng\n"}
    d = one(pinfer(tmp_path, files))
    assert d["type"] == "class" and d["module_path"] == "pkg/mod.py"


# Spec: "Standard library -- recognize stdlib modules available in the target runtime."
def test_stdlib_module_is_recognized(tmp_path):
    files = {"main.py": "import json\njson.du<|>mps\n"}
    d = one(pinfer(tmp_path, files))
    assert d["name"] == "dumps"


# Spec: search order -- "1. Project root ... 2. Standard library".
# Context: a project module shadows a stdlib module of the same name.
def test_project_module_shadows_stdlib(tmp_path):
    files = {"json.py": "def project_only():\n    pass\n",
             "main.py": "import json\njson.project_o<|>nly\n"}
    d = one(pinfer(tmp_path, files))
    assert d["type"] == "function" and d["module_path"] == "json.py"


# Spec: "If a module cannot be found, treat it as unresolvable -- `infer` ...
#        return empty results".
def test_unresolvable_module_infer_is_empty(tmp_path):
    files = {"main.py": "from no_such_module_xyz import thing\nthi<|>ng\n"}
    assert pinfer(tmp_path, files) == []


# Spec: "... `goto` return empty results" -- with --follow-imports the import
# site is the documented fallback, so the empty result is the attribute case.
def test_unresolvable_module_attribute_goto_is_empty(tmp_path):
    files = {"main.py": "import no_such_module_xyz\nno_such_module_xyz.th<|>ing\n"}
    assert pgoto(tmp_path, files) == []


# Spec: "completions return nothing for that module's attributes."
def test_unresolvable_module_attribute_completion_is_empty(tmp_path):
    files = {"main.py": "import no_such_module_xyz\nno_such_module_xyz.<|>\n"}
    assert pcomplete(tmp_path, files) == []


# =====================================================================
# Import Resolution -- relative imports
# =====================================================================

# Spec: relative imports resolve within the project. Context: `from . import mod`.
def test_relative_import_of_sibling_module(tmp_path):
    files = {"pkg/__init__.py": "",
             "pkg/mod.py": "class Thing:\n    pass\n",
             "pkg/main.py": "from . import mod\nmod.Thi<|>ng\n"}
    d = one(pinfer(tmp_path, files, project=True))
    assert d["type"] == "class" and d["module_path"] == "pkg/mod.py"


# Spec: relative imports resolve within the project. Context: `from .mod import X`.
def test_relative_import_of_name(tmp_path):
    files = {"pkg/__init__.py": "",
             "pkg/mod.py": "class Thing:\n    pass\n",
             "pkg/main.py": "from .mod import Thing\nThi<|>ng\n"}
    d = one(pinfer(tmp_path, files, project=True))
    assert d["full_name"] == "pkg.mod.Thing"


# Spec: relative imports resolve within the project. Context: two dots leave the
# subpackage for its parent.
def test_relative_import_two_levels_up(tmp_path):
    files = {"pkg/__init__.py": "",
             "pkg/top.py": "class Thing:\n    pass\n",
             "pkg/sub/__init__.py": "",
             "pkg/sub/main.py": "from ..top import Thing\nThi<|>ng\n"}
    d = one(pinfer(tmp_path, files, project=True))
    assert d["module_path"] == "pkg/top.py"


# Spec: "If the relative import goes above the project root, it is unresolvable."
def test_relative_import_above_root_is_unresolvable(tmp_path):
    files = {"outside.py": "class Thing:\n    pass\n",
             "pkg/__init__.py": "",
             "pkg/main.py": "from ..outside import Thing\nThi<|>ng\n"}
    assert pinfer(tmp_path, files, project="pkg") == []


# Spec: "If the relative import goes above the project root, it is unresolvable."
# Context: a single dot at the root itself still resolves.
def test_single_dot_at_root_resolves(tmp_path):
    files = {"lib.py": "class Thing:\n    pass\n",
             "main.py": "from .lib import Thing\nThi<|>ng\n"}
    d = one(pinfer(tmp_path, files))
    assert d["module_path"] == "lib.py"


# =====================================================================
# Star imports
# =====================================================================

# Spec: "Makes all public names from `foo` visible in the importing module."
def test_star_import_makes_public_names_visible(tmp_path):
    files = {"lib.py": "def helper():\n    pass\n\n\nCONST = 1\n",
             "main.py": "from lib import *\nhelp<|>\n"}
    comps = pcomplete(tmp_path, files)
    assert "helper" in names(comps) and kinds(comps, "helper") == "function"


# Spec: "A name is public if: ... Otherwise: all names that do not start with `_`."
def test_star_import_excludes_underscore_names(tmp_path):
    files = {"lib.py": "def helper():\n    pass\n\n\ndef _hidden():\n    pass\n",
             "main.py": "from lib import *\n_hi<|>\n"}
    assert "_hidden" not in names(pcomplete(tmp_path, files))


# Spec: "The module defines `__all__`: use exactly those names."
def test_star_import_uses_dunder_all(tmp_path):
    files = {"lib.py": ("__all__ = ['kept']\n\n\ndef kept():\n    pass\n\n\n"
                        "def dropped():\n    pass\n"),
             "main.py": "from lib import *\nd<|>\n"}
    assert "dropped" not in names(pcomplete(tmp_path, files))


# Spec: "The module defines `__all__`: use exactly those names."
# Context: an underscore name listed in __all__ IS public.
def test_dunder_all_can_export_underscore_name(tmp_path):
    files = {"lib.py": "__all__ = ['_special']\n\n\ndef _special():\n    pass\n",
             "main.py": "from lib import *\n_spec<|>\n"}
    assert "_special" in names(pcomplete(tmp_path, files))


# Spec: "Makes all public names from `foo` visible in the importing module."
# Context: the star-imported name resolves for `infer` too.
def test_star_imported_name_infers_across_files(tmp_path):
    files = {"lib.py": "class Thing:\n    pass\n",
             "main.py": "from lib import *\nt = Thing()\nt<|>\n"}
    d = one(pinfer(tmp_path, files))
    assert d["type"] == "instance" and d["name"] == "Thing"


# =====================================================================
# `goto` -- --follow-imports
# =====================================================================

# Spec: "python sith.py goto <file> <line> <col> [--follow-imports]"
def test_follow_imports_flag_is_accepted(tmp_path):
    files = {"lib.py": "class Thing:\n    pass\n",
             "main.py": "from lib import Thing\nThi<|>ng\n"}
    r = prun("goto", tmp_path, files, extra=["--follow-imports"])
    assert r.returncode == 0, "stderr=%r" % r.stderr


# Spec: "Without `--follow-imports` (default), `goto` on an imported name returns
#        the `import` statement itself".
def test_goto_without_follow_returns_import_statement(tmp_path):
    files = {"lib.py": "class Thing:\n    pass\n",
             "main.py": "from lib import Thing\nThi<|>ng\n"}
    d = one(pgoto(tmp_path, files))
    assert (d["module_path"], d["line"]) == ("main.py", 1)
    assert d["description"] == "from lib import Thing"


# Spec: "Without `--follow-imports` (default) ..." Context: plain `import x`.
def test_goto_without_follow_on_module_name(tmp_path):
    files = {"lib.py": "class Thing:\n    pass\n",
             "main.py": "import lib\nl<|>ib\n"}
    d = one(pgoto(tmp_path, files))
    assert (d["module_path"], d["line"], d["description"]) == ("main.py", 1, "import lib")


# Spec: "With `--follow-imports`, `goto` follows the import chain and returns the
#        actual definition in the source module".
def test_goto_with_follow_returns_definition_in_source_module(tmp_path):
    files = {"lib.py": "class Thing:\n    pass\n",
             "main.py": "from lib import Thing\nThi<|>ng\n"}
    d = one(pgoto(tmp_path, files, extra=["--follow-imports"]))
    assert (d["module_path"], d["line"], d["column"]) == ("lib.py", 1, 6)
    assert d["type"] == "class" and d["full_name"] == "lib.Thing"


# Spec: "With `--follow-imports` ..." Context: a function, and a file offset.
def test_goto_with_follow_to_function(tmp_path):
    files = {"lib.py": "X = 1\n\n\ndef helper():\n    pass\n",
             "main.py": "from lib import helper\nhelp<|>er()\n"}
    d = one(pgoto(tmp_path, files, extra=["--follow-imports"]))
    assert (d["type"], d["line"], d["column"]) == ("function", 4, 4)


# Spec: "With `--follow-imports` ..." Context: an aliased import.
def test_goto_with_follow_through_alias(tmp_path):
    files = {"lib.py": "class Thing:\n    pass\n",
             "main.py": "from lib import Thing as T\nT<|>\n"}
    d = one(pgoto(tmp_path, files, extra=["--follow-imports"]))
    assert (d["name"], d["module_path"], d["line"]) == ("Thing", "lib.py", 1)


# Spec: "`--follow-imports` follows the import chain to the final definition."
# Context: a re-export chain main -> mid -> base.
def test_follow_imports_traverses_reexport_chain(tmp_path):
    files = {"base.py": "class Thing:\n    pass\n",
             "mid.py": "from base import Thing\n",
             "main.py": "from mid import Thing\nThi<|>ng\n"}
    d = one(pgoto(tmp_path, files, extra=["--follow-imports"]))
    assert (d["module_path"], d["line"]) == ("base.py", 1)


# Spec: "`--follow-imports` follows the import chain to the final definition."
# Context: a star-import re-export in the middle of the chain.
def test_follow_imports_through_star_reexport(tmp_path):
    files = {"base.py": "def helper():\n    pass\n",
             "mid.py": "from base import *\n",
             "main.py": "from mid import helper\nhelp<|>er\n"}
    d = one(pgoto(tmp_path, files, extra=["--follow-imports"]))
    assert (d["module_path"], d["line"], d["type"]) == ("base.py", 1, "function")


# Spec: "With `--follow-imports`, ... returns the actual definition in the source
#        module" -- context: `import pkg.mod` then goto on the module name.
def test_follow_imports_on_module_name_returns_module_definition(tmp_path):
    files = {"lib.py": "class Thing:\n    pass\n",
             "main.py": "import lib\nl<|>ib\n"}
    d = one(pgoto(tmp_path, files, extra=["--follow-imports"]))
    assert d["type"] == "module" and d["module_path"] == "lib.py"


# Spec: "If the import chain leads to a module that cannot be found (e.g.,
#        third-party or stdlib), return the import statement as a fallback."
def test_follow_imports_falls_back_for_stdlib(tmp_path):
    files = {"main.py": "from os import getcwd\ngetc<|>wd\n"}
    d = one(pgoto(tmp_path, files, extra=["--follow-imports"]))
    assert (d["module_path"], d["line"]) == ("main.py", 1)
    assert d["description"] == "from os import getcwd"


# Spec: "If the import chain leads to a module that cannot be found ..."
# Context: a module that does not exist at all.
def test_follow_imports_falls_back_for_missing_module(tmp_path):
    files = {"main.py": "from no_such_module_xyz import thing\nthi<|>ng\n"}
    d = one(pgoto(tmp_path, files, extra=["--follow-imports"]))
    assert (d["module_path"], d["line"]) == ("main.py", 1)


# Spec clarification: "With `--follow-imports`, if the terminal target cannot be
# resolved, return the import site in the current file as the fallback definition."
# Context: the module resolves but does not define the imported name.
def test_follow_imports_falls_back_when_name_missing_in_module(tmp_path):
    files = {"lib.py": "X = 1\n",
             "main.py": "from lib import absent\nabse<|>nt\n"}
    d = one(pgoto(tmp_path, files, extra=["--follow-imports"]))
    assert (d["module_path"], d["line"]) == ("main.py", 1)
    assert d["name"] == "absent"


# Spec: "--follow-imports follows the import chain" -- context: a local (non
# imported) name is unaffected by the flag.
def test_follow_imports_leaves_local_names_alone(tmp_path):
    files = {"main.py": "def helper():\n    pass\n\n\nhelp<|>er()\n"}
    plain = one(pgoto(tmp_path, files))
    files = {"main.py": "def helper():\n    pass\n\n\nhelp<|>er()\n"}
    followed = one(pgoto(tmp_path, files, extra=["--follow-imports"]))
    assert plain == followed


# =====================================================================
# `infer` across files
# =====================================================================

# Spec: "`infer` now follows imports to resolve types across files."
def test_infer_follows_import_to_class(tmp_path):
    files = {"lib.py": "class Thing:\n    pass\n",
             "main.py": "from lib import Thing\nt = Thing()\nt<|>\n"}
    d = one(pinfer(tmp_path, files))
    assert d["type"] == "instance" and d["full_name"] == "lib.Thing"


# Spec: "`infer` now follows imports to resolve types across files."
# Context: the return type of an imported function.
def test_infer_follows_imported_function_return_type(tmp_path):
    files = {"lib.py": "class Thing:\n    pass\n\n\ndef make():\n    return Thing()\n",
             "main.py": "from lib import make\nv = make()\nv<|>\n"}
    d = one(pinfer(tmp_path, files))
    assert d["type"] == "instance" and d["name"] == "Thing"


# Spec: "`infer` now follows imports to resolve types across files."
# Context: through two files (main -> mid -> base).
def test_infer_across_two_hops(tmp_path):
    files = {"base.py": "class Thing:\n    pass\n",
             "mid.py": "from base import Thing\n",
             "main.py": "from mid import Thing\nt = Thing()\nt<|>\n"}
    d = one(pinfer(tmp_path, files))
    assert d["module_path"] == "base.py" and d["type"] == "instance"


# Spec: "`infer` now follows imports to resolve types across files."
# Context: an attribute of an instance of an imported class.
def test_infer_attribute_of_imported_class_instance(tmp_path):
    files = {"lib.py": "class Thing:\n    def __init__(self):\n        self.count = 0\n",
             "main.py": "from lib import Thing\nt = Thing()\nt.cou<|>nt\n"}
    d = one(pinfer(tmp_path, files))
    assert d["full_name"] == "builtins.int"


# =====================================================================
# `complete` -- import context
# =====================================================================

# Spec: "`import ...` suggests top-level module/package names."
def test_import_completes_project_module(tmp_path):
    files = {"alpha.py": "", "beta.py": "",
             "main.py": "import al<|>\n"}
    comps = pcomplete(tmp_path, files)
    assert "alpha" in names(comps) and "beta" not in names(comps)


# Spec: "`import ...` suggests top-level module/package names."
# Context: packages (directories with __init__.py) are suggested too.
def test_import_completes_package(tmp_path):
    files = {"mypkg/__init__.py": "", "main.py": "import myp<|>\n"}
    comps = pcomplete(tmp_path, files)
    assert "mypkg" in names(comps) and kinds(comps, "mypkg") == "module"


# Spec: "`import ...` suggests top-level module/package names."
# Context: stdlib names are top-level modules too (T41).
def test_import_completes_stdlib_module(tmp_path):
    files = {"main.py": "import js<|>\n"}
    assert "json" in names(pcomplete(tmp_path, files))


# Spec: "`import |` suggests top-level module/package names."
def test_import_empty_prefix_lists_modules(tmp_path):
    files = {"alpha.py": "", "mypkg/__init__.py": "", "main.py": "import <|>\n"}
    got = names(pcomplete(tmp_path, files))
    assert "alpha" in got and "mypkg" in got


# Spec: "`import |` suggests top-level module/package names."
# Context: local names of the current file are not module names.
def test_import_context_does_not_offer_local_names(tmp_path):
    files = {"main.py": "alpha_local = 1\nimport alph<|>\n"}
    assert "alpha_local" not in names(pcomplete(tmp_path, files))


# Spec: "`from X import ...` suggests names inside module `X`."
def test_from_import_suggests_module_members(tmp_path):
    files = {"lib.py": "def helper():\n    pass\n\n\nclass Thing:\n    pass\n",
             "main.py": "from lib import he<|>\n"}
    comps = pcomplete(tmp_path, files)
    assert "helper" in names(comps) and kinds(comps, "helper") == "function"


# Spec: "`from X import |` suggests names inside module `X`."
def test_from_import_empty_prefix(tmp_path):
    files = {"lib.py": "def helper():\n    pass\n\n\nclass Thing:\n    pass\n",
             "main.py": "from lib import <|>\n"}
    got = names(pcomplete(tmp_path, files))
    assert "helper" in got and "Thing" in got


# Spec: "`from X.Y import ...` suggests names inside submodule `X.Y`."
def test_from_dotted_import_suggests_submodule_members(tmp_path):
    files = {"pkg/__init__.py": "", "pkg/mod.py": "def deep():\n    pass\n",
             "main.py": "from pkg.mod import de<|>\n"}
    assert "deep" in names(pcomplete(tmp_path, files))


# Spec: "`from X.Y import |` suggests names inside submodule `X.Y`."
def test_from_dotted_import_empty_prefix(tmp_path):
    files = {"pkg/__init__.py": "", "pkg/mod.py": "def deep():\n    pass\n",
             "main.py": "from pkg.mod import <|>\n"}
    assert "deep" in names(pcomplete(tmp_path, files))


# Spec clarification: "In `from X import ...` completion, exported names come from
# `__all__` when it exists".
def test_from_import_completion_honours_dunder_all(tmp_path):
    files = {"lib.py": ("__all__ = ['kept']\n\n\ndef kept():\n    pass\n\n\n"
                        "def dropped():\n    pass\n"),
             "main.py": "from lib import <|>\n"}
    got = names(pcomplete(tmp_path, files))
    assert "kept" in got and "dropped" not in got


# Spec clarification: "... otherwise use names that do not start with `_`."
def test_from_import_completion_hides_underscore_names(tmp_path):
    files = {"lib.py": "def kept():\n    pass\n\n\ndef _hidden():\n    pass\n",
             "main.py": "from lib import <|>\n"}
    got = names(pcomplete(tmp_path, files))
    assert "kept" in got and "_hidden" not in got


# Spec: "`from X import |` suggests names inside module `X`." Context: a package
# offers its submodules as importable names (T42).
def test_from_package_import_offers_submodules(tmp_path):
    files = {"pkg/__init__.py": "", "pkg/mod.py": "",
             "main.py": "from pkg import <|>\n"}
    assert "mod" in names(pcomplete(tmp_path, files))


# Spec: "`from X import ...` suggests names inside module `X`." Context: a stdlib
# module as X.
def test_from_stdlib_import_completion(tmp_path):
    files = {"main.py": "from json import dum<|>\n"}
    assert "dumps" in names(pcomplete(tmp_path, files))


# Spec: "`from X import ...`" Context: a relative module reference (T44).
def test_from_relative_import_completion(tmp_path):
    files = {"pkg/__init__.py": "", "pkg/mod.py": "def deep():\n    pass\n",
             "pkg/main.py": "from .mod import de<|>\n"}
    assert "deep" in names(pcomplete(tmp_path, files, project=True))


# Spec: "`from X import ...`" Context: completion after a comma in a name list (T44).
def test_from_import_completion_after_comma(tmp_path):
    files = {"lib.py": "def alpha():\n    pass\n\n\ndef beta():\n    pass\n",
             "main.py": "from lib import alpha, be<|>\n"}
    assert "beta" in names(pcomplete(tmp_path, files))


# Spec: "Import completions use the same ordering rules (public -> private ->
#        dunder) ... as name completions."
def test_import_completion_ordering(tmp_path):
    files = {"main.py": "import <|>\n"}
    comps = pcomplete(tmp_path, files)
    assert_ordering(comps)


# Spec: "Import completions use the same ... prefix matching as name completions."
def test_import_completion_prefix_matching(tmp_path):
    files = {"alpha.py": "", "beta.py": "", "main.py": "import be<|>\n"}
    got = names(pcomplete(tmp_path, files))
    assert got and all(n.lower().startswith("be") for n in got)


# Spec: "Import completions use the same ... prefix matching as name completions."
# Context: `complete` holds the remaining characters.
def test_import_completion_complete_field(tmp_path):
    files = {"alpha.py": "", "main.py": "import alp<|>\n"}
    assert find(pcomplete(tmp_path, files), "alpha")["complete"] == "ha"


# Spec: "Import completions use the same ordering rules ... and prefix matching."
# Context: --fuzzy still applies in an import context.
def test_import_completion_fuzzy(tmp_path):
    files = {"alphabet.py": "", "main.py": "import apt<|>\n"}
    assert "alphabet" in names(pcomplete(tmp_path, files, extra=["--fuzzy"]))


# Spec: "`import ...` suggests top-level module/package names." Context: no
# keywords or builtins leak into an import context.
def test_import_context_has_no_keywords(tmp_path):
    files = {"alpha.py": "", "main.py": "import a<|>\n"}
    comps = pcomplete(tmp_path, files)
    assert [c for c in comps if c["type"] == "keyword"] == []


# =====================================================================
# `complete` -- cross-file attribute completion
# =====================================================================

# Spec: "Attribute completion now works for imported names."
def test_attribute_completion_on_imported_module(tmp_path):
    files = {"lib.py": "def helper():\n    pass\n\n\nclass Thing:\n    pass\n",
             "main.py": "import lib\nlib.<|>\n"}
    got = names(pcomplete(tmp_path, files))
    assert "helper" in got and "Thing" in got


# Spec: "Attribute completion now works for imported names."
# Context: an instance of a class imported from another module.
def test_attribute_completion_on_imported_class_instance(tmp_path):
    files = {"lib.py": ("class Thing:\n    def __init__(self):\n"
                        "        self.count = 0\n\n    def run(self):\n        pass\n"),
             "main.py": "from lib import Thing\nt = Thing()\nt.<|>\n"}
    got = names(pcomplete(tmp_path, files))
    assert "count" in got and "run" in got


# Spec: "Attribute completion now works for imported names."
# Context: a package attribute chain, pkg.mod.<attr>.
def test_attribute_completion_through_package(tmp_path):
    files = {"pkg/__init__.py": "", "pkg/mod.py": "def deep():\n    pass\n",
             "main.py": "import pkg.mod\npkg.mod.<|>\n"}
    assert "deep" in names(pcomplete(tmp_path, files))


# Spec: "Attribute completion now works for imported names."
# Context: a package exposes its submodules as attributes.
def test_package_attribute_lists_submodule(tmp_path):
    files = {"pkg/__init__.py": "", "pkg/mod.py": "",
             "main.py": "import pkg\npkg.<|>\n"}
    assert "mod" in names(pcomplete(tmp_path, files))


# Spec: "goto ... navigate to definitions in other modules." Context: goto on an
# attribute of an imported module lands in that module.
def test_goto_attribute_of_imported_module(tmp_path):
    files = {"lib.py": "def helper():\n    pass\n",
             "main.py": "import lib\nlib.help<|>er()\n"}
    d = one(pgoto(tmp_path, files))
    assert (d["module_path"], d["line"], d["type"]) == ("lib.py", 1, "function")


# =====================================================================
# Namespace packages
# =====================================================================

# Spec clarification: "The same import rules apply to regular packages and
# namespace packages."
def test_namespace_package_submodule_import(tmp_path):
    files = {"nspkg/mod.py": "class Thing:\n    pass\n",
             "main.py": "from nspkg.mod import Thing\nThi<|>ng\n"}
    d = one(pinfer(tmp_path, files))
    assert d["module_path"] == "nspkg/mod.py" and d["full_name"] == "nspkg.mod.Thing"


# Spec clarification: "The same import rules apply to regular packages and
# namespace packages." Context: import completion lists a namespace package.
def test_namespace_package_in_import_completion(tmp_path):
    files = {"nspkg/mod.py": "", "main.py": "import nsp<|>\n"}
    assert "nspkg" in names(pcomplete(tmp_path, files))


# Spec clarification: "The same import rules apply to regular packages and
# namespace packages." Context: `from nspkg import mod`.
def test_from_namespace_package_import_submodule(tmp_path):
    files = {"nspkg/mod.py": "def deep():\n    pass\n",
             "main.py": "from nspkg import mod\nmod.de<|>ep\n"}
    d = one(pinfer(tmp_path, files))
    assert d["type"] == "function" and d["module_path"] == "nspkg/mod.py"


# =====================================================================
# Path convention
# =====================================================================

# Spec: "All paths in output fields (`module_path`, ...) use forward-slash
#        separators (POSIX convention) regardless of the host operating system."
def test_module_path_uses_forward_slashes(tmp_path):
    files = {"pkg/__init__.py": "", "pkg/sub/__init__.py": "",
             "pkg/sub/mod.py": "class Thing:\n    pass\n",
             "main.py": "from pkg.sub.mod import Thing\nThi<|>ng\n"}
    d = one(pinfer(tmp_path, files, project=True))
    assert "\\" not in d["module_path"] and d["module_path"] == "pkg/sub/mod.py"


# =====================================================================
# Error handling
# =====================================================================

# Spec: "Circular imports: do not infinite-loop."
def test_circular_imports_terminate(tmp_path):
    files = {"a.py": "from b import beta\n\n\ndef alpha():\n    pass\n",
             "b.py": "from a import alpha\n\n\ndef beta():\n    pass\n",
             "main.py": "from a import alpha\nalp<|>ha\n"}
    r = prun("goto", tmp_path, files, extra=["--follow-imports"])
    assert r.returncode == 0, "stderr=%r" % r.stderr
    d = one(json.loads(r.stdout)["definitions"])
    assert (d["module_path"], d["line"]) == ("a.py", 4)


# Spec: "If module A imports B and B imports A, resolve what is available at the
#        point of the circular reference and move on."
def test_circular_import_resolves_available_names(tmp_path):
    files = {"a.py": "from b import beta\n\n\ndef alpha():\n    pass\n",
             "b.py": "from a import alpha\n\n\ndef beta():\n    pass\n",
             "main.py": "from b import alpha\nalp<|>ha\n"}
    d = one(pgoto(tmp_path, files, extra=["--follow-imports"]))
    assert d["module_path"] == "a.py" and d["type"] == "function"


# Spec: "Names not yet defined at the point of circular import are simply not
#        visible."
def test_circular_star_import_sees_only_earlier_names(tmp_path):
    # `a` is analysed first (its star import is eager), so when `b` reaches back
    # into `a` only the names above a's own `from b import *` line exist yet.
    files = {"a.py": "early = 1\nfrom b import *\nlate = 2\n",
             "b.py": "from a import *\n\n\ndef uses():\n    pass\n",
             "main.py": "from a import *\nimport b\nb.<|>\n"}
    got = names(pcomplete(tmp_path, files))
    assert "early" in got and "uses" in got and "late" not in got


# Spec: "Import of nonexistent module: not an error -- return empty results for
#        that module's names."
def test_nonexistent_module_is_not_an_error(tmp_path):
    files = {"main.py": "import no_such_module_xyz\nno_such_module_xyz<|>\n"}
    r = prun("infer", tmp_path, files)
    assert r.returncode == 0
    assert json.loads(r.stdout)["definitions"] == []


# Spec: "Import of nonexistent module: not an error" -- other names in the file
# still complete normally.
def test_nonexistent_module_does_not_break_file(tmp_path):
    files = {"main.py": "from no_such_module_xyz import thing\nlocal_x = 1\nloca<|>\n"}
    assert "local_x" in names(pcomplete(tmp_path, files))


# Spec: "Syntax errors in imported files: parse as much as possible (same
#        tolerance as the main file)."
def test_syntax_error_in_imported_file_is_tolerated(tmp_path):
    files = {"lib.py": "def helper():\n    pass\n\n\ndef broken(:\n    pass\n",
             "main.py": "from lib import helper\nhelp<|>er\n"}
    d = one(pgoto(tmp_path, files, extra=["--follow-imports"]))
    assert (d["module_path"], d["line"], d["type"]) == ("lib.py", 1, "function")


# Spec: "Syntax errors in imported files: parse as much as possible."
# Context: attribute completion on the broken module still works.
def test_syntax_error_in_imported_file_still_completes(tmp_path):
    files = {"lib.py": "def helper():\n    pass\n\n\nx = (\n",
             "main.py": "import lib\nlib.<|>\n"}
    assert "helper" in names(pcomplete(tmp_path, files))


# Spec clarification: "With `--follow-imports`, if the terminal target cannot be
# resolved, return the import site in the current file as the fallback
# definition." Context: the chain dead-ends one file away (T52).
def test_follow_imports_fallback_is_the_current_file(tmp_path):
    files = {"relib.py": "from os import getcwd\n",
             "main.py": "from relib import getcwd\ngetc<|>wd\n"}
    d = one(pgoto(tmp_path, files, extra=["--follow-imports"]))
    assert (d["module_path"], d["line"]) == ("main.py", 1)


# Spec: "`--follow-imports` follows the import chain to the final definition."
# Context: the final definition is an assignment, not a def/class.
def test_follow_imports_to_assignment(tmp_path):
    files = {"lib.py": "import os\nVALUE = 3\n",
             "main.py": "from lib import VALUE\nVAL<|>UE\n"}
    d = one(pgoto(tmp_path, files, extra=["--follow-imports"]))
    assert (d["module_path"], d["line"], d["type"]) == ("lib.py", 2, "statement")


# Spec: "`infer` now follows imports to resolve types across files."
# Context: an imported module-level constant.
def test_infer_imported_constant(tmp_path):
    files = {"lib.py": "VALUE = 3\n",
             "main.py": "from lib import VALUE\nVAL<|>UE\n"}
    assert one(pinfer(tmp_path, files))["full_name"] == "builtins.int"
