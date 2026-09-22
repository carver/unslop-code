"""Shared fixtures: a mock API server and a helper that runs the CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from mock_server import MockServer, Script

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class MultiResult:
    """A run of a multi-task config, whose outputs live in a directory."""

    exit_code: int
    stdout: str
    stderr: str
    output_dir: Path

    @property
    def summary(self) -> dict:
        return json.loads(self.stdout.strip().splitlines()[-1])

    def path(self, task: str) -> Path:
        return self.output_dir / f"{task}.jsonl"

    def rows(self, task: str) -> list[dict]:
        text = self.path(task).read_text()
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def written_tasks(self) -> set[str]:
        return {path.stem for path in self.output_dir.glob("*.jsonl")}


@dataclass
class CliResult:
    exit_code: int
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


def make_config(server_url: str, **overrides) -> dict:
    """A valid greedy config against `server_url`, with `task` keys overridden."""
    task = {
        "name": "gsm8k_solve",
        "api_url": server_url,
        "model": "gpt-4",
        "rpm": 600,
        "prompt": {
            "system": "Solve the math problem. Put your final answer after ####.",
            "user": "{question}",
        },
        "generation": {"scheme": "greedy", "temperature": 0.0, "max_tokens": 512, "n": 1},
        "evaluation": {
            "type": "exact_match",
            "answer_field": "answer",
            "extract": "last_number",
        },
        "output_field": "solution",
    }
    task.update(overrides)
    return {"task": task}


@pytest.fixture
def servers():
    """Factory for mock servers; every server started is stopped at teardown."""
    started: list[MockServer] = []

    def factory(**script_kwargs) -> MockServer:
        server = MockServer(Script(**script_kwargs)).start()
        started.append(server)
        return server

    yield factory
    for server in started:
        server.stop()


@pytest.fixture
def server(servers) -> MockServer:
    return servers()


@pytest.fixture
def run_cli(tmp_path):
    """Run `python rejector.py run ...` against files written under tmp_path."""

    def runner(config, rows, *extra_args, timeout=120) -> CliResult:
        config_path = tmp_path / "task.yaml"
        input_path = tmp_path / "data.jsonl"
        output_path = tmp_path / "results.jsonl"
        config_path.write_text(
            config if isinstance(config, str) else yaml.safe_dump(config)
        )
        input_path.write_text(
            rows
            if isinstance(rows, str)
            else "".join(json.dumps(row) + "\n" for row in rows)
        )
        proc = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "rejector.py"),
                "run",
                "--config",
                str(config_path),
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                *extra_args,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=PROJECT_ROOT,
        )
        return CliResult(proc.returncode, proc.stdout, proc.stderr, output_path)

    return runner


def make_multi_config(server_url: str, tasks: dict, **defaults) -> dict:
    """A `defaults` + `tasks` config: shared connection settings plus tasks."""
    shared = {
        "api_url": server_url,
        "model": "gpt-4",
        "rpm": 600,
        "generation": {"max_tokens": 512},
    }
    shared.update(defaults)
    return {"defaults": shared, "tasks": tasks}


def exact_match_task(**overrides) -> dict:
    """A greedy `exact_match` task body, for configs that need a second task."""
    task = {
        "prompt": {"system": "Solve it.", "user": "{question}"},
        "generation": {"scheme": "greedy"},
        "evaluation": {
            "type": "exact_match",
            "answer_field": "answer",
            "extract": "last_number",
        },
        "output_field": "solution",
    }
    task.update(overrides)
    return task


@pytest.fixture
def run_multi(tmp_path):
    """Run the CLI over a multi-task config, in mapping or directory mode."""

    def runner(
        config,
        inputs: dict,
        *extra_args,
        mode: str = "mapping",
        output: Path | None = None,
        timeout: int = 120,
    ) -> MultiResult:
        config_path = tmp_path / "multi.yaml"
        config_path.write_text(
            config if isinstance(config, str) else yaml.safe_dump(config)
        )
        data_dir = tmp_path / "data"
        data_dir.mkdir(exist_ok=True)
        input_args = []
        for task, rows in inputs.items():
            path = data_dir / f"{task}.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            if mode == "mapping":
                input_args += ["--input", f"{task}={path}"]
        if mode == "dir":
            input_args = ["--input-dir", str(data_dir)]

        output_dir = tmp_path / "results" if output is None else output
        proc = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "rejector.py"),
                "run",
                "--config",
                str(config_path),
                *input_args,
                "--output",
                str(output_dir),
                *extra_args,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=PROJECT_ROOT,
        )
        return MultiResult(proc.returncode, proc.stdout, proc.stderr, output_dir)

    return runner
