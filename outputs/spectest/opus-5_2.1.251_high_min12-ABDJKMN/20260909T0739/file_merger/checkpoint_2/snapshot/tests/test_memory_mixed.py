"""`Performance & Memory` for heterogeneous inputs."""
import os

from conftest import merge_paths, write, write_jsonl, write_parquet


# --- Spec: "Implementation must work with --memory-limit-mb as low as 64
#            and terabyte-scale inputs" ------------------------------------
def test_mixed_sources_sort_under_a_small_memory_limit(tmp_path):
    n = 2000
    csv_text = "id,tag\n" + "".join(f"{(i * 7919) % n},c{i}\n" for i in range(n))
    c = write(tmp_path, "a.csv", csv_text)
    j = write_jsonl(tmp_path, "b.jsonl",
                    [{"id": (i * 104729) % n, "tag": f"j{i}"} for i in range(n)])
    p = write_parquet(tmp_path, "c.parquet",
                      [{"id": (i * 31) % n, "tag": f"p{i}"} for i in range(n)],
                      row_group_size=97)
    r = merge_paths([c, j, p], "--key", "id", "--memory-limit-mb", "1")
    assert r.ok, r.stderr
    rows = r.rows()
    assert len(rows) == 3 * n + 1
    ids = [int(row[0]) for row in rows[1:]]
    assert ids == sorted(ids)


# --- Spec: "Avoid format-specific issues (e.g., don't load entire Parquet
#            files ...)" - many small row groups stream fine ---------------
def test_many_row_groups_stream(tmp_path):
    n = 900
    p = write_parquet(tmp_path, "a.parquet",
                      [{"id": n - i, "v": "x" * 50} for i in range(n)],
                      row_group_size=10)
    r = merge_paths([p], "--key", "id", "--memory-limit-mb", "1",
                    "--parquet-row-group-bytes", "1024")
    assert r.ok, r.stderr
    assert [int(row[0]) for row in r.rows()[1:]] == list(range(1, n + 1))


# --- Spec: intermediates are cleaned up, mixed-format edition -------------
def test_temp_dir_left_empty_for_mixed_inputs(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    n = 800
    c = write(tmp_path, "a.csv", "id\n" + "".join(f"{i}\n" for i in range(n)))
    p = write_parquet(tmp_path, "b.parquet", [{"id": i} for i in range(n)])
    r = merge_paths([c, p], "--key", "id", "--memory-limit-mb", "1",
                    "--temp-dir", str(scratch))
    assert r.ok, r.stderr
    assert os.listdir(scratch) == []


# --- Spec: output is independent of the memory budget --------------------
def test_output_independent_of_memory_limit(tmp_path):
    c = write(tmp_path, "a.csv",
              "id,tag\n" + "".join(f"{(i * 13) % 500},c{i}\n" for i in range(500)))
    j = write_jsonl(tmp_path, "b.jsonl",
                    [{"id": (i * 7) % 500, "tag": f"j{i}"} for i in range(500)])
    small = merge_paths([c, j], "--key", "id", "--memory-limit-mb", "1")
    large = merge_paths([c, j], "--key", "id", "--memory-limit-mb", "256")
    assert small.ok and large.ok, (small.stderr, large.stderr)
    assert small.stdout == large.stdout
