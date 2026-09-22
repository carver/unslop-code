"""Part 3: ICL setup declaration, file-backed setups, `k` and `strategy`."""

import fake_api


def inline_setup(name, *outputs, question="ex?"):
    """A setup whose examples' outputs identify it in a recorded request."""
    return {"name": name,
            "examples": [{"input": {"question": question}, "output": out}
                         for out in outputs]}


def icl(setups, **kw):
    cfg = {"setups": setups}
    cfg.update(kw)
    return cfg


ONE_SETUP = icl([inline_setup("chain_of_thought", "step\n#### 4")])


# ---------------------------------------------------------------------------
# Spec: "Tasks may define named ICL setups" with `icl: setups: - name: ...
#        examples: - input: {question: ...} output: ..."
# Context: ICL Configuration.  An inline-examples setup is accepted and the run
# succeeds.
# ---------------------------------------------------------------------------
def test_inline_examples_setup_is_accepted(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task={"icl": ONE_SETUP}, check=0)
    assert api.call_count == 1
    assert res.summary["total"] == 1


# ---------------------------------------------------------------------------
# Spec: "Setups may also come from files" / 'file: "icl/gsm8k_detailed.jsonl"'
# Context: ICL Configuration.  A file-backed setup is accepted.
# ---------------------------------------------------------------------------
def test_file_backed_setup_is_accepted(run_task, write_file):
    path = write_file("icl/gsm8k_detailed.jsonl",
                      [{"input": {"question": "What is 10 / 2?"},
                        "output": "10 divided by 2 is 5.\n#### 5"}])
    task = {"icl": icl([{"name": "detailed", "file": path}])}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=0)
    assert api.requests[0].assistant_contents == \
        ["10 divided by 2 is 5.\n#### 5"]
    assert res.summary["total"] == 1


# ---------------------------------------------------------------------------
# Spec: "file paths are relative to the config file directory"
# Context: ICL Configuration.  The CLI is run from the config's directory in
# these tests, so the distinguishing case is a config in a subdirectory whose
# file reference resolves next to it, not next to the process cwd.
# ---------------------------------------------------------------------------
CONFIG_IN_SUBDIR = """
task:
  name: gsm8k
  api_url: "%s"
  model: gpt-4
  prompt:
    system: Solve it.
    user: "{question}"
  generation: {scheme: greedy}
  evaluation: {type: exact_match, answer_field: answer, extract: last_number}
  output_field: solution
  icl:
    setups:
      - name: detailed
        file: examples.jsonl
"""


def test_file_path_is_relative_to_the_config_directory(run_cli, write_file,
                                                       write_input, workdir):
    # `examples.jsonl` exists only beside the config, never in the working
    # directory the CLI is invoked from.
    write_file("conf/examples.jsonl",
               [{"input": {"question": "What is 10 / 2?"}, "output": "#### 5"}])
    inp = write_input([{"question": "2+3?", "answer": "5"}])
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        cfg = write_file("conf/task.yaml", CONFIG_IN_SUBDIR % api.url)
        res = run_cli("run", "--config", str(workdir / cfg), "--input", inp,
                      check=0)
    assert api.requests[0].assistant_contents == ["#### 5"]
    assert res.summary["total"] == 1


# ---------------------------------------------------------------------------
# Spec: "each setup has a `name` and exactly one of `examples` or `file`"
# Context: ICL Configuration.  A setup with no name is rejected.
# ---------------------------------------------------------------------------
def test_setup_without_a_name_is_an_error(run_task):
    task = {"icl": icl([{"examples": [{"input": {"question": "q"},
                                       "output": "a"}]}])}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=1)
    assert api.call_count == 0
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Spec: "each setup has a `name` and exactly one of `examples` or `file`"
# Context: ICL Configuration.  Both keys at once is rejected.
# ---------------------------------------------------------------------------
def test_setup_with_both_examples_and_file_is_an_error(run_task, write_file):
    path = write_file("icl/a.jsonl",
                      [{"input": {"question": "q"}, "output": "a"}])
    task = {"icl": icl([{"name": "both", "file": path,
                         "examples": [{"input": {"question": "q"},
                                       "output": "a"}]}])}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=1)
    assert api.call_count == 0


# ---------------------------------------------------------------------------
# Spec: "each setup has a `name` and exactly one of `examples` or `file`"
# Context: ICL Configuration.  Neither key is rejected.
# ---------------------------------------------------------------------------
def test_setup_with_neither_examples_nor_file_is_an_error(run_task):
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task={"icl": icl([{"name": "empty"}])}, check=1)
    assert api.call_count == 0


# ---------------------------------------------------------------------------
# Spec: "file-backed setups must be valid JSONL where each non-empty line has
#        {"input": <object>, "output": <string>}; malformed lines ... must
#        terminate the run with exit code 1 before any API requests are sent"
# Context: ICL Configuration.  A line that is not JSON at all.
# ---------------------------------------------------------------------------
def test_malformed_jsonl_line_exits_1_before_any_request(run_task, write_file):
    path = write_file("icl/bad.jsonl",
                      '{"input": {"question": "q"}, "output": "a"}\nnot json\n')
    task = {"icl": icl([{"name": "detailed", "file": path}])}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        res = run_task(api, task=task, check=1)
    assert api.call_count == 0
    assert res.stderr.strip()


# ---------------------------------------------------------------------------
# Spec: "each non-empty line has {"input": <object>, "output": <string>};
#        ... missing keys must terminate the run with exit code 1"
# Context: ICL Configuration.  A line missing `output`.
# ---------------------------------------------------------------------------
def test_jsonl_line_missing_output_exits_1(run_task, write_file):
    path = write_file("icl/bad.jsonl", [{"input": {"question": "q"}}])
    task = {"icl": icl([{"name": "detailed", "file": path}])}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=1)
    assert api.call_count == 0


# ---------------------------------------------------------------------------
# Spec: 'each non-empty line has {"input": <object>, "output": <string>}'
# Context: ICL Configuration.  A line missing `input`.
# ---------------------------------------------------------------------------
def test_jsonl_line_missing_input_exits_1(run_task, write_file):
    path = write_file("icl/bad.jsonl", [{"output": "a"}])
    task = {"icl": icl([{"name": "detailed", "file": path}])}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=1)
    assert api.call_count == 0


# ---------------------------------------------------------------------------
# Spec: '{"input": <object>, "output": <string>}'
# Context: ICL Configuration.  `input` must be an object and `output` a string.
# ---------------------------------------------------------------------------
def test_jsonl_line_with_wrong_value_types_exits_1(run_task, write_file):
    for bad in ([{"input": "q", "output": "a"}],
                [{"input": {"question": "q"}, "output": 5}]):
        path = write_file("icl/bad.jsonl", bad)
        task = {"icl": icl([{"name": "detailed", "file": path}])}
        with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
            run_task(api, task=task, check=1)
        assert api.call_count == 0


# ---------------------------------------------------------------------------
# Spec: "valid JSONL where each non-empty line has ..."
# Context: ICL Configuration.  Blank lines are not lines to validate.
# ---------------------------------------------------------------------------
def test_blank_jsonl_lines_are_skipped(run_task, write_file):
    path = write_file(
        "icl/ok.jsonl",
        '\n{"input": {"question": "q"}, "output": "ex-a"}\n\n'
        '{"input": {"question": "q2"}, "output": "ex-b"}\n\n')
    task = {"icl": icl([{"name": "detailed", "file": path}])}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=0)
    assert api.requests[0].assistant_contents == ["ex-a", "ex-b"]


# ---------------------------------------------------------------------------
# Spec: "file paths are relative to the config file directory"
# Context: ICL Configuration.  A file that does not exist is a config error.
# ---------------------------------------------------------------------------
def test_missing_icl_file_exits_1(run_task):
    task = {"icl": icl([{"name": "detailed", "file": "icl/nope.jsonl"}])}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=1)
    assert api.call_count == 0


# ---------------------------------------------------------------------------
# Spec: "each non-empty line has {"input": <object>, "output": <string>}"
# Context: ICL Configuration; T59.  Inline examples are held to the same shape.
# ---------------------------------------------------------------------------
def test_malformed_inline_example_exits_1(run_task):
    for bad in ({"input": {"question": "q"}}, {"output": "a"},
                {"input": "q", "output": "a"},
                {"input": {"question": "q"}, "output": 5}):
        task = {"icl": icl([{"name": "x", "examples": [bad]}])}
        with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
            run_task(api, task=task, check=1)
        assert api.call_count == 0


# ---------------------------------------------------------------------------
# Spec: "`icl.k` defaults to all examples in the selected setup"
# Context: ICL Configuration.
# ---------------------------------------------------------------------------
def test_k_defaults_to_all_examples(run_task):
    task = {"icl": icl([inline_setup("cot", "ex-1", "ex-2", "ex-3")])}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=0)
    assert api.requests[0].assistant_contents == ["ex-1", "ex-2", "ex-3"]


# ---------------------------------------------------------------------------
# Spec: "if `k` is smaller than the number of examples in the setup, use the
#        first `k`"
# Context: ICL Configuration.
# ---------------------------------------------------------------------------
def test_k_smaller_than_the_setup_uses_the_first_k(run_task):
    task = {"icl": icl([inline_setup("cot", "ex-1", "ex-2", "ex-3")], k=2)}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=0)
    assert api.requests[0].assistant_contents == ["ex-1", "ex-2"]


# ---------------------------------------------------------------------------
# Spec: "if `k` is smaller than the number of examples in the setup, use the
#        first `k`"
# Context: ICL Configuration; T56.  A `k` larger than the setup uses them all.
# ---------------------------------------------------------------------------
def test_k_larger_than_the_setup_uses_every_example(run_task):
    task = {"icl": icl([inline_setup("cot", "ex-1", "ex-2")], k=5)}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=0)
    assert api.requests[0].assistant_contents == ["ex-1", "ex-2"]


# ---------------------------------------------------------------------------
# Spec: "`icl.k` defaults to all examples in the selected setup"
# Context: ICL Configuration; T56.  A non-positive `k` is a config error.
# ---------------------------------------------------------------------------
def test_non_positive_k_exits_1(run_task):
    task = {"icl": icl([inline_setup("cot", "ex-1")], k=0)}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=1)
    assert api.call_count == 0


# ---------------------------------------------------------------------------
# Spec: "`icl.strategy` is one of `fixed`, `random`, or `round_robin`"
# Context: ICL Configuration.  Any other value is a config error.
# ---------------------------------------------------------------------------
def test_unknown_strategy_exits_1(run_task):
    task = {"icl": icl([inline_setup("cot", "ex-1")], strategy="best")}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=1)
    assert api.call_count == 0


# ---------------------------------------------------------------------------
# Spec: "`icl.strategy` is one of `fixed`, `random`, or `round_robin`"
# Context: ICL Configuration.  All three values are accepted.
# ---------------------------------------------------------------------------
def test_each_named_strategy_is_accepted(run_task):
    for strategy in ("fixed", "random", "round_robin"):
        task = {"icl": icl([inline_setup("cot", "ex-1")], strategy=strategy)}
        with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
            run_task(api, task=task, check=0)
        assert api.call_count == 1


# ---------------------------------------------------------------------------
# Spec: "`icl.strategy` is one of `fixed`, `random`, or `round_robin`"
# Context: ICL Configuration; T45.  With the key omitted the run behaves as
# `fixed`: the first setup is used.
# ---------------------------------------------------------------------------
def test_strategy_defaults_to_fixed(run_task):
    task = {"icl": icl([inline_setup("a", "A-ex"), inline_setup("b", "B-ex")]),
            "num_solutions": 3,
            "generation": {"scheme": "sample", "temperature": 0.7}}
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_task(api, task=task, check=0)
    assert [r.icl_marker for r in api.requests] == ["A-ex"] * 3


# ---------------------------------------------------------------------------
# Spec: "each setup has a `name` and exactly one of `examples` or `file`"
# Context: ICL Configuration; T62.  `icl` with no usable setups is an error.
# ---------------------------------------------------------------------------
def test_icl_without_setups_exits_1(run_task):
    for bad in ({}, {"setups": []}, {"setups": {}}, {"k": 2}):
        with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
            run_task(api, task={"icl": bad}, check=1)
        assert api.call_count == 0


# ---------------------------------------------------------------------------
# Spec: "Tasks may define named ICL setups" under `tasks: gsm8k:`
# Context: ICL Configuration; T58.  `icl` is an ordinary task key, so it may be
# given per task or inherited from `defaults` in a multi-task config.
# ---------------------------------------------------------------------------
def test_icl_is_per_task_and_inheritable_from_defaults(run_multi):
    setups = icl([inline_setup("shared", "D-ex")])
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_multi(api, defaults={"icl": setups}, check=0)
    assert [r.icl_marker for r in api.requests] == ["D-ex", "D-ex"]

    per_task = icl([inline_setup("only_gsm8k", "G-ex")])
    with fake_api.FakeAPI(fake_api.always("#### 5")) as api:
        run_multi(api, tasks={"gsm8k": {"icl": per_task}}, check=0)
    markers = sorted(str(r.icl_marker) for r in api.requests)
    assert markers == ["G-ex", "None"]
