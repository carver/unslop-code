"""Shared fixtures: config/input builders and a driver for the CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from tests.fake_api import FakeAPI, ok

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO_ROOT / "rejector.py"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def task_config(**overrides) -> dict:
    """The spec's greedy example config, with per-test overrides merged in."""
    task = {
        "name": "math_solve",
        "api_url": "http://localhost:8000",
        "model": "gpt-4",
        "rpm": 60,
        "prompt": {
            "system": "Solve the math problem. Final answer after ####.",
            "user": "{question}",
        },
        "generation": {"scheme": "greedy", "max_tokens": 256},
        "evaluation": {
            "type": "exact_match",
            "answer_field": "answer",
            "extract": "last_number",
        },
        "output_field": "solution",
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(task.get(key), dict):
            task[key] = {**task[key], **value}
        else:
            task[key] = value
    return {"task": task}


SPEC_TASKS = {
    "gsm8k": {
        "prompt": {
            "system": "Solve the math problem step by step. Put your final answer after ####.",
            "user": "{question}",
        },
        "generation": {"scheme": "rejection", "temperature": 0.7, "n": 5},
        "evaluation": {
            "type": "exact_match",
            "answer_field": "answer",
            "extract": "last_number",
        },
        "output_field": "solution",
    },
    "mmlu": {
        "prompt": {
            "system": "Answer the multiple choice question with a single letter.",
            "user": "{question}\n\nA) {a}\nB) {b}\nC) {c}\nD) {d}",
        },
        "generation": {"scheme": "greedy"},
        "evaluation": {"type": "exact_match", "answer_field": "answer", "extract": "letter"},
        "output_field": "choice",
    },
    "code_gen": {
        "prompt": {
            "system": "Write a Python function to solve the problem.",
            "user": "{problem}",
        },
        "generation": {"scheme": "rejection", "temperature": 0.8, "n": 3},
        "evaluation": {
            "type": "script",
            "command_template": 'python3 -c "{test_code}"',
            "success_exit_code": 0,
        },
        "output_field": "code",
    },
    "review": {
        "prompt": {
            "system": "You are a writing assistant. Write a response to the given prompt.",
            "user": "{prompt_text}",
        },
        "generation": {"scheme": "greedy"},
        "evaluation": {
            "type": "llm_judge",
            "judge_prompt": {
                "system": "You are a quality evaluator. Respond with only a single integer from 1 to 10.",
                "user": (
                    "Rate the quality of this response.\n\nOriginal prompt: {prompt_text}\n\n"
                    "Response:\n{__response__}\n\nCriteria: {criteria}\n\nScore:"
                ),
            },
            "threshold": 7,
            "extract": "first_number",
        },
        "output_field": "response",
    },
}

SPEC_DEFAULTS = {
    "api_url": "http://localhost:8000",
    "model": "gpt-4",
    "rpm": 60,
    "generation": {"max_tokens": 512},
}

#: Input rows that satisfy each spec task's prompt and evaluation fields.
SPEC_ROWS = {
    "gsm8k": {"question": "What is 2 + 3?", "answer": "5"},
    "mmlu": {
        "question": "What is the capital of France?",
        "a": "London", "b": "Paris", "c": "Berlin", "d": "Madrid", "answer": "B",
    },
    "code_gen": {
        "problem": "write good code",
        "test_code": "assert 'good code' in '''{__response__}'''",
    },
    "review": {"prompt_text": "Describe the sea.", "criteria": "vividness"},
}


def multi_config(*names: str, defaults: dict | None = None, tasks: dict | None = None) -> dict:
    """A `defaults` + `tasks` config built from the spec's example tasks.

    ``names`` picks spec tasks by name; ``tasks`` adds or replaces task bodies;
    ``defaults`` is merged over the spec's `defaults` section.
    """
    selected = {name: deepcopy(SPEC_TASKS[name]) for name in names}
    selected.update(deepcopy(tasks or {}))
    return {"defaults": {**deepcopy(SPEC_DEFAULTS), **(defaults or {})}, "tasks": selected}


@dataclass
class Run:
    """Result of one CLI invocation."""

    returncode: int
    stdout: str
    stderr: str
    output_path: Path

    @property
    def summary(self) -> dict:
        return json.loads(self.stdout.strip().splitlines()[-1])

    @property
    def rows(self) -> list[dict]:
        return read_jsonl(self.output_path)

    def task_rows(self, name: str) -> list[dict]:
        """Rows written to `<output_dir>/<name>.jsonl` by a multi-task run."""
        return read_jsonl(self.output_path / f"{name}.jsonl")


class CliRunner:
    """Writes config/input files into a tmp dir and invokes the CLI."""

    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path

    def write_config(self, config: dict, name: str = "task.yaml") -> Path:
        path = self.tmp_path / name
        path.write_text(
            yaml.safe_dump(config, sort_keys=False) if isinstance(config, dict) else config
        )
        return path

    def write_input(self, rows, name: str = "data.jsonl") -> Path:
        path = self.tmp_path / name
        if isinstance(rows, str):
            path.write_text(rows)
        else:
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def run(self, config, rows, *extra_args: str, output_name: str = "results.jsonl") -> Run:
        return self.invoke(
            "--config", str(self.write_config(config)),
            "--input", str(self.write_input(rows)),
            "--output", str(self.tmp_path / output_name),
            *extra_args,
            output=self.tmp_path / output_name,
        )

    def run_multi(self, config, inputs: dict, *extra_args: str, output_name: str = "results") -> Run:
        """Run a multi-task config with one `--input <task>=<path>` per named input."""
        mapping = []
        for task_name, rows in inputs.items():
            path = self.write_input(rows, name=f"{task_name}-in.jsonl")
            mapping += ["--input", f"{task_name}={path}"]
        return self.invoke(
            "--config", str(self.write_config(config)),
            *mapping,
            "--output", str(self.tmp_path / output_name),
            *extra_args,
            output=self.tmp_path / output_name,
        )

    def invoke(self, *args: str, output) -> Run:
        """Invoke the CLI with exactly `args`; `output` is where results land."""
        completed = subprocess.run(
            [sys.executable, str(ENTRYPOINT), "run", *args],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=180,
        )
        return Run(completed.returncode, completed.stdout, completed.stderr, Path(output))


@pytest.fixture
def cli(tmp_path) -> CliRunner:
    return CliRunner(tmp_path)


@pytest.fixture
def api():
    """Factory for a running FakeAPI, torn down at test end."""
    servers = []

    def start(responder=None, delay: float = 0.0) -> FakeAPI:
        server = FakeAPI(responder, delay=delay).__enter__()
        servers.append(server)
        return server

    yield start
    for server in reversed(servers):
        server.__exit__(None, None, None)


@pytest.fixture
def static_api(api):
    """A server answering every request with one canned assistant message."""

    def start(content: str, **kwargs) -> FakeAPI:
        return api(lambda index, body: ok(content, **kwargs))

    return start


#: The spec judge prompt's system message; used to tell judge calls apart.
JUDGE_MARKER = "quality evaluator"


def judge_responder(response: str, score: str, **kwargs):
    """Responder answering generation calls with `response` and judge calls with `score`."""

    def respond(index, body):
        system = body["messages"][0]["content"]
        return ok(score, **kwargs) if JUDGE_MARKER in system else ok(response)

    return respond
