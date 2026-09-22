"""External-sort behaviour: small memory limits, temp directories, cleanup."""

import random


def _big_input(csv_file, name, rows):
    body = "".join(f"{key},{name}-{index}\n" for index, key in enumerate(rows))
    return csv_file(name, "id,tag\n" + body)


def test_sorts_correctly_under_a_tiny_memory_limit(run_cli, csv_file):
    # Spec: "Tool must handle inputs exceeding --memory-limit-mb constraint"
    keys = random.Random(7).sample(range(2, 4002), 4000)
    source = _big_input(csv_file, "big.csv", keys)
    result = run_cli("--output", "-", "--key", "id", "--memory-limit-mb", "1", source)
    assert result.returncode == 0, result.stderr
    assert [int(row[0]) for row in result.rows[1:]] == sorted(keys)


def test_small_limit_preserves_stability_across_files(run_cli, csv_file):
    # Spec: "Sort must be stable" while "inputs exceeding --memory-limit-mb"
    a = _big_input(csv_file, "a.csv", [index % 50 + 2 for index in range(800)])
    b = _big_input(csv_file, "b.csv", [index % 50 + 2 for index in range(800)])
    result = run_cli("--output", "-", "--key", "id", "--memory-limit-mb", "1", a, b)
    rows = result.rows[1:]
    assert [int(row[0]) for row in rows] == sorted(int(row[0]) for row in rows)
    tags_for_key_2 = [row[1] for row in rows if row[0] == "2"]
    assert tags_for_key_2 == [f"a.csv-{i}" for i in range(0, 800, 50)] + [
        f"b.csv-{i}" for i in range(0, 800, 50)
    ]


def test_temp_dir_is_used_and_left_empty(run_cli, csv_file, tmp_path):
    # Spec: "--temp-dir <PATH>" and "All intermediate resources must be cleaned up on exit"
    spill = tmp_path / "spill"
    spill.mkdir()
    keys = random.Random(3).sample(range(2, 3002), 3000)
    source = _big_input(csv_file, "big.csv", keys)
    result = run_cli(
        "--output", "-", "--key", "id", "--memory-limit-mb", "1", "--temp-dir", spill, source
    )
    assert result.returncode == 0, result.stderr
    assert [int(row[0]) for row in result.rows[1:]] == sorted(keys)
    assert list(spill.iterdir()) == []


def test_temp_dir_is_left_empty_after_a_failure(run_cli, csv_file, tmp_path):
    # Spec: "All intermediate resources must be cleaned up on exit" on the error path
    spill = tmp_path / "spill"
    spill.mkdir()
    schema = tmp_path / "schema.json"
    schema.write_text('{"columns": [{"name": "id", "type": "int"}]}', encoding="utf-8")
    source = csv_file("a.csv", "id,tag\n1,x\nnope,y\n")
    result = run_cli(
        "--output", "-", "--key", "id", "--schema", schema,
        "--on-type-error", "fail", "--temp-dir", spill, source
    )
    assert result.returncode != 0
    assert list(spill.iterdir()) == []


def test_output_file_is_complete_under_a_small_limit(run_cli, csv_file, tmp_path):
    # Spec: "all rows from inputs" regardless of the memory limit
    keys = random.Random(11).sample(range(2, 2002), 2000)
    source = _big_input(csv_file, "big.csv", keys)
    out = tmp_path / "merged.csv"
    result = run_cli("--output", out, "--key", "id", "--memory-limit-mb", "1", source)
    assert result.returncode == 0, result.stderr
    assert len(out.read_text(encoding="utf-8").splitlines()) == len(keys) + 1
