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
