"""Spec section: Part 3 / ICL Configuration (parsing, files, validation)."""
from __future__ import annotations

import json

from conftest import COT_SETUP, DIRECT_SETUP, base_config, icl_config
from mock_server import MockAPI, always


ROW = {"question": "What is 15 + 27?", "answer": "42"}


# ---------------------------------------------------------------------------
# Phrase: "Tasks may define named ICL setups" (the `icl.setups` YAML block)
# Context: Part 3 / ICL Configuration.
# ---------------------------------------------------------------------------
def test_inline_setups_are_accepted(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [COT_SETUP, DIRECT_SETUP],
                                      k=2, strategy="round_robin"))
        data = write_input([ROW])
        res = run_tool(cfg, data)
    assert res.returncode == 0, res
    assert res.rows[0]["output"][0]["icl_setup"] in ("chain_of_thought",
                                                     "direct")


# ---------------------------------------------------------------------------
# Phrase: "Setups may also come from files" / "file format" JSONL block
# Context: Part 3 / ICL Configuration.
# ---------------------------------------------------------------------------
def test_file_backed_setup_is_loaded(run_tool, write_config, write_input,
                                     workdir):
    (workdir / "icl").mkdir()
    (workdir / "icl" / "gsm8k_detailed.jsonl").write_text(
        json.dumps({"input": {"question": "What is 10 / 2?"},
                    "output": "10 divided by 2 is 5.\n#### 5"}) + "\n")
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [{"name": "detailed", "file": "icl/gsm8k_detailed.jsonl"}],
            k=3, strategy="fixed"))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert res.rows[0]["output"][0]["icl_setup"] == "detailed"
    assert sent["messages"][1] == {"role": "user", "content": "What is 10 / 2?"}
    assert sent["messages"][2] == {"role": "assistant",
                                   "content": "10 divided by 2 is 5.\n#### 5"}


# ---------------------------------------------------------------------------
# Phrase: "file paths are relative to the config file directory"
# Context: Part 3 / ICL Configuration.  The tool is run from the repo root, so
# a path that only resolves against the config's directory proves the rule.
# ---------------------------------------------------------------------------
def test_file_path_is_relative_to_config_dir(run_tool, write_config,
                                             write_input, workdir):
    nested = workdir / "cfgdir"
    nested.mkdir()
    (nested / "shots.jsonl").write_text(
        json.dumps({"input": {"question": "q?"}, "output": "#### 1"}) + "\n")
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [{"name": "fromfile", "file": "shots.jsonl"}]),
            name="cfgdir/task.yaml")
        data = write_input([ROW])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert sent["messages"][2]["content"] == "#### 1"


# ---------------------------------------------------------------------------
# Phrase: "each setup has a `name` and exactly one of `examples` or `file`"
# Context: Part 3 / ICL Configuration.
# ---------------------------------------------------------------------------
def test_setup_without_name_is_an_error(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [{"examples": COT_SETUP["examples"]}]))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0
    assert res.stderr.strip()


# Context: same phrase - both `examples` and `file` is not "exactly one".
def test_setup_with_both_examples_and_file_is_an_error(run_tool, write_config,
                                                       write_input, workdir):
    (workdir / "shots.jsonl").write_text(
        json.dumps({"input": {"question": "q?"}, "output": "#### 1"}) + "\n")
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [
            {"name": "both", "examples": COT_SETUP["examples"],
             "file": "shots.jsonl"}]))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0


# Context: same phrase - neither `examples` nor `file` is not "exactly one".
def test_setup_with_neither_examples_nor_file_is_an_error(run_tool,
                                                          write_config,
                                                          write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [{"name": "empty"}]))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0


# ---------------------------------------------------------------------------
# Phrase: "malformed lines or missing keys must terminate the run with exit
#          code 1 before any API requests are sent; malformed line errors
#          include `not valid JSON`"
# Context: Part 3 / ICL Configuration.
# ---------------------------------------------------------------------------
def test_malformed_jsonl_line_exits_1_with_not_valid_json(run_tool,
                                                          write_config,
                                                          write_input,
                                                          workdir):
    (workdir / "shots.jsonl").write_text(
        json.dumps({"input": {"question": "q?"}, "output": "#### 1"}) + "\n"
        + "{not json at all\n")
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [{"name": "broken", "file": "shots.jsonl"}]))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1, res
    assert "not valid JSON" in res.stderr
    assert calls == 0


# Context: same phrase - a line missing the `input` key.
def test_jsonl_line_missing_input_key_exits_1(run_tool, write_config,
                                              write_input, workdir):
    (workdir / "shots.jsonl").write_text(
        json.dumps({"output": "#### 1"}) + "\n")
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [{"name": "broken", "file": "shots.jsonl"}]))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0
    assert res.stderr.strip()


# Context: same phrase - a line missing the `output` key.
def test_jsonl_line_missing_output_key_exits_1(run_tool, write_config,
                                               write_input, workdir):
    (workdir / "shots.jsonl").write_text(
        json.dumps({"input": {"question": "q?"}}) + "\n")
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [{"name": "broken", "file": "shots.jsonl"}]))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0


# Context: same phrase - `{"input": <object>, "output": <string>}`: an `input`
# that is not an object, and an `output` that is not a string, are both errors.
def test_jsonl_line_with_wrong_types_exits_1(run_tool, write_config,
                                             write_input, workdir):
    (workdir / "a.jsonl").write_text(
        json.dumps({"input": "not an object", "output": "#### 1"}) + "\n")
    (workdir / "b.jsonl").write_text(
        json.dumps({"input": {"question": "q?"}, "output": 5}) + "\n")
    for name in ("a.jsonl", "b.jsonl"):
        with MockAPI(always("#### 42")) as api:
            cfg = write_config(
                icl_config(api.url, [{"name": "broken", "file": name}]),
                name=f"task_{name}.yaml")
            data = write_input([ROW])
            res = run_tool(cfg, data)
            calls = api.call_count
        assert res.returncode == 1, (name, res)
        assert calls == 0


# Context: same phrase - "each non-empty line": blank lines are skipped.
def test_blank_lines_in_jsonl_are_ignored(run_tool, write_config, write_input,
                                          workdir):
    (workdir / "shots.jsonl").write_text(
        "\n" + json.dumps({"input": {"question": "q?"},
                           "output": "#### 1"}) + "\n\n  \n")
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [{"name": "ok", "file": "shots.jsonl"}]))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert [m["role"] for m in sent["messages"]] == ["system", "user",
                                                     "assistant", "user"]


# Context: same phrase - a missing ICL file is a fatal config error, too.
def test_missing_icl_file_exits_1(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(
            api.url, [{"name": "gone", "file": "nope.jsonl"}]))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0


# ---------------------------------------------------------------------------
# Phrase: "`icl.strategy` is one of `fixed`, `random`, or `round_robin`"
# Context: Part 3 / ICL Configuration.
# ---------------------------------------------------------------------------
def test_unknown_strategy_is_an_error(run_tool, write_config, write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [COT_SETUP],
                                      strategy="alphabetical"))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0


def test_each_documented_strategy_is_accepted(run_tool, write_config,
                                              write_input):
    for strategy in ("fixed", "random", "round_robin"):
        with MockAPI(always("#### 42")) as api:
            cfg = write_config(icl_config(api.url, [COT_SETUP, DIRECT_SETUP],
                                          strategy=strategy),
                               name=f"task_{strategy}.yaml")
            data = write_input([ROW])
            res = run_tool(cfg, data)
        assert res.returncode == 0, (strategy, res)


# ---------------------------------------------------------------------------
# Phrase: "ICL examples are inserted ... each example's `input` is rendered
#          with the task's `prompt.user` template"
# Context: Part 3 / ICL Configuration (AMBIGUITIES T53): an example whose
# `input` lacks a templated field cannot be rendered - fail before requests.
# ---------------------------------------------------------------------------
def test_example_missing_a_template_field_exits_1(run_tool, write_config,
                                                  write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(icl_config(api.url, [
            {"name": "bad", "examples": [{"input": {"other": "x"},
                                          "output": "#### 1"}]}]))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        calls = api.call_count
    assert res.returncode == 1, res
    assert calls == 0


# ---------------------------------------------------------------------------
# Phrase: "Tasks may define named ICL setups" - ICL is optional; a task with
#         no `icl` section is unchanged.
# Context: Part 3 / ICL Configuration.
# ---------------------------------------------------------------------------
def test_no_icl_section_keeps_part1_behaviour(run_tool, write_config,
                                              write_input):
    with MockAPI(always("#### 42")) as api:
        cfg = write_config(base_config(api.url))
        data = write_input([ROW])
        res = run_tool(cfg, data)
        sent = api.requests[0]
    assert res.returncode == 0, res
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]
    assert res.rows[0]["output"] == {"solution": "#### 42"}
