"""The `Performance & Memory` section."""
import os

from conftest import merge, run, write


def _big_inputs(tmp_path, n=6000):
    a = "id,tag,pad\n" + "".join(
        f"{(i * 7919) % n},a{i},{'x' * 40}\n" for i in range(n)
    )
    b = "id,tag,pad\n" + "".join(
        f"{(i * 104729) % n},b{i},{'y' * 40}\n" for i in range(n)
    )
    return {"a.csv": a, "b.csv": b}


# --- Spec: "Tool must work under small `--memory-limit-mb` (e.g., 64MB) on
#            arbitrarily large inputs" ---------------------------------------
def test_small_memory_limit_still_sorts(tmp_path):
    n = 6000
    r = merge(tmp_path, _big_inputs(tmp_path, n), "--key", "id",
              "--memory-limit-mb", "1")
    assert r.ok, r.stderr
    rows = r.rows()
    assert len(rows) == 2 * n + 1
    ids = [int(x[0]) for x in rows[1:]]
    assert ids == sorted(ids)


# --- Spec: "Sort must be stable" holds through the external merge ----------
def test_external_sort_is_stable(tmp_path):
    n = 3000
    files = {
        "a.csv": "id,tag\n" + "".join(f"{i % 10},a{i}\n" for i in range(n)),
        "b.csv": "id,tag\n" + "".join(f"{i % 10},b{i}\n" for i in range(n)),
    }
    r = merge(tmp_path, files, "--key", "id", "--memory-limit-mb", "1")
    assert r.ok, r.stderr
    rows = r.rows()[1:]
    expected = [f"a{i}" for i in range(n)] + [f"b{i}" for i in range(n)]
    expected.sort(key=lambda t: int(t[1:]) % 10)  # stable, so ties keep order
    assert [x[1] for x in rows] == expected


# --- Spec: "All intermediate resources must be cleaned up on exit" ---------
def test_temp_dir_is_left_empty(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    r = merge(tmp_path, _big_inputs(tmp_path, 4000), "--key", "id",
              "--memory-limit-mb", "1", "--temp-dir", str(scratch))
    assert r.ok, r.stderr
    assert os.listdir(scratch) == []


# --- Spec: "All intermediate resources must be cleaned up on exit" - also
#           after a failure ------------------------------------------------
def test_temp_dir_is_left_empty_after_error(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    r = merge(tmp_path, {"a.csv": "id\n1\n"}, "--key", "missing",
              "--temp-dir", str(scratch))
    assert not r.ok
    assert os.listdir(scratch) == []


# --- Spec: "--temp-dir <PATH>" is where intermediates live ----------------
def test_output_matches_regardless_of_memory_limit(tmp_path):
    files = _big_inputs(tmp_path, 2000)
    small = merge(tmp_path, files, "--key", "id,tag", "--memory-limit-mb", "1")
    large = merge(tmp_path, files, "--key", "id,tag", "--memory-limit-mb", "512")
    assert small.ok and large.ok, (small.stderr, large.stderr)
    assert small.stdout == large.stdout
