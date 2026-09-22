"""bin/harness-provenance: the record bin/scb hands each run names the harness build it ran."""
import hashlib
import json
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "harness-provenance"
mod = types.ModuleType("harness_provenance")
mod.__file__ = str(SCRIPT)
sys.modules["harness_provenance"] = mod
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), mod.__dict__)


def git(tree, *args):
    return subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True, check=True).stdout.strip()


def make_harness(tmp_path):
    tree = tmp_path / "harness"
    tree.mkdir()
    git(tree, "init", "-q")
    (tree / "run.py").write_text("print('upstream')\n")
    git(tree, "add", "run.py")
    git(tree, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "upstream")
    return tree


def make_patch(tmp_path, name, text):
    patch = tmp_path / f"{name}.patch"
    patch.write_text(text)
    return patch


def test_record_names_the_commit_and_each_patch_by_hash(tmp_path):
    tree = make_harness(tmp_path)
    patch = make_patch(tmp_path, "fix", "a patch\n")
    record = mod.provenance(tree, [patch], ["run", "--config", "x.yaml"])
    assert record["harness_commit"] == git(tree, "rev-parse", "HEAD")
    assert record["patches"] == [{"name": "fix.patch", "sha256": hashlib.sha256(b"a patch\n").hexdigest()}]
    assert record["argv"] == ["run", "--config", "x.yaml"]
    json.dumps(record)


def test_tree_hash_moves_with_any_edit_to_the_checkout(tmp_path):
    tree = make_harness(tmp_path)
    clean = mod.provenance(tree, [], [])["tree_diff_sha256"]
    (tree / "run.py").write_text("print('patched')\n")
    edited = mod.provenance(tree, [], [])["tree_diff_sha256"]
    (tree / "new_module.py").write_text("x = 1\n")
    added = mod.provenance(tree, [], [])["tree_diff_sha256"]
    assert len({clean, edited, added}) == 3


def test_tree_hash_ignores_what_git_ignores(tmp_path):
    tree = make_harness(tmp_path)
    (tree / ".git" / "info" / "exclude").write_text("__pycache__/\n")
    before = mod.provenance(tree, [], [])["tree_diff_sha256"]
    (tree / "__pycache__").mkdir()
    (tree / "__pycache__" / "run.cpython-312.pyc").write_bytes(b"\0")
    assert mod.provenance(tree, [], [])["tree_diff_sha256"] == before


def test_the_default_patch_list_is_install_pys(tmp_path):
    assert mod.harness_patches() == mod.install.HARNESS_PATCHES
