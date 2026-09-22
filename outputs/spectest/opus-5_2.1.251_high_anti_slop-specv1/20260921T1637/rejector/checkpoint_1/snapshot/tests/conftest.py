"""Test fixtures: a mock API server and helpers for running the CLI end to end."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class MockServer:
    """A running mock API server, addressed by ``url``."""

    def __init__(self, process: subprocess.Popen, port: int) -> None:
        self.process = process
        self.url = f"http://127.0.0.1:{port}"


@pytest.fixture
def mock_server():
    """Start mock servers with the given CLI options and shut them down afterwards."""
    processes = []

    def start(*options: str) -> MockServer:
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "tests" / "mock_server.py"), *options],
            stdout=subprocess.PIPE,
            text=True,
        )
        processes.append(process)
        return MockServer(process, int(process.stdout.readline()))

    yield start
    for process in processes:
        process.terminate()
        process.wait(timeout=5)


@pytest.fixture
def run_cli(tmp_path):
    """Write a config and input file, run the CLI, and return its result plus output rows."""

    def run(config: str, rows: list[dict], *extra_args: str):
        config_path = tmp_path / "task.yaml"
        input_path = tmp_path / "input.jsonl"
        output_path = tmp_path / "results.jsonl"
        config_path.write_text(config, encoding="utf-8")
        input_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "rejector.py"),
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
        )
        results = (
            [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
            if output_path.exists()
            else []
        )
        summary = json.loads(completed.stdout) if completed.returncode == 0 else None
        return completed, summary, results

    return run
