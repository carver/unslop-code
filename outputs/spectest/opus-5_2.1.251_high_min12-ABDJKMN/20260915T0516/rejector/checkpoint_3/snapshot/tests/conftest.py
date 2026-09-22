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
                output_field="solution", name="gsm8k_solve", icl=None,
                num_solutions=None, max_attempts=None):
    """Build a task config dict; pass None to drop an optional key."""
    generation = {"scheme": scheme, "max_tokens": max_tokens}
    if temperature is not None:
        generation["temperature"] = temperature
    if n is not None:
        generation["n"] = n
    if max_attempts is not None:
        generation["max_attempts"] = max_attempts
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
    if icl is not None:
        task["icl"] = icl
    if num_solutions is not None:
        task["num_solutions"] = num_solutions
    return {"task": task}


# ------------------------------------------------------- part 3 helpers ---

def icl_setup(name, examples=None, file=None, question_field="question"):
    """One ICL setup: `examples` is a list of (input_dict_or_text, output)."""
    setup = {"name": name}
    if examples is not None:
        built = []
        for item in examples:
            inp, out = item
            if not isinstance(inp, dict):
                inp = {question_field: inp}
            built.append({"input": inp, "output": out})
        setup["examples"] = built
    if file is not None:
        setup["file"] = file
    return setup


def icl_block(setups, k=None, strategy=None):
    """An `icl` config block; pass None to leave a key out."""
    block = {"setups": list(setups)}
    if k is not None:
        block["k"] = k
    if strategy is not None:
        block["strategy"] = strategy
    return block


def marker_setups(names, per_setup=1):
    """Setups whose assistant turns are identifiable markers, e.g. `MARK_A`.

    The k-th example of setup `A` answers `MARK_A{k}`, so a mock responder can
    tell which setup produced a request and a test can read the turn order.
    """
    setups = []
    for name in names:
        examples = [({"question": "demo %s %d" % (name, i)},
                     "MARK_%s%d" % (name, i)) for i in range(per_setup)]
        setups.append(icl_setup(name, examples))
    return setups


def setup_of(payload, names):
    """Which marker setup a recorded request payload used (or None)."""
    for message in payload.get("messages", []):
        if message.get("role") != "assistant":
            continue
        for name in names:
            if ("MARK_%s" % name) in (message.get("content") or ""):
                return name
    return None


def setup_order(api, names):
    """The marker setup used by each recorded request, in call order."""
    return [setup_of(payload, names) for payload in api.calls]


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


# ------------------------------------------------------- part 2 helpers ---

def make_multi_config(defaults=None, tasks=None, api_url="http://localhost:8000"):
    """Build a `defaults` + `tasks` multi-task config dict."""
    base = {"api_url": api_url, "model": "gpt-4", "rpm": 60,
            "generation": {"max_tokens": 512}}
    if defaults is not None:
        base = merge_dicts(base, defaults)
    if tasks is None:
        tasks = {
            "gsm8k": {
                "prompt": {"system": "Solve the math problem.",
                           "user": "{question}"},
                "generation": {"scheme": "greedy"},
                "evaluation": {"type": "exact_match", "answer_field": "answer",
                               "extract": "last_number"},
                "output_field": "solution",
            },
            "mmlu": {
                "prompt": {"system": "Answer with a single letter.",
                           "user": "{question}"},
                "generation": {"scheme": "greedy"},
                "evaluation": {"type": "exact_match", "answer_field": "answer",
                               "extract": "letter"},
                "output_field": "choice",
            },
        }
    return {"defaults": base, "tasks": tasks}


def merge_dicts(base, overlay):
    """One-level-deep merge, as the spec describes for nested sections."""
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def script_task(command_template="python3 -c \"{test_code}\"",
                success_exit_code=0, scheme="greedy", **generation):
    gen = {"scheme": scheme}
    gen.update(generation)
    evaluation = {"type": "script", "command_template": command_template}
    if success_exit_code is not None:
        evaluation["success_exit_code"] = success_exit_code
    return {
        "prompt": {"system": "Write code.", "user": "{problem}"},
        "generation": gen,
        "evaluation": evaluation,
        "output_field": "code",
    }


def judge_task(threshold=7, extract="first_number", model=None,
               scheme="greedy", judge_system="JUDGE. Respond with an integer.",
               judge_user="Rate this response:\n{__response__}\n\n"
                          "Criteria: {criteria}\n\nScore:", **generation):
    gen = {"scheme": scheme}
    gen.update(generation)
    judge_prompt = {"user": judge_user}
    if judge_system is not None:
        judge_prompt["system"] = judge_system
    evaluation = {"type": "llm_judge", "judge_prompt": judge_prompt,
                  "threshold": threshold}
    if extract is not None:
        evaluation["extract"] = extract
    if model is not None:
        evaluation["model"] = model
    return {
        "prompt": {"system": "Write a response.", "user": "{prompt_text}"},
        "generation": gen,
        "evaluation": evaluation,
        "output_field": "response",
    }


class MultiRun:
    """The result of one multi-task `rejector.py run` invocation."""

    def __init__(self, proc, out_dir):
        self.proc = proc
        self.out_dir = str(out_dir)

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
        text = self.stdout.strip()
        assert text, "expected a JSON summary on stdout, got nothing"
        return json.loads(text)

    def path(self, task):
        return os.path.join(self.out_dir, "%s.jsonl" % task)

    def exists(self, task):
        return os.path.exists(self.path(task))

    def rows(self, task):
        with open(self.path(task)) as fh:
            return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture
def cli(workdir):
    """Run rejector.py with arbitrary argv; returns the CompletedProcess."""
    def _cli(*args, timeout=120):
        cmd = [sys.executable, REJECTOR] + [str(a) for a in args]
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, cwd=str(workdir))
    return _cli


@pytest.fixture
def multi(workdir, cli):
    """Write a multi-task config plus per-task inputs, then run the CLI."""
    class Harness:
        def __init__(self):
            self.workdir = workdir
            self.data_dir = workdir / "data"
            self.out_dir = workdir / "results"

        def write_config(self, config, name="multi.yaml", text=None):
            path = self.workdir / name
            path.write_text(text if text is not None
                            else yaml.safe_dump(config, sort_keys=False))
            return str(path)

        def write_input(self, task, rows, directory=None, filename=None):
            directory = self.data_dir if directory is None else directory
            os.makedirs(str(directory), exist_ok=True)
            path = os.path.join(str(directory),
                                filename or ("%s.jsonl" % task))
            with open(path, "w") as fh:
                for row in rows:
                    fh.write(json.dumps(row) + "\n")
            return path

        def run(self, config, inputs, args=(), mode="explicit",
                output=None, timeout=120, config_text=None):
            cfg_path = self.write_config(config, text=config_text)
            paths = {task: self.write_input(task, rows)
                     for task, rows in inputs.items()}
            out = str(self.out_dir if output is None else output)
            argv = ["run", "--config", cfg_path, "--output", out]
            if mode == "explicit":
                for task, path in paths.items():
                    argv += ["--input", "%s=%s" % (task, path)]
            elif mode == "dir":
                argv += ["--input-dir", str(self.data_dir)]
            argv += [str(a) for a in args]
            return MultiRun(cli(*argv, timeout=timeout), out)

    return Harness()
