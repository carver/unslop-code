"""Spec section: Performance & Memory — spilling, temp directories, cleanup."""

import random

from conftest import column


def big_input(path, rows, seed=0):
    """Write `rows` shuffled records with a wide payload column."""
    order = list(range(rows))
    random.Random(seed).shuffle(order)
    payload = "x" * 200
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write("id,payload\n")
        for value in order:
            handle.write(f"{value},{payload}\n")


# Phrase: "Tool must handle inputs exceeding --memory-limit-mb constraint"
# Context: Sorting. The result is fully sorted even when chunks must spill.
def test_sorts_correctly_when_input_exceeds_the_memory_limit(run_tool, workdir):
    big_input(workdir / "a.csv", 4000, seed=1)
    big_input(workdir / "b.csv", 4000, seed=2)
    result = run_tool(
        "--output", "out.csv", "--key", "id", "--memory-limit-mb", "1", "a.csv", "b.csv"
    )
    assert result.returncode == 0, result.stderr
    ids = [int(value) for value in column((workdir / "out.csv").read_text(), "id")]
    assert len(ids) == 8000
    assert ids == sorted(ids)


# Phrase: "Tool must work under small --memory-limit-mb ... on arbitrarily large inputs"
# Context: Performance & Memory. Descending order also survives spilling.
def test_descending_sort_survives_spilling(run_tool, workdir):
    big_input(workdir / "a.csv", 3000, seed=3)
    result = run_tool(
        "--output", "out.csv", "--key", "id", "--desc", "--memory-limit-mb", "1", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    ids = [int(value) for value in column((workdir / "out.csv").read_text(), "id")]
    assert ids == sorted(ids, reverse=True)


# Phrase: "[--temp-dir <PATH>]"
# Context: Usage. Intermediate files are placed under the requested directory.
def test_temp_dir_is_used_for_intermediates(run_tool, workdir):
    scratch = workdir / "scratch"
    scratch.mkdir()
    big_input(workdir / "a.csv", 3000)
    result = run_tool(
        "--output", "out.csv", "--key", "id",
        "--memory-limit-mb", "1", "--temp-dir", str(scratch), "a.csv",
    )
    assert result.returncode == 0, result.stderr
    assert (workdir / "out.csv").exists()


# Phrase: "All intermediate resources must be cleaned up on exit"
# Context: Performance & Memory.
def test_intermediates_are_removed_on_success(run_tool, workdir):
    scratch = workdir / "scratch"
    scratch.mkdir()
    big_input(workdir / "a.csv", 3000)
    run_tool(
        "--output", "out.csv", "--key", "id",
        "--memory-limit-mb", "1", "--temp-dir", str(scratch), "a.csv",
    )
    assert list(scratch.iterdir()) == []


# Phrase: "All intermediate resources must be cleaned up on exit"
# Context: Performance & Memory. Cleanup also happens on the error path.
def test_intermediates_are_removed_after_a_failure(csv_file, run_tool, workdir):
    scratch = workdir / "scratch"
    scratch.mkdir()
    csv_file("schema.json", '{"columns": [{"name": "id", "type": "int"}]}')
    csv_file("a.csv", "id\n1\nbroken\n")
    result = run_tool(
        "--output", "out.csv", "--key", "id", "--schema", "schema.json",
        "--on-type-error", "fail", "--temp-dir", str(scratch), "a.csv",
    )
    assert result.returncode != 0
    assert list(scratch.iterdir()) == []


# Phrase: "Sort must be stable with respect to input appearance for equal keys"
# Context: Sorting. Stability holds across spilled chunks, not just within one.
def test_stability_holds_across_spilled_chunks(run_tool, workdir):
    payload = "y" * 200
    with open(workdir / "a.csv", "w", encoding="utf-8", newline="") as handle:
        handle.write("id,seq,payload\n")
        for index in range(4000):
            handle.write(f"{index % 4},{index},{payload}\n")
    result = run_tool(
        "--output", "out.csv", "--key", "id", "--memory-limit-mb", "1", "a.csv"
    )
    assert result.returncode == 0, result.stderr
    text = (workdir / "out.csv").read_text()
    seqs = [int(value) for value in column(text, "seq")]
    for group in range(4):
        block = seqs[group * 1000:(group + 1) * 1000]
        assert block == sorted(block)
