"""Part 3 ICL configuration: setups, files, `k`, and `strategy` validation."""
import json
import os

import pytest
import yaml

from conftest import icl_block, icl_setup, make_config, marker_setups
from mock_api import MockAPI, always

ROWS = [{"question": "2+2?", "answer": "4"}]


def write_jsonl(workdir, relpath, text):
    path = os.path.join(str(workdir), relpath)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    return path


def jsonl_lines(*pairs):
    return "".join(json.dumps({"input": inp, "output": out}) + "\n"
                   for inp, out in pairs)


# Spec: "Tasks may define named ICL setups" -- the spec's own YAML block.
# Context: ICL Configuration.
SPEC_ICL = """
tasks:
  gsm8k:
    api_url: "%s"
    model: "gpt-4"
    rpm: 60
    prompt:
      system: "Solve the math problem step by step. Final answer after ####."
      user: "{question}"
    icl:
      setups:
        - name: "chain_of_thought"
          examples:
            - input: {question: "What is 2+2?"}
              output: "Let me think step by step.\\n2 + 2 = 4\\n#### 4"
            - input: {question: "If I have 3 cats and get 2 more, how many cats do I have?"}
              output: "Step by step:\\nI start with 3 cats.\\nI get 2 more.\\n3 + 2 = 5\\n#### 5"
        - name: "direct"
          examples:
            - input: {question: "What is 2+2?"}
              output: "#### 4"
            - input: {question: "If I have 3 cats and get 2 more, how many cats do I have?"}
              output: "#### 5"
      k: 2
      strategy: "round_robin"
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
    output_field: "solution"
"""


def test_spec_icl_config_block_is_accepted(multi):
    with MockAPI(always("#### 4")) as api:
        run = multi.run(None, {"gsm8k": ROWS}, config_text=SPEC_ICL % api.url)
    assert run.returncode == 0, run.stderr
    assert api.call_count >= 1


# Spec: "Setups may also come from files" / "File format: {"input": {...},
#        "output": "..."}"
# Context: ICL Configuration.
def test_file_backed_setup_is_loaded_and_used(run_tool, workdir):
    write_jsonl(workdir, "icl/gsm8k_detailed.jsonl",
                jsonl_lines(({"question": "What is 10 / 2?"},
                             "10 divided by 2 is 5.\n#### 5")))
    icl = icl_block([icl_setup("detailed", file="icl/gsm8k_detailed.jsonl")])
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl), ROWS)
    assert run.returncode == 0, run.stderr
    messages = api.calls[0]["messages"]
    assert {"role": "user", "content": "What is 10 / 2?"} in messages
    assert {"role": "assistant",
            "content": "10 divided by 2 is 5.\n#### 5"} in messages


# Spec: "file paths are relative to the config file directory"
# Context: ICL Configuration rules.
def test_file_path_is_relative_to_the_config_directory(cli, workdir):
    cfg_dir = workdir / "conf"
    os.makedirs(str(cfg_dir), exist_ok=True)
    write_jsonl(cfg_dir, "shots.jsonl",
                jsonl_lines(({"question": "demo"}, "DEMO_OUT")))
    icl = icl_block([icl_setup("s", file="shots.jsonl")])
    with MockAPI(always("#### 4")) as api:
        cfg = make_config(api_url=api.url, icl=icl)
        cfg_path = cfg_dir / "task.yaml"
        cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
        in_path = workdir / "data.jsonl"
        in_path.write_text(json.dumps(ROWS[0]) + "\n")
        out_path = workdir / "out.jsonl"
        # cwd is workdir, so a config-relative path is the only one that works.
        proc = cli("run", "--config", str(cfg_path), "--input", str(in_path),
                   "--output", str(out_path))
    assert proc.returncode == 0, proc.stderr
    assert "DEMO_OUT" in json.dumps(api.calls[0]["messages"])


def test_file_path_relative_to_cwd_is_not_used(cli, workdir):
    # The same file name exists next to the *input*, not next to the config.
    write_jsonl(workdir, "shots.jsonl", jsonl_lines(({"question": "d"}, "X")))
    cfg_dir = workdir / "conf"
    os.makedirs(str(cfg_dir), exist_ok=True)
    icl = icl_block([icl_setup("s", file="shots.jsonl")])
    with MockAPI(always("#### 4")) as api:
        cfg_path = cfg_dir / "task.yaml"
        cfg_path.write_text(yaml.safe_dump(
            make_config(api_url=api.url, icl=icl), sort_keys=False))
        in_path = workdir / "data.jsonl"
        in_path.write_text(json.dumps(ROWS[0]) + "\n")
        proc = cli("run", "--config", str(cfg_path), "--input", str(in_path),
                   "--output", str(workdir / "out.jsonl"))
        assert proc.returncode == 1
        assert api.call_count == 0


# Spec: "each setup has a `name` and exactly one of `examples` or `file`"
# Context: ICL Configuration rules.
def test_setup_without_a_name_exits_1(run_tool):
    icl = {"setups": [{"examples": [{"input": {"question": "d"},
                                     "output": "o"}]}]}
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl), ROWS)
    assert run.returncode == 1
    assert api.call_count == 0


def test_setup_with_both_examples_and_file_exits_1(run_tool, workdir):
    write_jsonl(workdir, "shots.jsonl", jsonl_lines(({"question": "d"}, "o")))
    setup = icl_setup("s", examples=[({"question": "d"}, "o")],
                      file="shots.jsonl")
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl_block([setup])),
                       ROWS)
    assert run.returncode == 1
    assert api.call_count == 0


def test_setup_with_neither_examples_nor_file_exits_1(run_tool):
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   icl=icl_block([{"name": "s"}])), ROWS)
    assert run.returncode == 1
    assert api.call_count == 0


# Spec: "file-backed setups must be valid JSONL where each non-empty line has
#        {"input": <object>, "output": <string>}; malformed lines or missing
#        keys must terminate the run with exit code 1 before any API requests
#        are sent"
# Context: ICL Configuration rules.
@pytest.mark.parametrize("text", [
    '{"input": {"question": "d"}, "output": "o"}\n{not json}\n',   # malformed
    '{"input": {"question": "d"}}\n',                              # no output
    '{"output": "o"}\n',                                           # no input
    '{"input": "d", "output": "o"}\n',                 # input is not an object
    '{"input": {"question": "d"}, "output": 5}\n',     # output is not a string
    '["input", "output"]\n',                           # line is not an object
])
def test_malformed_icl_file_exits_1_before_any_request(run_tool, workdir, text):
    write_jsonl(workdir, "shots.jsonl", text)
    icl = icl_block([icl_setup("s", file="shots.jsonl")])
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl), ROWS)
    assert run.returncode == 1
    assert api.call_count == 0


def test_blank_lines_in_an_icl_file_are_skipped(run_tool, workdir):
    write_jsonl(workdir, "shots.jsonl",
                '\n{"input": {"question": "d"}, "output": "o"}\n\n\n')
    icl = icl_block([icl_setup("s", file="shots.jsonl")])
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl), ROWS)
    assert run.returncode == 0, run.stderr
    assert len(api.calls[0]["messages"]) == 4    # system + 1 shot pair + user


def test_missing_icl_file_exits_1(run_tool):
    icl = icl_block([icl_setup("s", file="nope.jsonl")])
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl), ROWS)
    assert run.returncode == 1
    assert api.call_count == 0


# Inline examples are held to the same shape as file-backed ones.
@pytest.mark.parametrize("example", [
    {"input": {"question": "d"}},
    {"output": "o"},
    {"input": "d", "output": "o"},
    {"input": {"question": "d"}, "output": 7},
])
def test_malformed_inline_example_exits_1(run_tool, example):
    icl = icl_block([{"name": "s", "examples": [example]}])
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl), ROWS)
    assert run.returncode == 1
    assert api.call_count == 0


# Spec: "`icl.k` defaults to all examples in the selected setup"
# Context: ICL Configuration rules.
def test_k_defaults_to_every_example_in_the_setup(run_tool):
    setups = marker_setups(["A"], per_setup=3)
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl_block(setups)),
                       ROWS)
    assert run.returncode == 0, run.stderr
    assistants = [m for m in api.calls[0]["messages"] if m["role"] == "assistant"]
    assert [m["content"] for m in assistants] == ["MARK_A0", "MARK_A1", "MARK_A2"]


# Spec: "if `k` is smaller than the number of examples in the setup, use the
#        first `k`"
# Context: ICL Configuration rules.
def test_k_smaller_than_the_setup_uses_the_first_k_examples(run_tool):
    setups = marker_setups(["A"], per_setup=4)
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   icl=icl_block(setups, k=2)), ROWS)
    assert run.returncode == 0, run.stderr
    assistants = [m for m in api.calls[0]["messages"] if m["role"] == "assistant"]
    assert [m["content"] for m in assistants] == ["MARK_A0", "MARK_A1"]


# T54: `k` larger than the available examples uses them all rather than failing.
def test_k_larger_than_the_setup_uses_every_example(run_tool):
    setups = marker_setups(["A"], per_setup=2)
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   icl=icl_block(setups, k=9)), ROWS)
    assert run.returncode == 0, run.stderr
    assistants = [m for m in api.calls[0]["messages"] if m["role"] == "assistant"]
    assert [m["content"] for m in assistants] == ["MARK_A0", "MARK_A1"]


# T54: a non-positive or non-integer `k` is a configuration error.
@pytest.mark.parametrize("bad_k", [0, -1, "two", 1.5])
def test_invalid_k_exits_1(run_tool, bad_k):
    setups = marker_setups(["A"], per_setup=2)
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   icl=icl_block(setups, k=bad_k)), ROWS)
    assert run.returncode == 1
    assert api.call_count == 0


# Spec: "`icl.strategy` is one of `fixed`, `random`, or `round_robin`"
# Context: ICL Configuration rules.
@pytest.mark.parametrize("strategy", ["fixed", "random", "round_robin"])
def test_each_documented_strategy_is_accepted(run_tool, strategy):
    setups = marker_setups(["A", "B"])
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url,
                                   icl=icl_block(setups, strategy=strategy)),
                       ROWS)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("strategy", ["Fixed", "cycle", "", 3, None])
def test_unknown_strategy_exits_1(run_tool, strategy):
    setups = marker_setups(["A", "B"])
    block = icl_block(setups)
    block["strategy"] = strategy
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=block), ROWS)
    assert run.returncode == 1
    assert api.call_count == 0


# T43: an omitted `strategy` defaults to `fixed`, so every attempt uses the
# first declared setup.
def test_strategy_defaults_to_fixed(run_tool):
    setups = marker_setups(["A", "B", "C"])
    icl = icl_block(setups)              # no strategy key
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl, scheme="sample",
                                   temperature=0.7, num_solutions=3), ROWS)
    assert run.returncode == 0, run.stderr
    assert [o["icl_setup"] for o in run.rows[0]["output"]] == ["A", "A", "A"]


# T55: an `icl` block that declares no setups is a configuration error.
@pytest.mark.parametrize("block", [{"setups": []}, {"k": 2}, {},
                                   {"setups": "chain_of_thought"}])
def test_icl_block_without_usable_setups_exits_1(run_tool, block):
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=block), ROWS)
    assert run.returncode == 1
    assert api.call_count == 0


# T57: an example whose `input` cannot fill the prompt template is fatal, and
# is caught before any request is sent.
def test_example_input_missing_a_template_field_exits_1(run_tool):
    icl = icl_block([icl_setup("s", examples=[({"other": "x"}, "o")])])
    with MockAPI(always("#### 4")) as api:
        run = run_tool(make_config(api_url=api.url, icl=icl), ROWS)
    assert run.returncode == 1
    assert api.call_count == 0


# T61: `icl` merges out of `defaults` like any other nested section.
def test_icl_can_come_from_defaults(multi):
    from conftest import make_multi_config
    setups = marker_setups(["A"])
    tasks = {"gsm8k": {"prompt": {"system": "S", "user": "{question}"},
                       "generation": {"scheme": "greedy"},
                       "evaluation": {"type": "exact_match",
                                      "answer_field": "answer",
                                      "extract": "last_number"},
                       "output_field": "solution"}}
    with MockAPI(always("#### 4")) as api:
        config = make_multi_config(defaults={"icl": icl_block(setups)},
                                   tasks=tasks, api_url=api.url)
        run = multi.run(config, {"gsm8k": ROWS})
    assert run.returncode == 0, run.stderr
    assert run.rows("gsm8k")[0]["output"][0]["icl_setup"] == "A"
