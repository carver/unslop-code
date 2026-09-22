"""install.py: a patch applies once, reports itself already applied after, and names a failure."""
import subprocess
import sys
import types

import pytest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "install.py"
mod = types.ModuleType("install_tool")
mod.__file__ = str(SCRIPT)
sys.modules["install_tool"] = mod
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), mod.__dict__)

PATCH = """--- a/greeting.txt
+++ b/greeting.txt
@@ -1 +1 @@
-hello
+hello, world
"""


def test_apply_patch_once_then_already_applied_then_failure(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "greeting.txt").write_text("hello\n")
    patch = tmp_path / "greet.patch"
    patch.write_text(PATCH)
    assert mod.apply_patch(patch, tree) == "applied"
    assert (tree / "greeting.txt").read_text() == "hello, world\n"
    assert mod.apply_patch(patch, tree) == "already applied"
    (tree / "greeting.txt").write_text("goodbye\n")
    assert mod.apply_patch(patch, tree).startswith("failed: ")
    assert (tree / "greeting.txt").read_text() == "goodbye\n"


def test_harness_patches_are_the_eight_in_readme_order():
    names = [p.name for p in mod.HARNESS_PATCHES]
    assert names[0] == "claude-code-stream-parser-string-message.patch" and names[1] == "stop-after-checkpoint.patch"
    assert names[-2:] == ["exec-log-masks-secrets.patch", "run-records-harness-provenance.patch"]
    assert len(names) == 8 and all(p.exists() for p in mod.HARNESS_PATCHES)


def test_install_hooks_points_the_repo_at_the_tracked_hooks(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    mod.install_hooks(tmp_path)
    query = ["git", "-C", str(tmp_path), "config", "core.hooksPath"]
    got = subprocess.run(query, capture_output=True, text=True).stdout
    assert got.strip() == ".githooks"


def test_gitleaks_install_refuses_a_download_with_the_wrong_checksum(tmp_path, monkeypatch):
    import io
    import tarfile

    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as tar:
        info = tarfile.TarInfo("gitleaks")
        info.size = 4
        tar.addfile(info, io.BytesIO(b"bin\n"))
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(payload.getvalue()))
    with pytest.raises(SystemExit, match="sha256"):
        mod.install_gitleaks(tmp_path, sha256="0" * 64)
    assert not (tmp_path / "gitleaks").exists()
    mod.install_gitleaks(tmp_path, sha256=mod.hashlib.sha256(payload.getvalue()).hexdigest())
    assert (tmp_path / "gitleaks").read_bytes() == b"bin\n" and (tmp_path / "gitleaks").stat().st_mode & 0o111
