"""Shared fixtures: config/input writers and a subprocess runner for the CLI."""

import json
import os
import subprocess
import sys

import pytest
import yaml

from fake_api import FakeAPI  # noqa: F401  (re-exported for tests)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REJECTOR = os.path.join(REPO, "rejector.py")


class RunResult:
    """Outcome of one `python rejector.py run ...` invocation."""

    def __init__(self, proc, output_path):
        self.returncode = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr
        self._output_path = output_path

    @property
    def summary(self):
        """The JSON summary object printed on stdout."""
        text = self.stdout.strip()
        assert text, "expected a JSON summary on stdout, got nothing"
        # Tolerate other stdout lines; the summary is the last JSON object.
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)
        raise AssertionError("no JSON object on stdout: %r" % text)

    @property
    def rows(self):
        """Parsed JSONL output rows."""
        with open(self._output_path) as fh:
            return [json.loads(l) for l in fh if l.strip()]

    @property
    def output_exists(self):
        return os.path.exists(self._output_path)


@pytest.fixture
def workdir(tmp_path):
    return tmp_path


@pytest.fixture
def write_config(workdir):
    """Write a task config; returns the path.

    `task` is merged over a working default so tests only state what matters.
    """
    def _write(task=None, name="task.yaml", raw=None):
        path = workdir / name
        if raw is not None:
            path.write_text(raw)
            return str(path)
        base = {
            "name": "gsm8k_solve",
            "api_url": "http://localhost:1",
            "model": "gpt-4",
            "rpm": 60,
            "prompt": {
                "system": "Solve the math problem. Put your final answer after ####.",
                "user": "{question}",
            },
            "generation": {"scheme": "greedy", "temperature": 0.0,
                           "max_tokens": 512, "n": 1},
            "evaluation": {"type": "exact_match", "answer_field": "answer",
                           "extract": "last_number"},
            "output_field": "solution",
        }
        merged = dict(base)
        for k, v in (task or {}).items():
            if v is None:
                merged.pop(k, None)
            elif isinstance(v, dict) and isinstance(merged.get(k), dict):
                sub = dict(merged[k])
                for sk, sv in v.items():
                    if sv is None:
                        sub.pop(sk, None)
                    else:
                        sub[sk] = sv
                merged[k] = sub
            else:
                merged[k] = v
        path.write_text(yaml.safe_dump({"task": merged}, sort_keys=False))
        return str(path)
    return _write


@pytest.fixture
def write_input(workdir):
    """Write a JSONL input file; returns the path."""
    def _write(rows, name="data.jsonl", raw=None):
        path = workdir / name
        if raw is not None:
            path.write_text(raw)
            return str(path)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return str(path)
    return _write


@pytest.fixture
def run_cli(workdir):
    """Invoke the CLI as a subprocess and return a RunResult."""
    def _run(*args, output=None, timeout=120, check=None):
        out = output or str(workdir / "results.jsonl")
        argv = [sys.executable, REJECTOR] + [str(a) for a in args]
        if "--output" not in argv:
            argv += ["--output", out]
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, cwd=str(workdir))
        res = RunResult(proc, out)
        if check is not None:
            assert res.returncode == check, (
                "exit %d (expected %d)\nstdout: %s\nstderr: %s"
                % (res.returncode, check, res.stdout, res.stderr))
        return res
    return _run


@pytest.fixture
def run_task(run_cli, write_config, write_input):
    """Config + input + server -> RunResult, the common end-to-end path."""
    def _run(server=None, task=None, rows=None, extra=(), check=None,
             api_url=None, config_raw=None, input_raw=None):
        task = dict(task or {})
        if server is not None and "api_url" not in task:
            task["api_url"] = server.url
        if api_url is not None:
            task["api_url"] = api_url
        cfg = write_config(task, raw=config_raw)
        if rows is None and input_raw is None:
            rows = [{"question": "What is 2 + 3?", "answer": "5"}]
        inp = write_input(rows, raw=input_raw)
        return run_cli("run", "--config", cfg, "--input", inp,
                       *extra, check=check)
    return _run
