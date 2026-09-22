"""Spec section: New Input Types (format detection, compression)."""
from conftest import body, header


# Phrase: "Accepted file types: CSV, TSV, JSON Lines (NDJSON), Parquet"
# Context: New Input Types.
def test_csv_input_accepted(run, work):
    work.csv("a.csv", ["id"], [["5"]])
    r = run("--output", "-", "--key", "id", work.path("a.csv"))
    assert r.ok, r.stderr
    assert body(r) == [["5"]]


def test_tsv_input_accepted(run, work):
    work.tsv("a.tsv", ["id"], [["5"]])
    r = run("--output", "-", "--key", "id", work.path("a.tsv"))
    assert r.ok, r.stderr
    assert body(r) == [["5"]]


def test_jsonl_input_accepted(run, work):
    work.jsonl("a.jsonl", [{"id": 1}])
    r = run("--output", "-", "--key", "id", work.path("a.jsonl"))
    assert r.ok, r.stderr
    assert body(r) == [["1"]]


def test_parquet_input_accepted(run, work):
    work.parquet("a.parquet", [{"id": 1}])
    r = run("--output", "-", "--key", "id", work.path("a.parquet"))
    assert r.ok, r.stderr
    assert body(r) == [["1"]]


# Phrase: "`--input-format=auto` (default): detect per file by extension and magic bytes"
# Context: New Input Types; detection is per file, so one run may mix all four.
def test_detection_is_per_file(run, work):
    work.csv("a.csv", ["id"], [["5"]])
    work.tsv("b.tsv", ["id"], [["6"]])
    work.jsonl("c.jsonl", [{"id": 7}])
    work.parquet("d.parquet", [{"id": 8}])
    r = run(
        "--output", "-", "--key", "id",
        work.path("a.csv"), work.path("b.tsv"),
        work.path("c.jsonl"), work.path("d.parquet"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["5"], ["6"], ["7"], ["8"]]


# Phrase: "`.jsonl`/`.ndjson` -> jsonl"
# Context: New Input Types; both extensions mean JSON Lines.
def test_ndjson_extension_is_jsonl(run, work):
    work.jsonl("a.ndjson", [{"id": 2}, {"id": 1}])
    r = run("--output", "-", "--key", "id", work.path("a.ndjson"))
    assert r.ok, r.stderr
    assert body(r) == [["1"], ["2"]]


# Phrase: "For gzip, allow `.gz` suffix after base extension (e.g., `data.csv.gz`, `events.jsonl.gz`)"
# Context: New Input Types.
def test_gzipped_csv_detected(run, work):
    work.gzip("data.csv.gz", "id\n5\n")
    r = run("--output", "-", "--key", "id", work.path("data.csv.gz"))
    assert r.ok, r.stderr
    assert body(r) == [["5"]]


def test_gzipped_jsonl_detected(run, work):
    work.gzip("events.jsonl.gz", '{"id": 7}\n{"id": 6}\n')
    r = run("--output", "-", "--key", "id", work.path("events.jsonl.gz"))
    assert r.ok, r.stderr
    assert body(r) == [["6"], ["7"]]


def test_gzipped_tsv_detected(run, work):
    work.gzip("data.tsv.gz", "id\tname\n5\tzed\n")
    r = run("--output", "-", "--key", "id", work.path("data.tsv.gz"))
    assert r.ok, r.stderr
    assert header(r) == ["id", "name"]
    assert body(r) == [["5", "zed"]]


def test_gzipped_parquet_detected(run, work):
    src = work.parquet("m.parquet", [{"id": 3}, {"id": 1}])
    work.gzip_file("m.parquet.gz", src)
    r = run("--output", "-", "--key", "id", work.path("m.parquet.gz"))
    assert r.ok, r.stderr
    assert body(r) == [["1"], ["3"]]


# Phrase: "If extension is ambiguous and magic bytes indicate Parquet, treat as parquet;
#          otherwise error 2"
# Context: New Input Types.
def test_unknown_extension_with_parquet_magic_is_parquet(run, work):
    src = work.parquet("real.parquet", [{"id": 9}])
    work.raw("mystery.dat", src.read_bytes())
    r = run("--output", "-", "--key", "id", work.path("mystery.dat"))
    assert r.ok, r.stderr
    assert body(r) == [["9"]]


def test_unknown_extension_without_parquet_magic_is_error_2(run, work):
    work.write("mystery.dat", "id\n1\n")
    r = run("--output", "-", "--key", "id", work.path("mystery.dat"))
    assert r.returncode == 2
    assert r.stderr.strip()


def test_no_extension_without_parquet_magic_is_error_2(run, work):
    work.write("plainfile", "id\n1\n")
    r = run("--output", "-", "--key", "id", work.path("plainfile"))
    assert r.returncode == 2


# Phrase: "--input-format {auto,csv,tsv,jsonl,parquet}"
# Context: Usage; an explicit format overrides extension detection.
def test_explicit_input_format_overrides_extension(run, work):
    # Tab-separated content living in a file named .csv
    work.write("weird.csv", "id\tname\n2\tb\n1\ta\n")
    r = run(
        "--output", "-", "--key", "id", "--input-format", "tsv",
        work.path("weird.csv"),
    )
    assert r.ok, r.stderr
    assert header(r) == ["id", "name"]
    assert body(r) == [["1", "a"], ["2", "b"]]


def test_explicit_input_format_allows_unknown_extension(run, work):
    work.write("mystery.dat", "id\n4\n")
    r = run(
        "--output", "-", "--key", "id", "--input-format", "csv",
        work.path("mystery.dat"),
    )
    assert r.ok, r.stderr
    assert body(r) == [["4"]]


def test_input_format_rejects_unknown_choice(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run(
        "--output", "-", "--key", "id", "--input-format", "xml", work.path("a.csv")
    )
    assert r.returncode != 0


def test_input_format_accepts_all_choices(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    for mode in ("auto", "csv"):
        r = run(
            "--output", "-", "--key", "id", "--input-format", mode, work.path("a.csv")
        )
        assert r.ok, r.stderr


# Phrase: "`--compression=auto` (default): detect `.gz` -> gzip; otherwise none"
# Context: New Input Types.
def test_compression_auto_reads_plain_file(run, work):
    work.csv("a.csv", ["id"], [["5"]])
    r = run(
        "--output", "-", "--key", "id", "--compression", "auto", work.path("a.csv")
    )
    assert r.ok, r.stderr
    assert body(r) == [["5"]]


def test_compression_auto_reads_gzip_file(run, work):
    work.gzip("a.csv.gz", "id\n5\n")
    r = run(
        "--output", "-", "--key", "id", "--compression", "auto", work.path("a.csv.gz")
    )
    assert r.ok, r.stderr
    assert body(r) == [["5"]]


# Phrase: "`--compression=gzip` forces gzip"
# Context: New Input Types; the .gz suffix is then not required.
def test_compression_gzip_forced_without_gz_suffix(run, work):
    work.gzip("packed.csv", "id\n8\n")
    r = run(
        "--output", "-", "--key", "id", "--compression", "gzip", work.path("packed.csv")
    )
    assert r.ok, r.stderr
    assert body(r) == [["8"]]


# Phrase: "`--compression=none` forces no decompression"
# Context: New Input Types.
def test_compression_none_reads_plain_file(run, work):
    work.csv("a.csv", ["id"], [["3"]])
    r = run(
        "--output", "-", "--key", "id", "--compression", "none", work.path("a.csv")
    )
    assert r.ok, r.stderr
    assert body(r) == [["3"]]


# Phrase: "Mismatch is error 5"
# Context: New Input Types; forced compression disagreeing with the actual bytes.
def test_forced_gzip_on_plain_file_is_error_5(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run(
        "--output", "-", "--key", "id", "--compression", "gzip", work.path("a.csv")
    )
    assert r.returncode == 5
    assert r.stderr.strip()


def test_forced_none_on_gzip_file_is_error_5(run, work):
    work.gzip("a.csv.gz", "id\n1\n")
    r = run(
        "--output", "-", "--key", "id", "--compression", "none", work.path("a.csv.gz")
    )
    assert r.returncode == 5


def test_gz_suffix_on_non_gzip_bytes_is_error_5(run, work):
    work.write("a.csv.gz", "id\n1\n")
    r = run("--output", "-", "--key", "id", work.path("a.csv.gz"))
    assert r.returncode == 5


def test_compression_rejects_unknown_choice(run, work):
    work.csv("a.csv", ["id"], [["1"]])
    r = run(
        "--output", "-", "--key", "id", "--compression", "zstd", work.path("a.csv")
    )
    assert r.returncode != 0


# Phrase: "--parquet-row-group-bytes <INT>" / "advisory for batch sizing"
# Context: Usage & New Input Types; the flag never changes emitted bytes.
def test_parquet_row_group_bytes_is_advisory(run, work):
    work.parquet("a.parquet", [{"id": i} for i in (3, 1, 2)])
    outs = []
    for size in ("1024", "1048576"):
        r = run(
            "--output", "-", "--key", "id", "--parquet-row-group-bytes", size,
            work.path("a.parquet"),
        )
        assert r.ok, r.stderr
        outs.append(r.stdout)
    assert outs[0] == outs[1] == "id\n1\n2\n3\n"
