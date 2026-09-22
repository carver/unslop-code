"""Shared helpers for driving the `sith.py` CLI from tests."""
import functools
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SITH = ROOT / "sith.py"


class Result:
    """Outcome of one `sith.py` invocation."""

    def __init__(self, proc):
        self.returncode = proc.returncode
        self.stdout = proc.stdout
        self.stderr = proc.stderr

    @property
    def payload(self):
        return json.loads(self.stdout)

    @property
    def completions(self):
        return self.payload["completions"]

    @property
    def definitions(self):
        return self.payload["definitions"]

    @property
    def signatures(self):
        return self.payload["signatures"]

    @property
    def references(self):
        return self.payload["references"]

    @property
    def signature(self):
        """The single signature returned, asserting there is exactly one."""
        assert len(self.signatures) == 1, self.signatures
        return self.signatures[0]

    @property
    def changed_files(self):
        return self.payload["changed_files"]

    @property
    def renames(self):
        return self.payload["renames"]

    @property
    def errors(self):
        return self.payload["errors"]

    @property
    def places(self):
        """Each reference as a `(module_path, line, column)` tuple."""
        return [(r["module_path"], r["line"], r["column"]) for r in self.references]

    @property
    def context(self):
        return self.payload["context"]

    @property
    def environments(self):
        return self.payload["environments"]

    @property
    def only(self):
        """The single definition returned, asserting there is exactly one."""
        assert len(self.definitions) == 1, self.definitions
        return self.definitions[0]

    @property
    def definition_names(self):
        return [d["name"] for d in self.definitions]

    @property
    def names(self):
        return [c["name"] for c in self.completions]

    def by_name(self, name):
        for completion in self.completions:
            if completion["name"] == name:
                return completion
        raise AssertionError(f"{name!r} not in {self.names[:40]}")


def run_cli(*args, cwd=None):
    proc = subprocess.run(
        [sys.executable, str(SITH), *[str(a) for a in args]],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )
    return Result(proc)


def _mode_args(interpreter=False, namespaces=None, settings=None):
    """The flags shared by every analysis command: interpreter mode and settings."""
    args = []
    if interpreter:
        args.append("--interpreter")
    if namespaces is not None:
        args += ["--namespaces", str(namespaces)]
    for pair in settings or []:
        args += ["--setting", pair]
    return args


@pytest.fixture
def workdir(tmp_path):
    return tmp_path


@pytest.fixture
def complete(workdir):
    """Write `source` to a file and complete at a cursor marker or explicit position.

    The marker ``|`` in the source denotes the cursor; it is stripped before
    the file is written.  Alternatively pass explicit ``line``/``col``.
    `files` writes extra project files, and `project` passes ``--project``.
    """

    def _complete(source, line=None, col=None, fuzzy=False, name="sample.py", expect_ok=True,
                  files=None, project=None, interpreter=False, namespaces=None, settings=None):
        if line is None:
            line, col, source = _split_marker(source)
        _write_files(workdir, {name: source, **(files or {})})
        args = ["complete", str(workdir / name), line, col]
        if fuzzy:
            args.append("--fuzzy")
        if project is not None:
            args += ["--project", str(workdir / project)]
        args += _mode_args(interpreter, namespaces, settings)
        result = run_cli(*args, cwd=workdir)
        if expect_ok:
            assert result.returncode == 0, result.stderr
        return result

    return _complete


def _split_marker(source):
    lines = source.split("\n")
    for index, text in enumerate(lines):
        if "|" in text:
            col = text.index("|")
            lines[index] = text.replace("|", "", 1)
            return index + 1, col, "\n".join(lines)
    raise AssertionError("source has no '|' cursor marker")


def _write_files(workdir, files):
    for name, text in files.items():
        path = workdir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@pytest.fixture
def navigate(workdir):
    """Run `infer`/`goto` at the `|` marker, with optional extra project files."""

    def _navigate(command, source, line=None, col=None, name="sample.py", files=None,
                  expect_ok=True, project=None, follow_imports=False, interpreter=False,
                  namespaces=None, settings=None):
        if line is None:
            line, col, source = _split_marker(source)
        _write_files(workdir, {name: source, **(files or {})})
        args = [command, str(workdir / name), line, col]
        if project is not None:
            args += ["--project", str(workdir / project)]
        if follow_imports:
            args.append("--follow-imports")
        args += _mode_args(interpreter, namespaces, settings)
        result = run_cli(*args, cwd=workdir)
        if expect_ok:
            assert result.returncode == 0, result.stderr
        return result

    return _navigate


@pytest.fixture
def infer(navigate):
    return functools.partial(navigate, "infer")


@pytest.fixture
def goto(navigate):
    return functools.partial(navigate, "goto")


@pytest.fixture
def signatures(workdir):
    """Run `signatures` at the `|` marker, with optional extra project files."""

    def _signatures(source, line=None, col=None, name="sample.py", files=None,
                    project=None, expect_ok=True, interpreter=False, namespaces=None,
                    settings=None):
        if line is None:
            line, col, source = _split_marker(source)
        _write_files(workdir, {name: source, **(files or {})})
        args = ["signatures", str(workdir / name), line, col]
        if project is not None:
            args += ["--project", str(workdir / project)]
        args += _mode_args(interpreter, namespaces, settings)
        result = run_cli(*args, cwd=workdir)
        if expect_ok:
            assert result.returncode == 0, result.stderr
        return result

    return _signatures


@pytest.fixture
def references(workdir):
    """Run `references` at the `|` marker, optionally over the whole project."""

    def _references(source, line=None, col=None, name="sample.py", files=None,
                    scope=None, project=None, expect_ok=True):
        if line is None:
            line, col, source = _split_marker(source)
        _write_files(workdir, {name: source, **(files or {})})
        args = ["references", str(workdir / name), line, col]
        if scope is not None:
            args += ["--scope", scope]
        if project is not None:
            args += ["--project", str(workdir / project)]
        result = run_cli(*args, cwd=workdir)
        if expect_ok:
            assert result.returncode == 0, result.stderr
        return result

    return _references


@pytest.fixture
def search(workdir):
    """Write a set of project files and search them for a query."""

    def _search(query, files, project=None, expect_ok=True):
        _write_files(workdir, files)
        args = ["search", query]
        if project is not None:
            args += ["--project", str(workdir / project)]
        result = run_cli(*args, cwd=workdir)
        if expect_ok:
            assert result.returncode == 0, result.stderr
        return result

    return _search


@pytest.fixture
def names(workdir):
    """List the names a file defines, optionally including every scope."""

    def _names(source, name="sample.py", files=None, all_scopes=False, project=None,
               expect_ok=True):
        _write_files(workdir, {name: source, **(files or {})})
        args = ["names", str(workdir / name)]
        if all_scopes:
            args.append("--all-scopes")
        if project is not None:
            args += ["--project", str(workdir / project)]
        result = run_cli(*args, cwd=workdir)
        if expect_ok:
            assert result.returncode == 0, result.stderr
        return result

    return _names


def _split_positions(source):
    """Strip the `|` (cursor) and `$` (until) markers, returning their positions."""
    marks = []
    lines = source.split("\n")
    for index, text in enumerate(lines):
        while True:
            column = min((text.index(m) for m in "|$" if m in text), default=None)
            if column is None:
                break
            marks.append((index + 1, column))
            text = text[:column] + text[column + 1:]
        lines[index] = text
    return marks, "\n".join(lines)


class Refactoring:
    """A refactoring command run over a temporary project."""

    def __init__(self, workdir, command):
        self.workdir = workdir
        self.command = command

    def __call__(self, source, path="sample.py", files=None, project=".", diff=False,
                 expect_ok=True, cursor=None, until=None, **options):
        marks, source = _split_positions(source)
        if cursor is None:
            cursor = marks[0]
        if until is None and len(marks) > 1:
            until = marks[1]
        _write_files(self.workdir, {path: source, **(files or {})})
        args = [self.command, str(self.workdir / path), cursor[0], cursor[1]]
        if until is not None:
            args += ["--until", f"{until[0]}:{until[1]}"]
        for option, value in options.items():
            args += [f"--{option.replace('_', '-')}", value]
        if diff:
            args.append("--diff")
        if project is not None:
            args += ["--project", str(self.workdir / project)]
        result = run_cli(*args, cwd=self.workdir)
        if expect_ok:
            assert result.returncode == 0, result.stderr
        return result


@pytest.fixture
def rename(workdir):
    """Run `rename` at the `|` marker over a temporary project."""
    return Refactoring(workdir, "rename")


@pytest.fixture
def inline(workdir):
    """Run `inline` at the `|` marker over a temporary project."""
    return Refactoring(workdir, "inline")


@pytest.fixture
def extract_variable(workdir):
    """Run `extract-variable` from the `|` marker to the `$` marker."""
    return Refactoring(workdir, "extract-variable")


@pytest.fixture
def extract_function(workdir):
    """Run `extract-function` from the `|` marker to the `$` marker."""
    return Refactoring(workdir, "extract-function")


@pytest.fixture
def errors(workdir):
    """Run `errors` over a file written into the temporary project."""

    def _errors(source, name="sample.py", files=None, expect_ok=True):
        _write_files(workdir, {name: source, **(files or {})})
        result = run_cli("errors", str(workdir / name), cwd=workdir)
        if expect_ok:
            assert result.returncode == 0, result.stderr
        return result

    return _errors


@pytest.fixture
def context(workdir):
    """Run `context` at the `|` marker over a temporary project."""

    def _context(source, line=None, col=None, name="sample.py", files=None, project=None,
                 settings=None, expect_ok=True):
        if line is None:
            line, col, source = _split_marker(source)
        _write_files(workdir, {name: source, **(files or {})})
        args = ["context", str(workdir / name), line, col]
        if project is not None:
            args += ["--project", str(workdir / project)]
        args += _mode_args(settings=settings)
        result = run_cli(*args, cwd=workdir)
        if expect_ok:
            assert result.returncode == 0, result.stderr
        return result

    return _context


@pytest.fixture
def namespaces_file(workdir):
    """Write a `--namespaces` JSON document and return the path passed to the CLI."""

    def _namespaces(namespaces, name="namespaces.json"):
        path = workdir / name
        path.write_text(json.dumps(namespaces), encoding="utf-8")
        return str(path)

    return _namespaces


@pytest.fixture
def project_config(workdir):
    """Write a `.sith/project.json` under a project directory."""

    def _config(config, directory="."):
        path = workdir / directory / ".sith" / "project.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    return _config


@pytest.fixture(scope="session")
def virtualenv(tmp_path_factory):
    """A real virtualenv, created once, for the environment commands to find."""
    path = tmp_path_factory.mktemp("environments") / "created"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(path)], check=True,
        capture_output=True,
    )
    return path
