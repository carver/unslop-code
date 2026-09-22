"""Config and CLI surface for `agentic`, `api_type` and `chat_template`."""

from __future__ import annotations

from conftest import agentic_task, base_defaults, base_task, math_task
from fake_api import FakeAPI, always, call

ROW = {"question": "How many employees?", "answer": "142"}


# Spec: "Extend the pipeline with an `agentic` generation mode"
# Context: Agentic Generation / Task example.
def test_agentic_is_an_accepted_scheme(write_config, write_input, run_cli):
    with FakeAPI(responder=always("142 employees")) as api:
        result = run_cli(write_config(agentic_task(api.url)), write_input([ROW]))
    assert result.returncode == 0


# Spec: `generation: scheme: "agentic" ... temperature: 0.0`
# Context: Agentic Generation / Task example; other non-greedy schemes reject 0.
def test_agentic_allows_temperature_zero(write_config, write_input, run_cli):
    with FakeAPI(responder=always("142 employees")) as api:
        result = run_cli(write_config(agentic_task(api.url)), write_input([ROW]))
        assert [body["temperature"] for body in api.requests] == [0.0]
    assert result.returncode == 0


# Spec: `max_iterations: 10`
# Context: Agentic Generation / Task example; an omitted value still bounds
# the loop.
def test_max_iterations_defaults_when_omitted(write_config, write_input, run_cli):
    with FakeAPI(responder=always(None, tools=(call("lookup", key="employees"),))) as api:
        task = agentic_task(api.url)
        task["generation"] = {"scheme": "agentic", "temperature": 0.0}
        result = run_cli(write_config(task), write_input([ROW]))
        assert api.call_count == 10
    assert result.rows[0]["meta"]["finish_reason"] == "max_iterations"


# Spec: "`--scheme <greedy|sample|rejection>`" extended with the new mode.
# Context: Agentic Generation; the CLI must accept it as an override.
def test_scheme_flag_accepts_agentic(write_config, write_input, run_cli):
    with FakeAPI(responder=always("142 employees")) as api:
        task = agentic_task(api.url)
        task["generation"] = {"temperature": 0.0}
        result = run_cli(write_config(task), write_input([ROW]), "--scheme", "agentic")
    assert result.returncode == 0
    assert "iterations" in result.rows[0]["result"]


# Spec: `handler: type: "static_map"` / `type: "echo"` / `type: "script"`
# Context: Handler types; anything else is a config error.
def test_unknown_handler_type_is_rejected(write_config, write_input, run_cli):
    task = agentic_task("http://127.0.0.1:1")
    task["tools"][0]["handler"] = {"type": "psychic"}
    result = run_cli(write_config(task), write_input([ROW]))
    assert result.returncode == 1
    assert "psychic" in result.stderr


# Spec: `tools: - name: "lookup" ...`
# Context: Agentic Generation / Task example; a tool needs a name.
def test_tool_without_a_name_is_rejected(write_config, write_input, run_cli):
    task = agentic_task("http://127.0.0.1:1")
    del task["tools"][0]["name"]
    result = run_cli(write_config(task), write_input([ROW]))
    assert result.returncode == 1


# Spec: `defaults: api_type: "completions"  chat_template: "llama3"`
# Context: Completions Mode / Config.
def test_defaults_carry_api_type_and_chat_template(
    write_yaml, write_inputs, run_args, workdir
):
    with FakeAPI(responder=always("#### 5")) as api:
        document = {
            "defaults": base_defaults(api.url, api_type="completions", chat_template="llama3"),
            "tasks": {"gsm8k": math_task()},
        }
        config = write_yaml(document)
        data = write_inputs({"gsm8k": [{"question": "q", "answer": "5"}]})
        run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"),
        )
        assert api.paths == ["/v1/completions"]
        assert "<|begin_of_text|>" in api.requests[0]["prompt"]


# Spec: `tasks: gsm8k: api_type: "completions"  chat_template: "chatml"`
# Context: Completions Mode / Per-task override.
def test_task_overrides_the_default_api_type(write_yaml, write_inputs, run_args, workdir):
    with FakeAPI(responder=always("#### 5")) as api:
        document = {
            "defaults": base_defaults(api.url),
            "tasks": {
                "gsm8k": math_task(api_type="completions", chat_template="chatml"),
                "mmlu": math_task(output_field="choice"),
            },
        }
        config = write_yaml(document)
        rows = [{"question": "q", "answer": "5"}]
        data = write_inputs({"gsm8k": rows, "mmlu": rows})
        run_args(
            "run", "--config", str(config), "--input-dir", str(data),
            "--output", str(workdir / "results"),
        )
        assert sorted(api.paths) == ["/v1/chat/completions", "/v1/completions"]


# Spec: "`--api-type <chat|completions>`" / "When provided, these CLI flags
# override the config values."
# Context: Completions Mode / CLI flags.
def test_api_type_flag_overrides_the_config(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        task = base_task(api.url, api_type="chat")
        data = write_input([{"question": "q", "answer": "5"}])
        run_cli(write_config(task), data, "--api-type", "completions")
        assert api.paths == ["/v1/completions"]


# Spec: "`--chat-template <chatml|llama3|mistral|zephyr>`"
# Context: Completions Mode / CLI flags.
def test_chat_template_flag_overrides_the_config(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        task = base_task(api.url, api_type="completions", chat_template="chatml")
        data = write_input([{"question": "q", "answer": "5"}])
        run_cli(write_config(task), data, "--chat-template", "mistral")
        assert api.requests[0]["prompt"].startswith("[INST] ")


# Spec: "`--api-type <chat|completions>`"
# Context: Completions Mode / CLI flags; other values are usage errors.
def test_unknown_api_type_is_rejected(write_config, write_input, run_cli):
    task = base_task("http://127.0.0.1:1")
    data = write_input([{"question": "q", "answer": "5"}])
    assert run_cli(write_config(task), data, "--api-type", "grpc").returncode != 0


# Spec: "`--chat-template <chatml|llama3|mistral|zephyr>`"
# Context: Completions Mode / CLI flags; a custom template file is out of scope.
def test_unknown_chat_template_is_rejected(write_config, write_input, run_cli):
    task = base_task("http://127.0.0.1:1")
    data = write_input([{"question": "q", "answer": "5"}])
    assert run_cli(write_config(task), data, "--chat-template", "./mine.jinja").returncode != 0


# Spec: "`--api-type <chat|completions>`" / config `api_type` defaults.
# Context: Completions Mode; without the key the chat endpoint stays in use.
def test_chat_remains_the_default_api_type(write_config, write_input, run_cli):
    with FakeAPI(responder=always("#### 5")) as api:
        data = write_input([{"question": "q", "answer": "5"}])
        run_cli(write_config(base_task(api.url)), data)
        assert api.paths == ["/v1/chat/completions"]
