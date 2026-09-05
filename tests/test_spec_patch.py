"""bin/spec-patch builds one spec version from the cache and its folder of patches."""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "spec-patch"


def make_cache(tmp_path):
    cache = tmp_path / "cache"; (cache / "toy").mkdir(parents=True)
    (cache / "toy" / "checkpoint_1.md").write_text("alpha\nbeta\ngamma\n")
    return cache


def patch_text(old, new):
    return f"--- a/toy/checkpoint_1.md\n+++ b/toy/checkpoint_1.md\n@@ -1,3 +1,3 @@\n alpha\n-{old}\n+{new}\n gamma\n"


def run(tmp_path, version):
    env = {**os.environ, "SCBENCH_CACHE_PROBLEMS": str(tmp_path / "cache"), "SCBENCH_SPECS_ROOT": str(tmp_path / "specs")}
    return subprocess.run([str(SCRIPT), "toy", version], capture_output=True, text=True, env=env)


def test_patches_apply_in_filename_order_into_the_version_root(tmp_path):
    make_cache(tmp_path)
    v = tmp_path / "specs" / "v2"; v.mkdir(parents=True)
    (v / "01-toy-first.patch").write_text(patch_text("beta", "BETA"))
    (v / "02-toy-second.patch").write_text(patch_text("BETA", "delta"))
    r = run(tmp_path, "v2")
    assert r.returncode == 0, r.stderr
    assert (v / "problems" / "toy" / "checkpoint_1.md").read_text() == "alpha\ndelta\ngamma\n"
    assert "2 patch(es)" in r.stdout and str(v / "problems") in r.stdout


def test_a_hunk_that_does_not_apply_fails_the_build(tmp_path):
    make_cache(tmp_path)
    v = tmp_path / "specs" / "v3"; v.mkdir(parents=True)
    (v / "01-toy-wrong.patch").write_text(patch_text("nothing-here", "x"))
    assert run(tmp_path, "v3").returncode != 0


def test_unknown_version_is_an_error(tmp_path):
    make_cache(tmp_path)
    assert run(tmp_path, "v9").returncode == 2
