"""bin/release: stamp CITATION.cff, commit only that file, tag, push, create the GitHub release."""
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "release"
mod = types.ModuleType("release")
mod.__file__ = str(SCRIPT)
sys.modules["release"] = mod
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), mod.__dict__)

CFF = """cff-version: 1.2.0
title: "Unslop Code"
type: software
authors:
  - family-names: Carver
references:
  - type: software
    version: "9.9.9"
    date-released: 1999-01-01
"""
RELEASED = CFF.replace("authors:", 'version: "0.1.0"\ndate-released: 2026-09-19\nauthors:', 1)


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A clone on main with CITATION.cff pushed to a bare origin, and fake gh and uvx on PATH."""
    fakes = tmp_path / "fakes"
    fakes.mkdir()
    (fakes / "gh").write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/gh.log\n')
    (fakes / "uvx").write_text(f"#!/bin/sh\ntest ! -e {tmp_path}/cff-invalid\n")
    for fake in fakes.iterdir():
        fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fakes}:{os.environ['PATH']}")
    for key, value in {"NAME": "t", "EMAIL": "t@example.com"}.items():
        monkeypatch.setenv(f"GIT_AUTHOR_{key}", value)
        monkeypatch.setenv(f"GIT_COMMITTER_{key}", value)
    origin, clone = tmp_path / "origin.git", tmp_path / "clone"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(clone))
    git(clone, "checkout", "-q", "-b", "main")
    (clone / "CITATION.cff").write_text(CFF)
    (clone / "notes.md").write_text("first\n")
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "-m", "start")
    git(clone, "push", "-q", "-u", "origin", "main")
    monkeypatch.setattr(mod, "ROOT", clone)
    return clone


def test_stamp_inserts_version_and_date_before_authors_and_leaves_references_alone():
    assert mod.stamp(CFF, "v0.1.0", "2026-09-19") == RELEASED


def test_stamp_replaces_the_previous_release():
    assert mod.stamp(RELEASED, "v0.2.0", "2026-10-01") == RELEASED.replace("0.1.0", "0.2.0").replace(
        "2026-09-19", "2026-10-01")


def test_release_commits_only_the_cff_then_tags_pushes_and_creates_the_release(repo, tmp_path):
    (repo / "notes.md").write_text("another agent's unstaged edit\n")
    (repo / "staged.md").write_text("another agent's staged file\n")
    git(repo, "add", "staged.md")
    mod.release("v0.1.0", "2026-09-19", zenodo_enabled=True)
    assert git(repo, "show", "--name-only", "--format=%s", "HEAD").split() == ["Release", "v0.1.0", "CITATION.cff"]
    assert git(repo, "diff", "--name-only") == "notes.md"
    assert git(repo, "diff", "--cached", "--name-only") == "staged.md"
    origin = tmp_path / "origin.git"
    assert git(origin, "show", "v0.1.0:CITATION.cff") + "\n" == RELEASED
    assert git(origin, "rev-parse", "main") == git(repo, "rev-parse", "HEAD")
    assert (tmp_path / "gh.log").read_text().split() == [
        "release", "create", "v0.1.0", "--verify-tag", "--generate-notes", "--title", "v0.1.0"]


def test_dry_run_prints_the_plan_and_changes_nothing(repo, tmp_path, capsys):
    before = git(repo, "rev-parse", "HEAD")
    mod.main(["v0.1.0", "--zenodo-enabled", "--dry-run"])
    out = capsys.readouterr().out
    assert 'version: "0.1.0"' in out and "gh release create v0.1.0" in out
    assert (repo / "CITATION.cff").read_text() == CFF
    assert git(repo, "rev-parse", "HEAD") == before and git(repo, "tag") == ""
    assert not (tmp_path / "gh.log").exists()


def test_an_invalid_cff_is_restored_and_nothing_is_committed(repo, tmp_path):
    (tmp_path / "cff-invalid").touch()
    before = git(repo, "rev-parse", "HEAD")
    with pytest.raises(SystemExit, match="does not validate"):
        mod.release("v0.1.0", "2026-09-19", zenodo_enabled=True)
    assert (repo / "CITATION.cff").read_text() == CFF
    assert git(repo, "rev-parse", "HEAD") == before and git(repo, "tag") == ""


def test_a_failed_step_names_the_commands_still_to_run(repo, tmp_path):
    (tmp_path / "fakes" / "gh").write_text("#!/bin/sh\nexit 1\n")
    with pytest.raises(SystemExit) as failure:
        mod.release("v0.1.0", "2026-09-19", zenodo_enabled=True)
    assert str(failure.value).endswith("    gh release create v0.1.0 --verify-tag --generate-notes --title v0.1.0")
    assert "git push" not in str(failure.value).split("finish with:")[1]


def test_first_release_needs_the_zenodo_flag_and_later_ones_do_not(repo):
    with pytest.raises(SystemExit, match="--zenodo-enabled"):
        mod.release("v0.1.0", "2026-09-19")
    (repo / "CITATION.cff").write_text(CFF.replace("authors:", "doi: 10.5281/zenodo.1\nauthors:", 1))
    git(repo, "commit", "-q", "-am", "doi")
    mod.release("v0.1.0", "2026-09-19")
    assert git(repo, "tag") == "v0.1.0"


@pytest.mark.parametrize("version", ["0.1.0", "v1.0", "v1.0.0-rc1", "latest"])
def test_refuses_a_version_that_is_not_vX_Y_Z(repo, version):
    with pytest.raises(SystemExit, match="vX.Y.Z"):
        mod.release(version, "2026-09-19", zenodo_enabled=True)


def test_refuses_an_existing_tag(repo):
    git(repo, "tag", "v0.1.0")
    with pytest.raises(SystemExit, match="already exists"):
        mod.release("v0.1.0", "2026-09-19", zenodo_enabled=True)


def test_refuses_a_branch_other_than_main(repo):
    git(repo, "checkout", "-q", "-b", "side")
    with pytest.raises(SystemExit, match="on main"):
        mod.release("v0.1.0", "2026-09-19", zenodo_enabled=True)


def test_refuses_uncommitted_cff_edits(repo):
    (repo / "CITATION.cff").write_text(CFF + "keywords:\n  - x\n")
    with pytest.raises(SystemExit, match="uncommitted"):
        mod.release("v0.1.0", "2026-09-19", zenodo_enabled=True)


def test_refuses_when_origin_main_has_commits_this_clone_lacks(repo, tmp_path):
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    (other / "notes.md").write_text("theirs\n")
    git(other, "commit", "-q", "-am", "theirs")
    git(other, "push", "-q")
    with pytest.raises(SystemExit, match="pull"):
        mod.release("v0.1.0", "2026-09-19", zenodo_enabled=True)


@pytest.mark.parametrize("licenses", ["license:\n  - CC-BY-4.0\n  - MIT\n", "license: [CC-BY-4.0, MIT]\n"])
def test_refuses_a_license_list_zenodo_cannot_read(repo, licenses):
    """cffconvert accepts a list, but Zenodo's reader takes one string and drops the release."""
    (repo / "CITATION.cff").write_text(CFF.replace("authors:", licenses + "authors:", 1))
    git(repo, "commit", "-q", "-am", "two licenses")
    with pytest.raises(SystemExit, match="one license"):
        mod.release("v0.1.0", "2026-09-19", zenodo_enabled=True)


def test_a_single_license_string_is_fine(repo):
    (repo / "CITATION.cff").write_text(CFF.replace("authors:", "license: CC-BY-4.0\nauthors:", 1))
    git(repo, "commit", "-q", "-am", "one license")
    mod.release("v0.1.0", "2026-09-19", zenodo_enabled=True)
    assert git(repo, "tag") == "v0.1.0"


def test_refuses_before_changing_anything_when_gh_is_missing(repo, monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: None if name == "gh" else f"/usr/bin/{name}")
    with pytest.raises(SystemExit, match="gh"):
        mod.release("v0.1.0", "2026-09-19", zenodo_enabled=True)
    assert (repo / "CITATION.cff").read_text() == CFF and git(repo, "tag") == ""


def test_a_command_that_vanishes_mid_run_still_names_the_steps_left(repo, tmp_path, monkeypatch):
    real_run = mod.subprocess.run

    def run(cmd, *args, **kwargs):
        if cmd[0] == "gh":
            raise FileNotFoundError(2, "No such file or directory", "gh")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(mod.subprocess, "run", run)
    with pytest.raises(SystemExit, match="gh release create v0.1.0"):
        mod.release("v0.1.0", "2026-09-19", zenodo_enabled=True)
    assert git(repo, "tag") == "v0.1.0"
