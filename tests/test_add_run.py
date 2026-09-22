"""bin/add-run: a run goes into git redacted, allowlisted, with diff metadata, and rebuildable."""
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "add-run"
mod = types.ModuleType("add_run")
mod.__file__ = str(SCRIPT)
sys.modules["add_run"] = mod
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), mod.__dict__)

TOKEN = "sk-ant-oat01-" + "Ab3_" * 20
RUN = "outputs/spectest/opus-5_2.1.251_high_min12/20260922T1200"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "user.email", "t@t")
    write(repo / ".gitignore", "outputs/\n")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-q", "-m", "init")
    run = repo / RUN
    write(run / "checkpoint_results.jsonl", '{"problem": "xjq", "checkpoint": "checkpoint_1"}\n')
    write(run / "config.yaml", "model: opus-5\n")
    write(run / "harness_provenance.jsonl", '{"harness_commit": "06b5c06"}\n')
    write(run / "xjq" / "infer.log", f'{{"event": "Built docker exec command CLAUDE_CODE_OAUTH_TOKEN={TOKEN}"}}\n')
    for n, code in ((1, "print(1)\n"), (2, "print(2)\n")):
        ck = run / "xjq" / f"checkpoint_{n}"
        write(ck / "snapshot" / "xjq.py", code)
        write(ck / "snapshot" / "__pycache__" / "xjq.cpython-312.pyc", "\0")
        write(ck / "prompt.txt", "solve it\n")
        write(ck / "evaluation.json", '{"pass_counts": {"Core": 1}}\n')
        write(ck / "agent" / "stderr.log", "")
        write(ck / "agent" / "stdout.jsonl", '{"transcript": true}\n')
        write(ck / "agent" / "workspace" / "projects" / "-workspace" / "s.jsonl", "{}\n")
        write(ck / "evaluation" / "report.json", "{}\n")
        write(ck / "quality_analysis" / "symbols.jsonl", "{}\n")
        write(ck / "quality_analysis" / "overall_quality.json", "{}\n")
        write(ck / "qa" / "20260922T120000.md", "# Question\n")
    return repo, run


def fake_diffs(run):
    """diff.json the way a strict run writes it: every checkpoint against an empty workspace."""
    from slop_code.execution.snapshot import create_diff_from_directories

    for ck in (run / "xjq").glob("checkpoint_*"):
        (ck / "diff.json").write_text(create_diff_from_directories(None, ck / "snapshot").model_dump_json())


def tracked(repo):
    return set(git(repo, "ls-files", "outputs").split())


def test_selected_files_keep_code_and_scores_and_leave_out_the_rest(tmp_path):
    repo, run = make_repo(tmp_path)
    write(run / "xjq" / "checkpoint_1" / "diff.json", "{}")
    write(run / "xjq" / "checkpoint_1" / "diff_meta.json", "{}")
    names = {str(p.relative_to(run)) for p in mod.selected_files(run)}
    assert "xjq/checkpoint_1/snapshot/xjq.py" in names and "checkpoint_results.jsonl" in names
    assert {"harness_provenance.jsonl", "xjq/infer.log", "xjq/checkpoint_1/diff_meta.json"} <= names
    assert {"xjq/checkpoint_1/qa/20260922T120000.md", "xjq/checkpoint_1/agent/stderr.log"} <= names
    assert not any(
        part in name
        for name in names
        for part in ("stdout.jsonl", "workspace/", "__pycache__", "evaluation/", "symbols.jsonl", "diff.json")
    )


def test_redact_replaces_every_claude_token_and_keeps_the_mtime(tmp_path):
    repo, run = make_repo(tmp_path)
    log = run / "xjq" / "infer.log"
    mtime = log.stat().st_mtime_ns
    assert mod.redact([log]) == 1
    assert TOKEN not in log.read_text() and "CLAUDE_CODE_OAUTH_TOKEN=***redacted***" in log.read_text()
    assert log.stat().st_mtime_ns == mtime
    assert mod.redact([log]) == 0


def test_a_run_still_being_written_is_refused(tmp_path):
    repo, run = make_repo(tmp_path)
    with pytest.raises(SystemExit, match="written"):
        mod.check_idle(run, quiet_seconds=3600)
    mod.check_idle(run, quiet_seconds=0)


def test_a_run_outside_outputs_is_refused(tmp_path):
    repo, run = make_repo(tmp_path)
    with pytest.raises(SystemExit, match="outputs"):
        mod.run_path(repo, str(repo / "elsewhere"))


def test_something_else_staged_stops_the_tool(tmp_path):
    repo, run = make_repo(tmp_path)
    write(repo / "notes.md", "draft\n")
    git(repo, "add", "notes.md")
    with pytest.raises(SystemExit, match="notes.md"):
        mod.check_index_clean(repo)


needs_harness = pytest.mark.skipif(not mod.harness_available(), reason="run under ~/.venvs/scbench-harness/bin/python")
needs_gitleaks = pytest.mark.skipif(shutil.which("gitleaks") is None and not mod.GITLEAKS.exists(),
                                    reason="gitleaks not installed (python3 install.py)")


@needs_harness
@needs_gitleaks
def test_add_commits_the_allowlisted_redacted_run_and_remove_takes_it_out(tmp_path):
    repo, run = make_repo(tmp_path)
    fake_diffs(run)
    mod.add(repo, [run], complete=lambda r: True, quiet_seconds=0)
    files = tracked(repo)
    assert f"{RUN}/xjq/checkpoint_2/snapshot/xjq.py" in files and f"{RUN}/xjq/checkpoint_2/diff_meta.json" in files
    assert not any("stdout.jsonl" in f or "__pycache__" in f or f.endswith("/diff.json") for f in files)
    assert TOKEN not in git(repo, "show", f"HEAD:{RUN}/xjq/infer.log")
    assert json.loads((run / "xjq" / "checkpoint_2" / "diff_meta.json").read_text())["base"] == "empty"
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "log", "-1", "--format=%s") == "outputs: add 1 run\n"
    mod.add(repo, [run], complete=lambda r: True, quiet_seconds=0)  # again: nothing new, no commit
    assert git(repo, "rev-list", "--count", "HEAD") == "2\n"
    write(run / "xjq" / "checkpoint_1" / "qa" / "20260923T090000.md", "# Another question\n")
    mod.add(repo, [run], complete=lambda r: True, quiet_seconds=0)
    assert git(repo, "log", "-1", "--format=%s") == "outputs: update 1 run\n"
    mod.remove(repo, [run])
    assert tracked(repo) == set() and (run / "xjq" / "checkpoint_1" / "snapshot" / "xjq.py").exists()


@needs_harness
@needs_gitleaks
def test_a_secret_gitleaks_finds_stops_the_commit_and_unstages_the_run(tmp_path):
    repo, run = make_repo(tmp_path)
    write(run / "xjq" / "checkpoint_2" / "snapshot" / "config.py", 'GITHUB = "ghp_' + "a1B2c3D4e5" * 4 + '"\n')
    fake_diffs(run)
    with pytest.raises(SystemExit, match="gitleaks"):
        mod.add(repo, [run], complete=lambda r: True, quiet_seconds=0)
    assert tracked(repo) == set() and git(repo, "rev-list", "--count", "HEAD") == "1\n"


@needs_harness
def test_a_partial_run_is_refused_before_anything_changes(tmp_path):
    repo, run = make_repo(tmp_path)
    fake_diffs(run)
    with pytest.raises(SystemExit, match="partial"):
        mod.add(repo, [run], complete=lambda r: False, quiet_seconds=0)
    assert TOKEN in (run / "xjq" / "infer.log").read_text() and tracked(repo) == set()
