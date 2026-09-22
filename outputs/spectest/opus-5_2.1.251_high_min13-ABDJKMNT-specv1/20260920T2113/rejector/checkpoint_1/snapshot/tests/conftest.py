"""Shared fixtures: config/input builders and a driver for the CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from tests.fake_api import FakeAPI, ok

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO_ROOT / "rejector.py"


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
        text = self.output_path.read_text()
        return [json.loads(line) for line in text.splitlines() if line.strip()]


class CliRunner:
    """Writes config/input files into a tmp dir and invokes the CLI."""

    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path

    def write_config(self, config: dict, name: str = "task.yaml") -> Path:
        path = self.tmp_path / name
        path.write_text(yaml.safe_dump(config) if isinstance(config, dict) else config)
        return path

    def write_input(self, rows, name: str = "data.jsonl") -> Path:
        path = self.tmp_path / name
        if isinstance(rows, str):
            path.write_text(rows)
        else:
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        return path

    def run(self, config, rows, *extra_args: str, output_name: str = "results.jsonl") -> Run:
        config_path = self.write_config(config)
        input_path = self.write_input(rows)
        output_path = self.tmp_path / output_name
        completed = subprocess.run(
            [
                sys.executable, str(ENTRYPOINT), "run",
                "--config", str(config_path),
                "--input", str(input_path),
                "--output", str(output_path),
                *extra_args,
            ],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=180,
        )
        return Run(completed.returncode, completed.stdout, completed.stderr, output_path)


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
