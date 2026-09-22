"""Part 4 config: the agentic scheme, `tools`, `max_iterations`, api_type."""
import pytest
import yaml

from conftest import (agentic_config, echo_tool, make_config,
                      make_multi_config, script_tool, static_map_tool)
from mock_api import MockAPI, agentic_turns, always

ROWS = [{"question": "How many employees are there?", "answer": "142"}]


def bad_config(run_tool, **kw):
    """Run with a broken config and return the failed `Run`."""
    with MockAPI(always("142")) as api:
        run = run_tool(agentic_config(api.url, **kw), ROWS)
    return run


# Spec: `scheme: "agentic"` joins the existing generation schemes.
# Context: Agentic Generation, task example.
def test_agentic_is_a_valid_scheme(run_tool):
    with MockAPI(always("142")) as api:
        run = run_tool(agentic_config(api.url), ROWS)
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is True


def test_unknown_scheme_is_still_rejected(run_tool):
    with MockAPI(always("142")) as api:
        run = run_tool(make_config(api_url=api.url, scheme="agentix"), ROWS)
    assert run.returncode == 1
    assert "scheme" in run.stderr


# Spec: `--scheme <...>` already selects the generation scheme.
# Context: Agentic Generation + part 1 CLI overrides.
def test_scheme_agentic_can_be_selected_from_the_cli(run_tool):
    steps = [[("lookup", {"key": "employees"})], "142 employees"]
    with MockAPI(agentic_turns(steps)) as api:
        cfg = agentic_config(api.url)
        cfg["task"]["generation"]["scheme"] = "greedy"
        run = run_tool(cfg, ROWS, args=["--scheme", "agentic"])
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["iterations"] == 2


# Spec: "generation: scheme: "agentic" / max_iterations: 10 /
#        temperature: 0.0"
# Context: Agentic Generation, task example. temperature 0.0 is legal here,
# unlike `sample` and `rejection`.
def test_agentic_accepts_temperature_zero(run_tool):
    with MockAPI(always("142")) as api:
        run = run_tool(agentic_config(api.url, temperature=0.0), ROWS)
    assert run.returncode == 0, run.stderr


def test_max_iterations_must_be_a_positive_integer(run_tool):
    run = bad_config(run_tool, max_iterations=0)
    assert run.returncode == 1
    assert "max_iterations" in run.stderr


def test_max_iterations_must_be_an_integer(run_tool):
    run = bad_config(run_tool, max_iterations="ten")
    assert run.returncode == 1
    assert "max_iterations" in run.stderr


# Spec: the `tools` block: name, description, parameters, handler.
# Context: Agentic Generation, task example.
def test_tools_must_be_a_list(run_tool):
    run = bad_config(run_tool, tools={"name": "lookup"})
    assert run.returncode == 1
    assert "tools" in run.stderr


def test_tool_needs_a_name(run_tool):
    tool = static_map_tool()
    del tool["name"]
    run = bad_config(run_tool, tools=[tool])
    assert run.returncode == 1
    assert "name" in run.stderr


def test_tool_needs_a_handler(run_tool):
    tool = static_map_tool()
    del tool["handler"]
    run = bad_config(run_tool, tools=[tool])
    assert run.returncode == 1
    assert "handler" in run.stderr


# Spec: "Handler types: `echo` ... `static_map` ... `script`"
# Context: Handler types.
def test_unknown_handler_type_is_rejected(run_tool):
    tool = static_map_tool()
    tool["handler"] = {"type": "magic"}
    run = bad_config(run_tool, tools=[tool])
    assert run.returncode == 1
    assert "handler" in run.stderr


def test_static_map_handler_needs_a_mapping(run_tool):
    tool = static_map_tool()
    del tool["handler"]["mapping"]
    run = bad_config(run_tool, tools=[tool])
    assert run.returncode == 1
    assert "mapping" in run.stderr


# Spec: "handler: type: "script" / command: "python3 -c" / arg_field: "code""
# Context: Script handler config.
def test_script_handler_needs_a_command(run_tool):
    tool = script_tool()
    del tool["handler"]["command"]
    run = bad_config(run_tool, tools=[tool])
    assert run.returncode == 1
    assert "command" in run.stderr


def test_script_handler_needs_an_arg_field(run_tool):
    tool = script_tool()
    del tool["handler"]["arg_field"]
    run = bad_config(run_tool, tools=[tool])
    assert run.returncode == 1
    assert "arg_field" in run.stderr


def test_a_task_may_declare_no_tools(run_tool):
    with MockAPI(always("142 employees")) as api:
        run = run_tool(agentic_config(api.url, tools=[]), ROWS)
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["iterations"] == 1


# Spec: "evaluation: type: "exact_match" ... extract: "last_number""
# Context: Agentic Generation task example; evaluation stays optional.
def test_agentic_without_evaluation_is_allowed(run_tool):
    with MockAPI(always("142 employees")) as api:
        run = run_tool(agentic_config(api.url, evaluation=None), ROWS)
    assert run.returncode == 0, run.stderr
    assert run.rows[0]["result"]["passed"] is None


# ---------------------------------------------------------- api_type ------

# Spec: "When `api_type` is `"completions"`, send requests to
#        `{api_url}/v1/completions`"
# Context: Completions Mode.
def test_api_type_completions_uses_the_completions_endpoint(run_tool):
    with MockAPI(always("#### 142")) as api:
        run = run_tool(make_config(api_url=api.url, api_type="completions"),
                       ROWS)
    assert run.returncode == 0, run.stderr
    assert api.paths == ["/v1/completions"]


def test_api_type_chat_is_the_default(run_tool):
    with MockAPI(always("#### 142")) as api:
        run = run_tool(make_config(api_url=api.url), ROWS)
    assert run.returncode == 0, run.stderr
    assert api.paths == ["/v1/chat/completions"]


def test_unknown_api_type_is_rejected(run_tool):
    with MockAPI(always("#### 142")) as api:
        run = run_tool(make_config(api_url=api.url, api_type="responses"),
                       ROWS)
    assert run.returncode == 1
    assert "api_type" in run.stderr


# Spec: "chat_template: "llama3"" with the four built-ins.
# Context: Completions Mode config.
def test_unknown_chat_template_is_rejected(run_tool):
    with MockAPI(always("#### 142")) as api:
        run = run_tool(make_config(api_url=api.url, api_type="completions",
                                   chat_template="alpaca"), ROWS)
    assert run.returncode == 1
    assert "chat_template" in run.stderr


@pytest.mark.parametrize("template", ["chatml", "llama3", "mistral", "zephyr"])
def test_every_built_in_template_is_accepted(run_tool, template):
    with MockAPI(always("#### 142")) as api:
        run = run_tool(make_config(api_url=api.url, api_type="completions",
                                   chat_template=template), ROWS)
    assert run.returncode == 0, run.stderr


# Spec: "defaults: api_type: "completions" / chat_template: "llama3""
# Context: Completions Mode config.
def test_api_type_and_template_may_come_from_defaults(multi):
    with MockAPI(always("#### 142")) as api:
        config = make_multi_config(
            defaults={"api_url": api.url, "api_type": "completions",
                      "chat_template": "llama3"})
        run = multi.run(config, {"gsm8k": ROWS,
                                 "mmlu": [{"question": "q", "answer": "A"}]})
    assert run.returncode == 0, run.stderr
    assert set(api.paths) == {"/v1/completions"}
    assert all(p["prompt"].startswith("<|begin_of_text|>") for p in api.calls)


# Spec: "Per-task override: tasks: gsm8k: api_type: "completions" /
#        chat_template: "chatml""
# Context: Completions Mode config.
def test_a_task_may_override_api_type_and_template(multi):
    with MockAPI(always("#### 142")) as api:
        tasks = {
            "gsm8k": {"prompt": {"system": "S", "user": "{question}"},
                      "generation": {"scheme": "greedy"},
                      "api_type": "completions", "chat_template": "chatml",
                      "output_field": "solution"},
            "mmlu": {"prompt": {"system": "S", "user": "{question}"},
                     "generation": {"scheme": "greedy"},
                     "output_field": "choice"},
        }
        config = make_multi_config(defaults={"api_url": api.url}, tasks=tasks)
        run = multi.run(config, {"gsm8k": ROWS, "mmlu": ROWS})
    assert run.returncode == 0, run.stderr
    assert set(api.paths) == {"/v1/completions", "/v1/chat/completions"}
    completions = [c for c in api.calls if "prompt" in c]
    assert completions[0]["prompt"].startswith("<|im_start|>system")


# Spec: "CLI flags: `--api-type <chat|completions>` /
#        `--chat-template <chatml|llama3|mistral|zephyr>` ... When provided,
#        these CLI flags override the config values."
# Context: Completions Mode CLI flags.
def test_cli_api_type_overrides_the_config(run_tool):
    with MockAPI(always("#### 142")) as api:
        run = run_tool(make_config(api_url=api.url, api_type="chat"), ROWS,
                       args=["--api-type", "completions"])
    assert run.returncode == 0, run.stderr
    assert api.paths == ["/v1/completions"]


def test_cli_chat_template_overrides_the_config(run_tool):
    with MockAPI(always("#### 142")) as api:
        run = run_tool(make_config(api_url=api.url, api_type="completions",
                                   chat_template="chatml"), ROWS,
                       args=["--chat-template", "zephyr"])
    assert run.returncode == 0, run.stderr
    assert api.calls[0]["prompt"].startswith("<|system|>")


def test_cli_api_type_chat_overrides_a_completions_config(run_tool):
    with MockAPI(always("#### 142")) as api:
        run = run_tool(make_config(api_url=api.url, api_type="completions"),
                       ROWS, args=["--api-type", "chat"])
    assert run.returncode == 0, run.stderr
    assert api.paths == ["/v1/chat/completions"]


def test_invalid_cli_api_type_exits_one(run_tool):
    with MockAPI(always("#### 142")) as api:
        run = run_tool(make_config(api_url=api.url), ROWS,
                       args=["--api-type", "responses"])
    assert run.returncode == 1


def test_invalid_cli_chat_template_exits_one(run_tool):
    with MockAPI(always("#### 142")) as api:
        run = run_tool(make_config(api_url=api.url), ROWS,
                       args=["--chat-template", "alpaca"])
    assert run.returncode == 1


# Spec: the spec's own agentic task config parses as written.
# Context: Agentic Generation, task example.
SPEC_TASK = """
tasks:
  data_lookup:
    api_url: "%s"
    model: "gpt-4"
    rpm: 60
    prompt:
      system: "You are a data analysis assistant."
      user: "{question}"
    generation:
      scheme: "agentic"
      max_iterations: 10
      temperature: 0.0
      max_tokens: 512
    evaluation:
      type: "exact_match"
      answer_field: "answer"
      extract: "last_number"
    output_field: "answer"
    tools:
      - name: "lookup"
        description: "Look up a value in the database by key"
        parameters:
          type: "object"
          properties:
            key:
              type: "string"
              description: "The database key to look up"
          required: ["key"]
        handler:
          type: "static_map"
          mapping:
            "revenue_q1": "1250000"
            "revenue_q2": "1480000"
            "employees": "142"
          default: "KEY_NOT_FOUND"

      - name: "calculate"
        description: "Evaluate a mathematical expression"
        parameters:
          type: "object"
          properties:
            expression:
              type: "string"
              description: "The math expression to evaluate"
          required: ["expression"]
        handler:
          type: "echo"
"""


def test_spec_task_example_runs(multi):
    steps = [[("lookup", {"key": "employees"})], "The company has 142."]
    with MockAPI(agentic_turns(steps)) as api:
        run = multi.run(None, {"data_lookup": ROWS},
                        config_text=SPEC_TASK % api.url)
    assert run.returncode == 0, run.stderr
    row = run.rows("data_lookup")[0]
    assert row["result"]["tool_calls"][0]["result"] == "142"
    assert row["result"]["passed"] is True
