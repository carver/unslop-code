"""quality_report tests for bin/summarize: the scb-check report is computed from the snapshot on demand."""
import json
import subprocess
import sys
import types
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "summarize"
summarize = types.ModuleType("summarize")
summarize.__file__ = str(SCRIPT)
sys.modules["summarize"] = summarize
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), summarize.__dict__)

REPORT = {"total_loc": 100, "ast_grep_flagged_loc": 7, "clone_loc": 3, "verbosity": 0.1, "erosion": 0.5}


def fake_run(calls, returncode=0, stdout=None):
    stdout = json.dumps(REPORT) if stdout is None else stdout
    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="boom")
    return run


def checkpoint(tmp_path, snapshot=True):
    ck = tmp_path / "datagate" / "checkpoint_1"
    (ck / "snapshot").mkdir(parents=True) if snapshot else ck.mkdir(parents=True)
    return ck


def test_existing_report_is_read_without_running_scb_check(tmp_path, monkeypatch):
    ck = checkpoint(tmp_path)
    (ck / "quality_analysis").mkdir(); (ck / "quality_analysis" / "scb_check.json").write_text(json.dumps(REPORT))
    calls = []; monkeypatch.setattr(subprocess, "run", fake_run(calls))
    assert summarize.quality_report(ck) == REPORT
    assert calls == []


def test_missing_report_is_computed_from_snapshot_and_cached(tmp_path, monkeypatch):
    ck = checkpoint(tmp_path)
    calls = []; monkeypatch.setattr(subprocess, "run", fake_run(calls))
    assert summarize.quality_report(ck) == REPORT
    assert len(calls) == 1 and calls[0][-1] == str(ck / "snapshot") and "--include-all" in calls[0]
    assert json.loads((ck / "quality_analysis" / "scb_check.json").read_text()) == REPORT
    assert summarize.quality_report(ck) == REPORT and len(calls) == 1


def test_corrupt_report_is_recomputed(tmp_path, monkeypatch):
    ck = checkpoint(tmp_path)
    (ck / "quality_analysis").mkdir(); (ck / "quality_analysis" / "scb_check.json").write_text("")
    calls = []; monkeypatch.setattr(subprocess, "run", fake_run(calls))
    assert summarize.quality_report(ck) == REPORT
    assert len(calls) == 1


def test_no_snapshot_means_no_report(tmp_path, monkeypatch):
    ck = checkpoint(tmp_path, snapshot=False)
    calls = []; monkeypatch.setattr(subprocess, "run", fake_run(calls))
    assert summarize.quality_report(ck) is None
    assert calls == []


def test_failed_scb_check_leaves_no_file(tmp_path, monkeypatch, capsys):
    ck = checkpoint(tmp_path)
    monkeypatch.setattr(subprocess, "run", fake_run([], returncode=1, stdout=""))
    assert summarize.quality_report(ck) is None
    assert not (ck / "quality_analysis" / "scb_check.json").exists()
    assert "boom" in capsys.readouterr().err


def test_missing_uvx_preserves_existing_metrics(tmp_path, monkeypatch, capsys):
    ck = checkpoint(tmp_path)
    row = {'problem': 'datagate', 'checkpoint': 'checkpoint_1', 'idx': 1,
           'passed_tests': 50, 'erosion': 0.2}
    (tmp_path / 'checkpoint_results.jsonl').write_text(json.dumps(row) + '\n')
    def missing(*args, **kwargs):
        raise FileNotFoundError(2, 'No such file or directory', 'uvx')
    monkeypatch.setattr(subprocess, 'run', missing)
    assert summarize.load_rows(tmp_path) == [row]
    assert not (ck / 'quality_analysis/scb_check.json').exists()
    assert 'uvx' in capsys.readouterr().err
