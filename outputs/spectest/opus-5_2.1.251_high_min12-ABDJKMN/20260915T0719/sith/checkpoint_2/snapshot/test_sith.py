"""Tests derived phrase-by-phrase from the spec.

Each test carries a comment quoting the spec phrase (and the minimal context) it covers.
"""
import json
import subprocess
import sys

import pytest

from conftest import (assert_ordering, complete, find, group_rank, names, run,
                      run_raw, split_cursor, write)


# =====================================================================
# Deliverables / CLI
# =====================================================================

# Spec: "python sith.py complete <file> <line> <col> [--fuzzy]"
def test_cli_accepts_complete_subcommand(tmp_path):
    p = write(tmp_path, "x = 1\n")
    r = run(p, 1, 0)
    assert r.returncode == 0


# Spec: "python sith.py complete <file> <line> <col> [--fuzzy]" -- the --fuzzy flag is optional
def test_cli_accepts_fuzzy_flag(tmp_path):
    p = write(tmp_path, "x = 1\n")
    r = run(p, 1, 0, fuzzy=True)
    assert r.returncode == 0


# Spec: "Output is JSON to STDOUT -- a single JSON object with a `"completions"` array."
def test_output_is_object_with_completions_array(tmp_path):
    p = write(tmp_path, "value = 1\nva\n")
    r = run(p, 2, 2)
    data = json.loads(r.stdout)
    assert isinstance(data, dict)
    assert isinstance(data["completions"], list)


# Spec: "Compact format: no extra whitespace."
def test_output_is_compact_json(tmp_path):
    p = write(tmp_path, "value = 1\nva\n")
    r = run(p, 2, 2)
    data = json.loads(r.stdout)
    assert r.stdout.rstrip("\n") == json.dumps(data, separators=(",", ":"))


# Spec: "Newline-terminated."
def test_output_is_newline_terminated(tmp_path):
    p = write(tmp_path, "value = 1\nva\n")
    r = run(p, 2, 2)
    assert r.stdout.endswith("\n")
    assert not r.stdout.endswith("\n\n")


# Spec: "On success, exit 0 (even with zero completions)."
def test_zero_completions_still_exits_zero(tmp_path):
    comps = complete(tmp_path, "zzqqxx_nothing_matches<|>\n")
    assert comps == []


# Spec: "On error, print a message to STDERR and exit 1."
def test_error_writes_message_to_stderr_and_exits_one(tmp_path):
    r = run(tmp_path / "nope.py", 1, 0)
    assert r.returncode == 1
    assert r.stderr.strip() != ""
    assert r.stdout == ""


# =====================================================================
# Cursor Position
# =====================================================================

# Spec: "<line> is 1-based."
def test_line_is_one_based(tmp_path):
    src = "alpha = 1\nbeta = 2\n"
    p = write(tmp_path, src)
    r = run(p, 1, 0)
    assert r.returncode == 0
    got = names(json.loads(r.stdout)["completions"])
    # on line 1 only `alpha` (defined on line 1) is visible, not `beta`
    assert "alpha" in got and "beta" not in got


# Spec: "<col> is 0-based (number of characters before the cursor on that line)."
def test_col_is_zero_based_character_count(tmp_path):
    src = "alphabet = 1\nalp\n"
    p = write(tmp_path, src)
    r = run(p, 2, 3)  # 3 characters before the cursor => prefix "alp"
    comps = json.loads(r.stdout)["completions"]
    assert find(comps, "alphabet")["complete"] == "habet"


# Spec: "If the position is out of range (line exceeds file length ...), exit 1."
def test_line_beyond_end_of_file_exits_one(tmp_path):
    p = write(tmp_path, "x = 1\ny = 2\n")
    r = run(p, 99, 0)
    assert r.returncode == 1
    assert r.stderr.strip() != ""


# Spec: "If the position is out of range (... or column exceeds line length), exit 1."
def test_column_beyond_end_of_line_exits_one(tmp_path):
    p = write(tmp_path, "x = 1\n")
    r = run(p, 1, 99)
    assert r.returncode == 1
    assert r.stderr.strip() != ""


# Spec: "<col> is 0-based (number of characters before the cursor on that line)."
# Context: a column exactly equal to the line length is the end-of-line cursor, which is in range.
def test_column_equal_to_line_length_is_in_range(tmp_path):
    p = write(tmp_path, "x = 1\n")
    r = run(p, 1, 5)
    assert r.returncode == 0


# Spec: "<line> is 1-based." Context: line 0 (and negatives) cannot name a line.
def test_line_zero_exits_one(tmp_path):
    p = write(tmp_path, "x = 1\n")
    assert run(p, 0, 0).returncode == 1


# Spec: "If the position is out of range ... exit 1." Context: negative column.
def test_negative_column_exits_one(tmp_path):
    p = write(tmp_path, "x = 1\n")
    assert run(p, 1, -1).returncode == 1


# =====================================================================
# 1. Name Completion
# =====================================================================

# Spec: "When the cursor is in a position where a bare name is expected (not after a `.`),
#        return all names visible at that scope."
def test_bare_name_context_returns_visible_names(tmp_path):
    comps = complete(tmp_path, "alpha = 1\ndef beta():\n    pass\n<|>\n")
    got = names(comps)
    assert "alpha" in got and "beta" in got


# Spec: "Local scope -- names assigned or defined in the immediately enclosing function/method."
def test_local_scope_assignment_visible(tmp_path):
    comps = complete(tmp_path, "def f():\n    local_thing = 1\n    local<|>\n")
    assert "local_thing" in names(comps)


# Spec: "Local scope -- names assigned or defined in the immediately enclosing function/method."
# Context: a nested def is also a local name.
def test_local_scope_nested_def_visible(tmp_path):
    src = "def outer():\n    def helper():\n        pass\n    help<|>\n"
    comps = complete(tmp_path, src)
    assert find(comps, "helper")["type"] == "function"


# Spec: "Local scope" -- context: function parameters are local names.
def test_parameters_are_local_names(tmp_path):
    comps = complete(tmp_path, "def f(needle, other):\n    need<|>\n")
    assert find(comps, "needle") is not None


# Spec: "Local scope" -- context: names local to *another* function are not visible.
def test_names_from_sibling_function_not_visible(tmp_path):
    src = "def a():\n    secret = 1\n\ndef b():\n    sec<|>\n"
    assert names(complete(tmp_path, src)) == []


# Spec: "Enclosing scopes -- names from enclosing functions (for nested functions/closures)."
def test_enclosing_function_names_visible(tmp_path):
    src = "def outer():\n    captured = 1\n    def inner():\n        capt<|>\n"
    comps = complete(tmp_path, src)
    assert find(comps, "captured") is not None


# Spec: "Enclosing scopes -- names from enclosing functions"
# Context: the "defined before the cursor" rule is stated only "for the local and global scopes",
# so a closure sees enclosing names bound later in the enclosing function (T17).
def test_enclosing_names_defined_after_cursor_still_visible(tmp_path):
    src = "def outer():\n    def inner():\n        lat<|>\n    later_name = 5\n"
    assert "later_name" in names(complete(tmp_path, src))


# Spec: "Global scope -- names defined at module level (assignments, function defs, class defs, imports)."
def test_global_scope_sources(tmp_path):
    src = (
        "import os\n"
        "gvar = 1\n"
        "def gfunc():\n    pass\n"
        "class GClass:\n    pass\n"
        "def user():\n"
        "    g<|>\n"
    )
    got = names(complete(tmp_path, src))
    for expected in ("gvar", "gfunc", "GClass"):
        assert expected in got
    assert "os" in names(complete(tmp_path, src.replace("    g<|>", "    o<|>")))


# Spec: "Builtin scope -- builtin names provided by Python's `builtins` module."
def test_builtins_visible(tmp_path):
    got = names(complete(tmp_path, "pri<|>\n"))
    assert "print" in got


# Spec: "Builtin scope -- builtin names provided by Python's `builtins` module."
# Context: builtin classes too.
def test_builtin_classes_visible(tmp_path):
    comps = complete(tmp_path, "prop<|>\n")
    assert find(comps, "property")["type"] == "class"


# Spec: "Visible names come from these sources, checked in order: 1. Local scope ... 4. Builtin scope."
# Context: a local name shadows the builtin of the same name (one entry, the local one).
def test_local_shadows_builtin(tmp_path):
    src = "def f():\n    list = [1]\n    lis<|>\n"
    comps = [c for c in complete(tmp_path, src) if c["name"] == "list"]
    assert len(comps) == 1
    assert comps[0]["type"] == "instance"


# Spec: "A name is visible only if it is defined before the cursor position in the source
#        (for the local and global scopes)."
def test_global_name_defined_after_cursor_not_visible(tmp_path):
    src = "before_name = 1\n<|>\nafter_name = 2\n"
    got = names(complete(tmp_path, src))
    assert "before_name" in got
    assert "after_name" not in got


# Spec: "A name is visible only if it is defined before the cursor position ..." (local scope)
def test_local_name_defined_after_cursor_not_visible(tmp_path):
    src = "def f():\n    early = 1\n    e<|>\n    elate = 2\n"
    got = names(complete(tmp_path, src))
    assert "early" in got
    assert "elate" not in got


# Spec: "A `def` or `class` statement makes its name visible from the line of the `def`/`class` keyword."
def test_def_visible_from_its_own_line(tmp_path):
    src = "def recurse(n):\n    return recurse<|>\n"
    assert "recurse" in names(complete(tmp_path, src))


# Spec: "A `def` or `class` statement makes its name visible from the line of the `def`/`class` keyword."
# Context: on the def line itself (T3 -- inclusive).
def test_def_name_visible_on_the_def_line(tmp_path):
    src = "def target(<|>):\n    pass\n"
    assert "target" in names(complete(tmp_path, src))


# Spec: "A `def` or `class` statement makes its name visible from the line of the `class` keyword."
def test_class_visible_from_its_own_line(tmp_path):
    src = "class Thing:\n    pass\nTh<|>\n"
    assert find(complete(tmp_path, src), "Thing")["type"] == "class"


# Spec: "An assignment makes the name visible from the line of the assignment."
def test_assignment_visible_from_its_own_line(tmp_path):
    src = "spam = spam<|>\n"
    assert "spam" in names(complete(tmp_path, src))


# Spec: "If the cursor is partway through typing a name, the partially typed prefix filters completions."
def test_prefix_filters_completions(tmp_path):
    src = "apple = 1\nbanana = 2\nap<|>\n"
    got = names(complete(tmp_path, src))
    assert "apple" in got
    assert "banana" not in got


# Spec: "The prefix is determined by scanning backwards from the cursor to the start of the current identifier."
def test_prefix_scans_back_to_start_of_identifier(tmp_path):
    src = "apple = 1\nresult = apple + ap<|>\n"
    comps = complete(tmp_path, src)
    assert find(comps, "apple")["complete"] == "ple"


# Spec: "The prefix is determined by scanning backwards from the cursor to the start of the current identifier."
# Context: the cursor may sit in the middle of an existing word; text after the cursor is ignored.
def test_prefix_ignores_text_after_cursor(tmp_path):
    src = "apple = 1\nap<|>ricot\n"
    comps = complete(tmp_path, src)
    assert find(comps, "apple") is not None


# Spec: "The prefix is determined by scanning backwards ..." Context: a non-identifier char ends the scan.
def test_prefix_stops_at_non_identifier_character(tmp_path):
    src = "value = 1\nfoo(val<|>\n"
    comps = complete(tmp_path, src)
    assert find(comps, "value")["complete"] == "ue"


# =====================================================================
# 2. Attribute Completion
# =====================================================================

# Spec: "Modules -- if `foo` is an imported module, return the module's public names."
def test_module_attribute_completion(tmp_path):
    comps = complete(tmp_path, "import os\nos.<|>\n")
    got = names(comps)
    assert "getcwd" in got and "path" in got


# Spec: "A name is public if it does not start with `_`."
def test_module_attributes_exclude_underscore_names(tmp_path):
    comps = complete(tmp_path, "import os\nos.<|>\n")
    assert [n for n in names(comps) if n.startswith("_")] == []


# Spec: "Modules -- ... return the module's public names." Context: `import x as y`.
def test_module_alias_attribute_completion(tmp_path):
    comps = complete(tmp_path, "import os.path as osp\nosp.jo<|>\n")
    assert find(comps, "join") is not None


# Spec: "Modules -- ... return the module's public names." Context: dotted receiver expression.
def test_dotted_module_receiver(tmp_path):
    comps = complete(tmp_path, "import os\nos.path.jo<|>\n")
    assert find(comps, "join") is not None


# Spec: "Classes -- if `foo` is a class, return its methods and class attributes"
def test_class_attribute_completion(tmp_path):
    src = (
        "class Thing:\n"
        "    cattr = 1\n"
        "    def method(self):\n        pass\n"
        "Thing.<|>\n"
    )
    comps = complete(tmp_path, src)
    got = names(comps)
    assert "cattr" in got and "method" in got
    assert find(comps, "method")["type"] == "function"
    assert find(comps, "cattr")["type"] == "instance"


# Spec: "Classes -- ... (including inherited ones from base classes defined in the same file)."
def test_class_inherits_attributes_from_local_base(tmp_path):
    src = (
        "class Base:\n"
        "    base_attr = 1\n"
        "    def base_method(self):\n        pass\n"
        "class Kid(Base):\n"
        "    def kid_method(self):\n        pass\n"
        "Kid.<|>\n"
    )
    got = names(complete(tmp_path, src))
    assert "base_attr" in got and "base_method" in got and "kid_method" in got


# Spec: "Instances -- if `foo` is an instance (from `foo = MyClass()`), return the same attributes as the class"
def test_instance_gets_class_attributes(tmp_path):
    src = (
        "class Thing:\n"
        "    cattr = 1\n"
        "    def method(self):\n        pass\n"
        "t = Thing()\n"
        "t.<|>\n"
    )
    got = names(complete(tmp_path, src))
    assert "cattr" in got and "method" in got


# Spec: "Instances -- ... plus any attributes assigned in `__init__` via `self.name = ...`."
def test_instance_gets_init_self_attributes(tmp_path):
    src = (
        "class Thing:\n"
        "    def __init__(self):\n"
        "        self.count = 0\n"
        "        self.label = 'x'\n"
        "t = Thing()\n"
        "t.<|>\n"
    )
    comps = complete(tmp_path, src)
    got = names(comps)
    assert "count" in got and "label" in got
    assert find(comps, "label")["description"] == "instance of str"


# Spec: "Classes -- if `foo` is a class, return its methods and class attributes"
# Context: a class receiver does not expose `__init__`-assigned instance attributes.
def test_class_receiver_excludes_instance_attributes(tmp_path):
    src = (
        "class Thing:\n"
        "    def __init__(self):\n"
        "        self.only_on_instance = 1\n"
        "Thing.<|>\n"
    )
    assert "only_on_instance" not in names(complete(tmp_path, src))


# Spec: "Literals -- string/list/dict/set literals expose attributes appropriate to their inferred builtin type."
@pytest.mark.parametrize("literal,expected", [
    ("'abc'", "upper"),
    ("[1, 2]", "append"),
    ("{'a': 1}", "keys"),
    ("{1, 2}", "add"),
])
def test_literal_attribute_completion(tmp_path, literal, expected):
    comps = complete(tmp_path, "x = %s.<|>\n" % literal)
    assert expected in names(comps)


# Spec: "Literals -- ... expose attributes appropriate to their inferred builtin type."
# Context: a variable assigned a literal is an instance of that builtin type (T12).
def test_variable_holding_literal_exposes_builtin_attributes(tmp_path):
    comps = complete(tmp_path, "s = 'hello'\ns.<|>\n")
    assert "upper" in names(comps)


# Spec: "If there is a prefix after the dot, filter to attributes matching that prefix."
def test_attribute_prefix_filters(tmp_path):
    comps = complete(tmp_path, "s = 'hello'\ns.upp<|>\n")
    got = names(comps)
    assert got == ["upper"]
    assert comps[0]["complete"] == "er"


# Spec: "When the cursor follows a `.`, return attributes of the value before the dot."
# Context: an unresolvable receiver yields zero completions, which is still success (T13).
def test_unresolvable_receiver_returns_empty(tmp_path):
    comps = complete(tmp_path, "def f(param):\n    param.<|>\n")
    assert comps == []


# Spec: "When the cursor follows a `.`, return attributes of the value before the dot."
# Context: constructor call directly before the dot.
def test_constructor_call_receiver(tmp_path):
    src = (
        "class Thing:\n"
        "    def method(self):\n        pass\n"
        "x = Thing().me<|>\n"
    )
    assert "method" in names(complete(tmp_path, src))


# =====================================================================
# 3. Keyword Completion
# =====================================================================

# Spec: "When in a name-completion context, also include Python keywords as completions."
def test_keywords_included_in_name_context(tmp_path):
    comps = complete(tmp_path, "whi<|>\n")
    kw = find(comps, "while")
    assert kw["type"] == "keyword"
    assert kw["description"] == "while"


# Spec: "Keywords are filtered by the same prefix rules as names."
def test_keywords_filtered_by_prefix(tmp_path):
    got = names(complete(tmp_path, "el<|>\n"))
    assert "elif" in got and "else" in got
    assert "while" not in got


# Spec: "Keywords are not included in attribute completion (after `.`)."
def test_no_keywords_after_dot(tmp_path):
    comps = complete(tmp_path, "import os\nos.<|>\n")
    assert [c for c in comps if c["type"] == "keyword"] == []


# Spec: "Keywords are not included in attribute completion (after `.`)."
# Context: even when the post-dot prefix matches a keyword.
def test_keyword_prefix_after_dot_not_completed(tmp_path):
    comps = complete(tmp_path, "s = 'x'\ns.imp<|>\n")
    assert [c for c in comps if c["type"] == "keyword"] == []


# =====================================================================
# Prefix Matching
# =====================================================================

# Spec: "By default, prefix matching is case-insensitive."
def test_prefix_matching_is_case_insensitive(tmp_path):
    src = "Alpha = 1\nal<|>\n"
    assert "Alpha" in names(complete(tmp_path, src))


# Spec: "By default, prefix matching is case-insensitive." Context: typed uppercase, lowercase name.
def test_uppercase_prefix_matches_lowercase_name(tmp_path):
    comps = complete(tmp_path, "PRI<|>\n")
    assert find(comps, "print") is not None


# Spec: "When `--fuzzy` is passed ... the characters of the query must appear in the name in order,
#        but not necessarily contiguously."
def test_fuzzy_subsequence_match(tmp_path):
    comps = complete(tmp_path, "isnt<|>\n", fuzzy=True)
    assert "isinstance" in names(comps)


# Spec: "When `--fuzzy` is passed, matching is relaxed" -- context: without the flag it must not match.
def test_non_fuzzy_does_not_match_subsequence(tmp_path):
    comps = complete(tmp_path, "isnt<|>\n")
    assert "isinstance" not in names(comps)


# Spec: "Fuzzy matching is also case-insensitive."
def test_fuzzy_is_case_insensitive(tmp_path):
    src = "CamelCaseName = 1\ncmn<|>\n"
    assert "CamelCaseName" in names(complete(tmp_path, src, fuzzy=True))


# Spec: "When `--fuzzy` is passed ... characters ... in order" -- out-of-order query must not match.
def test_fuzzy_requires_order(tmp_path):
    comps = complete(tmp_path, "tni<|>\n", fuzzy=True)
    assert "print" not in names(comps)


# Spec: "When there is no prefix (cursor is right after `.` ...), all applicable names are returned."
def test_no_prefix_after_dot_returns_all_attributes(tmp_path):
    src = (
        "class Thing:\n"
        "    a_one = 1\n"
        "    def b_two(self):\n        pass\n"
        "Thing.<|>\n"
    )
    assert names(complete(tmp_path, src)) == ["a_one", "b_two"]


# Spec: "When there is no prefix (... or at a blank position), all applicable names are returned."
def test_no_prefix_at_blank_position_returns_all_names(tmp_path):
    comps = complete(tmp_path, "thing = 1\n<|>\n")
    got = names(comps)
    assert "thing" in got and "print" in got and "while" in got


# =====================================================================
# Output Format
# =====================================================================

# Spec: example output object -- fields name/complete/type/description
def test_completion_object_fields(tmp_path):
    comps = complete(tmp_path, "pri<|>\n")
    c = find(comps, "print")
    assert set(c) == {"name", "complete", "type", "description"}
    assert c == {"name": "print", "complete": "nt", "type": "function",
                 "description": "def print(...)"}


# Spec: example output -- "{"name":"property","complete":"roperty","type":"class","description":"class property"}"
def test_spec_example_property_entry(tmp_path):
    comps = complete(tmp_path, "p<|>\n")
    assert find(comps, "property") == {
        "name": "property", "complete": "roperty", "type": "class",
        "description": "class property"}


# Spec: "`complete` ... The text that would be inserted -- the name with the already-typed prefix removed."
def test_complete_strips_prefix(tmp_path):
    comps = complete(tmp_path, "value = 1\nva<|>\n")
    assert find(comps, "value")["complete"] == "lue"


# Spec: "`complete` ... If no prefix, equals `name`."
def test_complete_equals_name_without_prefix(tmp_path):
    comps = complete(tmp_path, "value = 1\n<|>\n")
    assert find(comps, "value")["complete"] == "value"


# Spec: "When prefix matching is case-insensitive, removal is by character count: the first
#        `len(prefix)` characters of the matched name are stripped regardless of case."
def test_complete_strips_by_character_count(tmp_path):
    comps = complete(tmp_path, "AlphaBet = 1\nalp<|>\n")
    assert find(comps, "AlphaBet")["complete"] == "haBet"


# Spec: "removal is by character count" -- context: fuzzy query, same rule (T7).
def test_complete_under_fuzzy_strips_by_character_count(tmp_path):
    comps = complete(tmp_path, "isnt<|>\n", fuzzy=True)
    assert find(comps, "isinstance")["complete"] == "stance"


# Spec: "`type` ... One of: module, class, function, instance, statement, param, keyword."
def test_type_values_are_from_the_enum(tmp_path):
    src = (
        "import os\n"
        "num = 1\n"
        "unknown = os.getcwd()\n"
        "class K:\n    pass\n"
        "def fn(arg):\n"
        "    <|>\n"
    )
    allowed = {"module", "class", "function", "instance", "statement", "param", "keyword"}
    comps = complete(tmp_path, src)
    assert {c["type"] for c in comps} <= allowed


# Spec: "For functions: `def name(...)`."
def test_function_type_and_description(tmp_path):
    comps = complete(tmp_path, "def myfunc(a, b):\n    pass\nmyf<|>\n")
    c = find(comps, "myfunc")
    assert c["type"] == "function"
    assert c["description"] == "def myfunc(...)"


# Spec: "For classes: `class Name`."
def test_class_type_and_description(tmp_path):
    comps = complete(tmp_path, "class MyClass:\n    pass\nMyC<|>\n")
    c = find(comps, "MyClass")
    assert c["type"] == "class"
    assert c["description"] == "class MyClass"


# Spec: "For imports: `module name`."
def test_import_module_type_and_description(tmp_path):
    comps = complete(tmp_path, "import os\no<|>\n")
    c = find(comps, "os")
    assert c["type"] == "module"
    assert c["description"] == "module os"


# Spec: "For imports: `module name`." Context: aliased import uses the bound name.
def test_aliased_import_description_uses_bound_name(tmp_path):
    comps = complete(tmp_path, "import os as operating\nopera<|>\n")
    c = find(comps, "operating")
    assert c["type"] == "module"
    assert c["description"] == "module operating"


# Spec: "For assignments: `instance of <type>` if the right-hand side is a literal"
@pytest.mark.parametrize("rhs,tname", [
    ("1", "int"), ("1.5", "float"), ("'s'", "str"), ("b'b'", "bytes"),
    ("True", "bool"), ("[1]", "list"), ("(1, 2)", "tuple"),
    ("{'a': 1}", "dict"), ("{1}", "set"), ("None", "NoneType"),
])
def test_literal_assignment_descriptions(tmp_path, rhs, tname):
    comps = complete(tmp_path, "var = %s\nva<|>\n" % rhs)
    c = find(comps, "var")
    assert c["type"] == "instance"
    assert c["description"] == "instance of %s" % tname


# Spec: "For assignments: `instance of <type>` if the right-hand side is ... a constructor call"
def test_constructor_call_assignment_description(tmp_path):
    src = "class Widget:\n    pass\nw = Widget()\nw<|>\n"
    c = find(complete(tmp_path, src), "w")
    assert c["type"] == "instance"
    assert c["description"] == "instance of Widget"


# Spec: "For assignments: ... otherwise `statement`."
def test_unresolvable_assignment_is_statement(tmp_path):
    src = "import os\nthing = os.getcwd()\nthin<|>\n"
    c = find(complete(tmp_path, src), "thing")
    assert c["type"] == "statement"
    assert c["description"] == "statement"


# Spec: "For keywords: the keyword itself."
def test_keyword_description_is_the_keyword(tmp_path):
    comps = complete(tmp_path, "lamb<|>\n")
    c = find(comps, "lambda")
    assert c["type"] == "keyword" and c["description"] == "lambda"


# Spec: "`param`" is one of the completion types.
def test_parameter_type(tmp_path):
    comps = complete(tmp_path, "def f(needle):\n    need<|>\n")
    assert find(comps, "needle")["type"] == "param"


# Spec: "For imported names (from import statements), the `type` reflects the imported object's
#        actual kind if inferable (e.g., `function`, `class`, `module`)."
def test_from_import_types_are_inferred(tmp_path):
    src = (
        "from os import getcwd\n"
        "from os import path\n"
        "from collections import OrderedDict\n"
        "<|>\n"
    )
    comps = complete(tmp_path, src)
    assert find(comps, "getcwd")["type"] == "function"
    assert find(comps, "path")["type"] == "module"
    assert find(comps, "OrderedDict")["type"] == "class"


# Spec: "If not inferable, use `statement`."
def test_uninferable_import_is_statement(tmp_path):
    comps = complete(tmp_path, "from no_such_module_xyz import thing\nthi<|>\n")
    assert find(comps, "thing")["type"] == "statement"


# =====================================================================
# Ordering
# =====================================================================

# Spec: "1. Public names (do not start with `_`) -- sorted alphabetically, case-insensitive."
def test_public_names_sorted_case_insensitively(tmp_path):
    src = "zebra = 1\nApple = 2\nmango = 3\n<|>\n"
    got = [n for n in names(complete(tmp_path, src)) if n in {"zebra", "Apple", "mango"}]
    assert got == ["Apple", "mango", "zebra"]


# Spec: "1. Public names ... 2. Private names (start with `_` but not `__`) ...
#        3. Dunder names (start with `__` and end with `__`) ... 4. Keywords"
def test_group_ordering(tmp_path):
    src = "import os\npublic_x = 1\n_private_x = 2\n__dunder_x__ = 3\n<|>\n"
    comps = complete(tmp_path, src)
    assert_ordering(comps)
    got = names(comps)
    assert got.index("public_x") < got.index("_private_x") < got.index("__dunder_x__")


# Spec: "4. Keywords -- sorted alphabetically after all names."
def test_keywords_come_after_all_names(tmp_path):
    comps = complete(tmp_path, "as<|>\n")
    got = names(comps)
    # `AssertionError`/`ascii` are builtin names; `as`/`assert`/`async` are keywords
    assert got == ["ascii", "AssertionError", "as", "assert", "async"]


# Spec: "Within each group, break ties by case-insensitive alphabetical order."
def test_ordering_holds_for_large_result_sets(tmp_path):
    comps = complete(tmp_path, "import os\nfrom os import path\nvar = 1\n<|>\n")
    assert_ordering(comps)


# Spec: "4. Keywords -- sorted alphabetically after all names."
# Context: keywords are themselves alphabetical, case-insensitively.
def test_keywords_sorted_case_insensitively(tmp_path):
    comps = complete(tmp_path, "<|>\n")
    kws = [c["name"] for c in comps if c["type"] == "keyword"]
    assert kws == sorted(kws, key=str.lower)
    assert kws[:3] == ["and", "as", "assert"]


# =====================================================================
# Imports
# =====================================================================

# Spec: "`import os` makes `os` visible as a module."
def test_import_makes_module_visible(tmp_path):
    comps = complete(tmp_path, "import os\no<|>\n")
    assert find(comps, "os")["type"] == "module"


# Spec: "`from os import *` makes all public names from `os` visible."
def test_star_import_from_stdlib(tmp_path):
    comps = complete(tmp_path, "from os import *\ngetc<|>\n")
    assert "getcwd" in names(comps)


# Spec: "`from os import *` makes all public names from `os` visible."
# Context: non-public names are not made visible.
def test_star_import_excludes_private_names(tmp_path):
    comps = complete(tmp_path, "from os import *\n_e<|>\n")
    assert "_exit" not in names(comps)


# Spec: "Star imports resolve both installed packages and local project modules
#        (files in the same directory)."
def test_star_import_from_local_module(tmp_path):
    write(tmp_path, "def local_helper():\n    pass\n\n\nLOCAL_CONST = 3\n_hidden = 4\n",
          name="helper.py")
    comps = complete(tmp_path, "from helper import *\nlocal<|>\n")
    got = names(comps)
    assert "local_helper" in got and "LOCAL_CONST" in names(
        complete(tmp_path, "from helper import *\nLOC<|>\n"))
    assert "_hidden" not in names(complete(tmp_path, "from helper import *\n_h<|>\n"))


# Spec: "Star imports resolve both installed packages and local project modules."
# Context: the kind of a star-imported local name is still inferred.
def test_star_imported_local_function_type(tmp_path):
    write(tmp_path, "def local_helper():\n    pass\n", name="helper.py")
    comps = complete(tmp_path, "from helper import *\nlocal<|>\n")
    assert find(comps, "local_helper")["type"] == "function"


# Spec: "Modules -- if `foo` is an imported module, return the module's public names."
# Context: a local project module as the receiver.
def test_local_module_attribute_completion(tmp_path):
    write(tmp_path, "def local_helper():\n    pass\n_hidden = 1\n", name="helper.py")
    comps = complete(tmp_path, "import helper\nhelper.<|>\n")
    got = names(comps)
    assert "local_helper" in got and "_hidden" not in got


# =====================================================================
# Error Handling
# =====================================================================

# Spec: "File does not exist or is not a regular file: exit 1, message to STDERR."
def test_missing_file(tmp_path):
    r = run(tmp_path / "missing.py", 1, 0)
    assert r.returncode == 1 and r.stderr.strip()


# Spec: "File does not exist or is not a regular file: exit 1, message to STDERR."
def test_directory_is_not_a_regular_file(tmp_path):
    r = run(tmp_path, 1, 0)
    assert r.returncode == 1 and r.stderr.strip()


# Spec: "File is not valid UTF-8: exit 1."
def test_invalid_utf8(tmp_path):
    p = tmp_path / "bad.py"
    p.write_bytes(b"x = 1\ny = '\xff\xfe'\n")
    r = run(p, 1, 0)
    assert r.returncode == 1 and r.stderr.strip()


# Spec: "Line or column out of range: exit 1."
def test_out_of_range_reports_error(tmp_path):
    p = write(tmp_path, "x = 1\n")
    assert run(p, 2, 0).returncode == 1
    assert run(p, 1, 6).returncode == 1


# Spec: "Python syntax errors in the source file: do not exit with an error."
def test_syntax_error_does_not_fail(tmp_path):
    src = "def broken(:\n    pass\npri<|>\n"
    comps = complete(tmp_path, src)
    assert "print" in names(comps)


# Spec: "Parse as much as possible and provide completions based on what was successfully parsed."
def test_definitions_survive_a_broken_line(tmp_path):
    src = "good_name = 1\nif :\n    pass\nother_name = 2\ngo<|>\n"
    assert "good_name" in names(complete(tmp_path, src))


# Spec: "Syntax errors are common during editing -- the tool must be tolerant."
# Context: the cursor line itself is the syntax error (a trailing dot).
def test_trailing_dot_line_is_tolerated(tmp_path):
    src = "import os\nos.<|>\n"
    assert "getcwd" in names(complete(tmp_path, src))


# Spec: "Syntax errors are common during editing -- the tool must be tolerant."
# Context: a broken cursor line inside a function must not lose the local scope.
def test_local_scope_survives_broken_cursor_line(tmp_path):
    src = "def f():\n    data = [1]\n    data.app<|>\n"
    assert "append" in names(complete(tmp_path, src))


# =====================================================================
# Clarifications
# =====================================================================

# Spec: "Name completion with an empty prefix returns all currently visible names plus keywords,
#        then applies the ordering rules in this spec."
def test_empty_prefix_name_completion(tmp_path):
    src = "import os\nalpha = 1\n<|>\n"
    comps = complete(tmp_path, src)
    got = names(comps)
    assert "alpha" in got and "os" in got and "len" in got
    assert any(c["type"] == "keyword" for c in comps)
    assert_ordering(comps)


# Spec: "Attribute completion with an empty prefix returns all resolved attributes for the
#        receiver expression and never adds keywords."
def test_empty_prefix_attribute_completion(tmp_path):
    comps = complete(tmp_path, "d = {}\nd.<|>\n")
    got = names(comps)
    assert "keys" in got and "items" in got
    assert all(c["type"] != "keyword" for c in comps)
    assert_ordering(comps)


# =====================================================================
# Receivers not literally named by the spec (see AMBIGUITIES T21)
# =====================================================================

# Spec: "Instances -- ... plus any attributes assigned in `__init__` via `self.name = ...`."
# Context: `self` inside a method is itself an instance of the enclosing class.
def test_self_receiver_inside_method(tmp_path):
    src = (
        "class Thing:\n"
        "    label = 1\n"
        "    def __init__(self):\n"
        "        self.count = 0\n"
        "    def method(self):\n"
        "        self.<|>\n"
    )
    got = names(complete(tmp_path, src))
    assert "count" in got and "label" in got and "method" in got


# Spec: "Classes -- if `foo` is a class, return its methods and class attributes"
# Context: `cls` in a classmethod is the class, so instance attributes are excluded.
def test_cls_receiver_in_classmethod(tmp_path):
    src = (
        "class Thing:\n"
        "    label = 1\n"
        "    def __init__(self):\n"
        "        self.count = 0\n"
        "    @classmethod\n"
        "    def make(cls):\n"
        "        cls.<|>\n"
    )
    got = names(complete(tmp_path, src))
    assert "label" in got and "count" not in got


# Spec: "When the cursor follows a `.`, return attributes of the value before the dot."
# Context: the first parameter of a staticmethod is an ordinary parameter, not the class.
def test_staticmethod_first_param_is_not_self(tmp_path):
    src = (
        "class Thing:\n"
        "    label = 1\n"
        "    @staticmethod\n"
        "    def helper(thing):\n"
        "        thing.<|>\n"
    )
    assert complete(tmp_path, src) == []


# Spec: "Instances -- ... return the same attributes as the class"
# Context: annotated parameters resolve to their annotated class.
def test_annotated_parameter_receiver(tmp_path):
    src = (
        "class Thing:\n"
        "    def method(self):\n        pass\n"
        "def use(t: Thing):\n"
        "    t.<|>\n"
    )
    assert "method" in names(complete(tmp_path, src))


# Spec: "Parse as much as possible and provide completions based on what was successfully parsed."
# Context: a block header missing its colon must not destroy the block's contents.
def test_incomplete_block_header_keeps_body(tmp_path):
    src = (
        "class C:\n"
        "    def m(self)\n"
        "        pass\n"
        "c = C()\n"
        "c.<|>\n"
    )
    assert "m" in names(complete(tmp_path, src))
