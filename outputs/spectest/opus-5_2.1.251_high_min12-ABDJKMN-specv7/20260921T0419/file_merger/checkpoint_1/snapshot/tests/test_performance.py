"""Spec section: Performance & Memory."""
import os

from conftest import body, header


# Phrase: "Tool must work under small `--memory-limit-mb` (e.g., 64MB) on arbitrarily large inputs"
# Context: Performance & Memory.
def test_large_input_under_small_memory_limit(run, work):
    n = 20000
    rows = [[str((i * 7919) % n), "x" * 20] for i in range(n)]
    work.csv("a.csv", ["id", "pad"], rows)
    r = run(
        "--output", "-", "--key", "id", "--memory-limit-mb", "1", work.path("a.csv"),
        timeout=300,
    )
    assert r.ok, r.stderr
    out = body(r)
    assert len(out) == n
    ids = [int(row[0]) for row in out]
    assert ids == sorted(ids)


def test_multiple_large_inputs_merge_correctly(run, work):
    n = 5000
    work.csv("a.csv", ["id"], [[str(i * 2)] for i in range(n)])
    work.csv("b.csv", ["id"], [[str(i * 2 + 1)] for i in range(n)])
    r = run(
        "--output", "-", "--key", "id", "--memory-limit-mb", "1",
        work.path("a.csv"), work.path("b.csv"), timeout=300,
    )
    assert r.ok, r.stderr
    ids = [int(row[0]) for row in body(r)]
    assert ids == list(range(2 * n))


# Phrase: "Tool must handle inputs exceeding `--memory-limit-mb` constraint"
# Context: Sorting; stability must survive the external merge.
def test_stability_survives_external_sort(run, work):
    n = 4000
    work.csv("a.csv", ["id", "seq"], [["1", str(i)] for i in range(n)])
    r = run(
        "--output", "-", "--key", "id", "--memory-limit-mb", "1", work.path("a.csv"),
        timeout=300,
    )
    assert r.ok, r.stderr
    assert [int(row[1]) for row in body(r)] == list(range(n))


# Phrase: "All intermediate resources must be cleaned up on exit"
# Context: Performance & Memory.
def test_temp_dir_is_empty_after_success(run, work):
    tmp = work.path("scratch")
    tmp.mkdir()
    n = 3000
    work.csv("a.csv", ["id"], [[str((i * 13) % n)] for i in range(n)])
    r = run(
        "--output", work.path("out.csv"), "--key", "id",
        "--memory-limit-mb", "1", "--temp-dir", tmp, work.path("a.csv"),
        timeout=300,
    )
    assert r.ok, r.stderr
    assert os.listdir(tmp) == []


def test_temp_dir_is_empty_after_failure(run, work):
    tmp = work.path("scratch")
    tmp.mkdir()
    work.schema("s.json", [("id", "int"), ("k", "int")])
    work.csv("a.csv", ["id", "k"], [["1", "abc"]])
    r = run(
        "--output", "-", "--key", "id", "--schema", work.path("s.json"),
        "--on-type-error", "fail", "--temp-dir", tmp, work.path("a.csv"),
    )
    assert r.returncode != 0
    assert os.listdir(tmp) == []


# Phrase: "--temp-dir <PATH>"
# Context: Usage; intermediates go to the requested directory, output is unaffected.
def test_temp_dir_choice_does_not_change_output(run, work):
    tmp = work.path("scratch")
    tmp.mkdir()
    rows = [[str((i * 31) % 200)] for i in range(200)]
    work.csv("a.csv", ["id"], rows)
    a = run("--output", "-", "--key", "id", "--memory-limit-mb", "1", work.path("a.csv"))
    b = run(
        "--output", "-", "--key", "id", "--memory-limit-mb", "1",
        "--temp-dir", tmp, work.path("a.csv"),
    )
    assert a.ok and b.ok, a.stderr + b.stderr
    assert a.stdout == b.stdout


# Phrase: "Tool must work under small --memory-limit-mb"
# Context: Performance & Memory; results are identical to an unconstrained run.
def test_memory_limit_does_not_change_results(run, work):
    rows = [[str((i * 17) % 300), "v%d" % i] for i in range(300)]
    work.csv("a.csv", ["id", "v"], rows)
    small = run(
        "--output", "-", "--key", "id", "--memory-limit-mb", "1", work.path("a.csv")
    )
    big = run(
        "--output", "-", "--key", "id", "--memory-limit-mb", "512", work.path("a.csv")
    )
    assert small.ok and big.ok, small.stderr + big.stderr
    assert small.stdout == big.stdout
