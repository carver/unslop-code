"""Spec section: Partitioned Output — "Partitioning by Size or Rows"."""

import os

from conftest import read_text, rows_of, run, run_ok, write


def parts(d):
    return sorted(p for p in os.listdir(d) if p.startswith("part-"))


def nrows(path):
    return len(rows_of(read_text(path)))


TEN = "id,v\n" + "".join(f"{i},x{i}\n" for i in range(1, 11))


# --- Spec: "--max-rows-per-file <INT>: cut output into files with at most INT
#     data rows each (header not counted)" ---
# Context: Partitioning by Size or Rows.
def test_max_rows_cuts_into_full_files(ws):
    a = write(ws / "a.csv", TEN)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-rows-per-file", "4", a)
    assert parts(out) == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    assert [nrows(out / p) for p in parts(out)] == [4, 4, 2]


# --- Spec: "at most INT data rows each (header not counted)" ---
# Context: the header does not consume part of the row budget.
def test_header_not_counted_against_row_limit(ws):
    a = write(ws / "a.csv", TEN)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-rows-per-file", "5", a)
    assert parts(out) == ["part-00000.csv", "part-00001.csv"]
    for p in parts(out):
        assert read_text(out / p).split("\n")[0] == "id,v"
        assert nrows(out / p) == 5


# --- Spec: "--max-rows-per-file <INT>" ---
# Context: a limit at or above the row count yields exactly one file.
def test_row_limit_above_total_yields_one_file(ws):
    a = write(ws / "a.csv", TEN)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-rows-per-file", "10", a)
    assert parts(out) == ["part-00000.csv"]
    assert nrows(out / "part-00000.csv") == 10


# --- Spec: "--max-rows-per-file <INT>" ---
# Context: a limit of 1 gives one row per file, and the counter keeps padding.
def test_row_limit_one_row_per_file(ws):
    a = write(ws / "a.csv", TEN)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-rows-per-file", "1", a)
    assert parts(out) == [f"part-{i:05d}.csv" for i in range(10)]
    assert rows_of(read_text(out / "part-00007.csv"))[0]["id"] == "8"


# --- Spec: "--max-bytes-per-file <INT>: cut so on-disk byte size of each file
#     (including header and line endings) is <= INT" ---
# Context: Partitioning by Size or Rows.
def test_max_bytes_respects_on_disk_size(ws):
    a = write(ws / "a.csv", TEN)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-bytes-per-file", "20", a)
    assert len(parts(out)) > 1
    for p in parts(out):
        assert os.path.getsize(out / p) <= 20, (p, read_text(out / p))


# --- Spec: "on-disk byte size ... (including header and line endings)" ---
# Context: the budget is exact bytes, so an off-by-one limit changes the cut.
def test_max_bytes_boundary_is_exact(ws):
    # header "id,v\n" = 5 bytes; each row "N,xN\n" = 5 bytes (ids 1..9).
    a = write(ws / "a.csv", "id,v\n" + "".join(f"{i},x{i}\n" for i in range(1, 7)))
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-bytes-per-file", "15", a)
    # 5 (header) + 2 rows * 5 = 15 fits; a 3rd row would be 20 > 15.
    assert [nrows(out / p) for p in parts(out)] == [2, 2, 2]
    for p in parts(out):
        assert os.path.getsize(out / p) == 15


# --- Spec: "on-disk byte size ... is <= INT" ---
# Context: sizes are UTF-8 bytes, not characters.
def test_max_bytes_counts_utf8_bytes(ws):
    a = write(ws / "a.csv", "id,v\n1,ééé\n2,ééé\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-bytes-per-file", "16", a)
    for p in parts(out):
        assert os.path.getsize(out / p) <= 16
    assert len(parts(out)) == 2


# --- Spec: "Exception: if single row alone exceeds INT, place that row in file
#     by itself (allowed to exceed limit)" ---
# Context: Partitioning by Size or Rows. See AMBIGUITIES T53.
def test_oversized_row_gets_its_own_file(ws):
    big = "y" * 200
    a = write(ws / "a.csv", f"id,v\n1,a\n2,{big}\n3,b\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-bytes-per-file", "30", a)
    sizes = {p: os.path.getsize(out / p) for p in parts(out)}
    over = [p for p, n in sizes.items() if n > 30]
    assert len(over) == 1
    assert nrows(out / over[0]) == 1


# --- Spec: "Exception: if single row alone exceeds INT ..." ---
# Context: a limit smaller than the header still yields one data row per file
# rather than an error (T53).
def test_limit_below_header_size_still_writes_rows(ws):
    a = write(ws / "a.csv", "id,v\n1,a\n2,b\n")
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-bytes-per-file", "1", a)
    assert parts(out) == ["part-00000.csv", "part-00001.csv"]
    assert read_text(out / "part-00000.csv") == "id,v\n1,a\n"


# --- Spec: "When both --max-rows-per-file and --max-bytes-per-file provided,
#     cut at earliest boundary that would violate either constraint" ---
# Context: the row limit binds first here.
def test_both_limits_rows_bind_first(ws):
    a = write(ws / "a.csv", TEN)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id",
           "--max-rows-per-file", "2", "--max-bytes-per-file", "100000", a)
    assert [nrows(out / p) for p in parts(out)] == [2, 2, 2, 2, 2]


# --- Spec: "cut at earliest boundary that would violate either constraint" ---
# Context: the byte limit binds first here.
def test_both_limits_bytes_bind_first(ws):
    a = write(ws / "a.csv", "id,v\n" + "".join(f"{i},x{i}\n" for i in range(1, 7)))
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id",
           "--max-rows-per-file", "1000", "--max-bytes-per-file", "15", a)
    assert [nrows(out / p) for p in parts(out)] == [2, 2, 2]


# --- Spec: "File naming (no field partitioning): write files directly under
#     --output as part-00000.csv, part-00001.csv, …" ---
# Context: no intermediate directories are created.
def test_shard_files_sit_directly_under_output(ws):
    a = write(ws / "a.csv", TEN)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-rows-per-file", "3", a)
    entries = sorted(os.listdir(out))
    assert entries == ["part-00000.csv", "part-00001.csv", "part-00002.csv",
                       "part-00003.csv"]
    assert all(os.path.isfile(out / e) for e in entries)


# --- Spec: "… in exact order rows are emitted from sorted stream" ---
# Context: shard N holds a contiguous ascending slice of the global order.
def test_shards_follow_sorted_stream_order(ws):
    a = write(ws / "a.csv", "id,v\n" + "".join(f"{i},x\n" for i in [5, 3, 1, 4, 2]))
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-rows-per-file", "2", a)
    got = [[r["id"] for r in rows_of(read_text(out / p))] for p in parts(out)]
    assert got == [["1", "2"], ["3", "4"], ["5"]]


# --- Spec: "… in exact order rows are emitted from sorted stream" ---
# Context: with --desc the shards follow the descending order.
def test_shards_follow_descending_stream_order(ws):
    a = write(ws / "a.csv", "id,v\n" + "".join(f"{i},x\n" for i in [5, 3, 1, 4, 2]))
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--desc",
           "--max-rows-per-file", "2", a)
    got = [[r["id"] for r in rows_of(read_text(out / p))] for p in parts(out)]
    assert got == [["5", "4"], ["3", "2"], ["1"]]


# --- Spec: "File naming (with field partitioning): same part-xxxxx.csv
#     sequence per partition directory" ---
# Context: the counter restarts at 00000 inside every partition.
def test_part_counter_restarts_per_partition(ws):
    rows = "".join(f"{i},{'US' if i <= 6 else 'CA'}\n" for i in range(1, 13))
    a = write(ws / "a.csv", "id,c\n" + rows)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "c",
           "--max-rows-per-file", "2", a)
    assert parts(out / "c=US") == [f"part-{i:05d}.csv" for i in range(3)]
    assert parts(out / "c=CA") == [f"part-{i:05d}.csv" for i in range(3)]


# --- Spec: "Must respect size/row-based cutting rules if set" ---
# Context: the byte budget is per file, and the header is re-counted in each.
def test_cutting_rules_apply_inside_partitions(ws):
    rows = "".join(f"{i},US\n" for i in range(1, 8))
    a = write(ws / "a.csv", "id,c\n" + rows)
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--partition-by", "c",
           "--max-bytes-per-file", "16", a)
    d = out / "c=US"
    for p in parts(d):
        assert os.path.getsize(d / p) <= 16


# --- Spec: "cut output into files with at most INT data rows each" ---
# Context: a limit of 0 cannot be honoured (T55).
def test_zero_row_limit_is_usage_error(ws):
    a = write(ws / "a.csv", TEN)
    res = run("--output", str(ws / "out"), "--key", "id",
              "--max-rows-per-file", "0", a)
    assert res.returncode == 2, res


def test_negative_row_limit_is_usage_error(ws):
    a = write(ws / "a.csv", TEN)
    res = run("--output", str(ws / "out"), "--key", "id",
              "--max-rows-per-file", "-1", a)
    assert res.returncode == 2, res


def test_zero_byte_limit_is_usage_error(ws):
    a = write(ws / "a.csv", TEN)
    res = run("--output", str(ws / "out"), "--key", "id",
              "--max-bytes-per-file", "0", a)
    assert res.returncode == 2, res


# --- Spec: "part-00000.csv, part-00001.csv, … (zero-padded width 5)" ---
# Context: the width is 5 and does not grow until it must.
def test_part_names_zero_padded_width_five(ws):
    n = 12
    a = write(ws / "a.csv", "id,v\n" + "".join(f"{i},x\n" for i in range(n)))
    out = ws / "out"
    run_ok("--output", str(out), "--key", "id", "--max-rows-per-file", "1", a)
    assert parts(out)[:3] == ["part-00000.csv", "part-00001.csv", "part-00002.csv"]
    assert parts(out)[-1] == "part-00011.csv"
