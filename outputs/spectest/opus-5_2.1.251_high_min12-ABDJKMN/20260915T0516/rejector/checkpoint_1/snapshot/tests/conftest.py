"""Shared fixtures: config/input builders and a CLI runner."""
import json
import os
import subprocess
import sys

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REJECTOR = os.path.join(ROOT, "rejector.py")
sys.path.insert(0, ROOT)


class Run:
    """The result of one `rejector.py run` invocation."""

    def __init__(self, proc, output_path):
        self.proc = proc
        self.output_path = output_path

    @property
    def returncode(self):
        return self.proc.returncode

    @property
    def stdout(self):
        return self.proc.stdout

    @property
    def stderr(self):
        return self.proc.stderr

    @property
    def summary(self):
        """The single JSON summary object printed to stdout."""
        text = self.stdout.strip()
        assert text, "expected a JSON summary on stdout, got nothing"
        return json.loads(text)

    @property
    def rows(self):
        """The parsed JSONL output rows."""
        with open(self.output_path) as fh:
            return [json.loads(line) for line in fh if line.strip()]

    @property
    def output_exists(self):
        return os.path.exists(self.output_path)


def make_config(api_url="http://localhost:8000", model="gpt-4", rpm=60,
                system="Solve the math problem. Put your final answer after ####.",
                user="{question}", scheme="greedy", temperature=None,
                max_tokens=512, n=None, evaluation="default",
                output_field="solution", name="gsm8k_solve"):
    """Build a task config dict; pass None to drop an optional key."""
    generation = {"scheme": scheme, "max_tokens": max_tokens}
    if temperature is not None:
        generation["temperature"] = temperature
    if n is not None:
        generation["n"] = n
    prompt = {}
    if system is not None:
        prompt["system"] = system
    if user is not None:
        prompt["user"] = user
    task = {
        "name": name,
        "api_url": api_url,
        "model": model,
        "rpm": rpm,
        "prompt": prompt,
        "generation": generation,
    }
    if evaluation == "default":
        evaluation = {"type": "exact_match", "answer_field": "answer",
                      "extract": "last_number"}
    if evaluation is not None:
        task["evaluation"] = evaluation
    if output_field is not None:
        task["output_field"] = output_field
    return {"task": task}


@pytest.fixture
def workdir(tmp_path):
    return tmp_path


@pytest.fixture
def write_files(workdir):
    def _write(config, rows, config_text=None, input_text=None):
        cfg_path = workdir / "task.yaml"
        if config_text is not None:
            cfg_path.write_text(config_text)
        else:
            cfg_path.write_text(yaml.safe_dump(config, sort_keys=False))
        in_path = workdir / "data.jsonl"
        if input_text is not None:
            in_path.write_text(input_text)
        else:
            in_path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return str(cfg_path), str(in_path)
    return _write


@pytest.fixture
def run_tool(workdir, write_files):
    """Run the CLI end to end and return a `Run`."""
    def _run(config=None, rows=(), args=(), config_text=None, input_text=None,
             output_name="results.jsonl", timeout=120):
        cfg_path, in_path = write_files(config, list(rows), config_text, input_text)
        out_path = str(workdir / output_name)
        cmd = [sys.executable, REJECTOR, "run",
               "--config", cfg_path, "--input", in_path, "--output", out_path]
        cmd += [str(a) for a in args]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              cwd=str(workdir))
        return Run(proc, out_path)
    return _run
