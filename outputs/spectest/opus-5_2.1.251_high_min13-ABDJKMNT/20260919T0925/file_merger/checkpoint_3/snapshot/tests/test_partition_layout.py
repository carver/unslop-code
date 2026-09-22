"""Checkpoint 3: the Hive-style directory tree written under `--output`."""


def test_each_unique_value_combination_gets_its_own_directory(run_cli, csv_file, tmp_path, tree):
    # Spec: "Rows for each unique combination of partition column values go into
    # separate directory"
    a = csv_file("a.csv", "id,country,dt\n1,US,2024-01-01\n2,US,2024-01-02\n3,FR,2024-01-01\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "country,dt", a)
    assert tree(out) == [
        "country=FR/dt=2024-01-01/part-00000.csv",
        "country=US/dt=2024-01-01/part-00000.csv",
        "country=US/dt=2024-01-02/part-00000.csv",
    ]


def test_rows_land_in_the_directory_of_their_values(run_cli, csv_file, tmp_path):
    # Spec: "Rows for each unique combination of partition column values go into
    # separate directory"
    a = csv_file("a.csv", "id,g\n1,x\n2,y\n3,x\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert (out / "g=x" / "part-00000.csv").read_text(encoding="utf-8") == "g,id\nx,1\nx,3\n"
    assert (out / "g=y" / "part-00000.csv").read_text(encoding="utf-8") == "g,id\ny,2\n"


def test_segments_follow_the_partition_by_order(run_cli, csv_file, tmp_path, tree):
    # Spec: "Emit directory tree inside --output using Hive-style segments:
    # `<col1>=<val1>/<col2>=<val2>/.../`"
    a = csv_file("a.csv", "id,alpha,beta\n1,p,q\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "beta,alpha", a)
    assert tree(out) == ["beta=q/alpha=p/part-00000.csv"]


def test_int_values_use_their_cast_form(run_cli, csv_file, tmp_path, tree):
    # Spec: "Values derived after casting to resolved schema types"
    a = csv_file("a.csv", "id,n\n1,007\n2,7\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "n", a)
    assert tree(out) == ["n=7/part-00000.csv"]


def test_timestamp_values_use_their_normalized_cast_form(run_cli, csv_file, tmp_path, tree):
    # Spec: "Values derived after casting to resolved schema types" — a timestamp
    # renders normalized to UTC with `Z`, and its colons are then percent-encoded
    a = csv_file("a.csv", "id,ts\n1,2024-01-01T05:30:00+01:00\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "ts", a)
    assert tree(out) == ["ts=2024-01-01T04%3A30%3A00Z/part-00000.csv"]


def test_date_values_keep_their_iso_form(run_cli, csv_file, tmp_path, tree):
    # Spec: "Values derived after casting to resolved schema types"
    a = csv_file("a.csv", "id,d\n1,2024-03-09\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "d", a)
    assert tree(out) == ["d=2024-03-09/part-00000.csv"]


def test_bool_values_use_the_output_rendering(run_cli, csv_file, tmp_path, tree):
    # Spec: "Values derived after casting to resolved schema types" (rendering: AMBIGUITIES T1)
    a = csv_file("a.csv", "id,flag\n1,true\n2,0\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "flag", a)
    assert tree(out) == ["flag=False/part-00000.csv", "flag=True/part-00000.csv"]


def test_space_is_percent_encoded(run_cli, csv_file, tmp_path, tree):
    # Spec: "space → `%20`"
    a = csv_file("a.csv", "id,g\n1,new york\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert tree(out) == ["g=new%20york/part-00000.csv"]


def test_slash_is_percent_encoded_rather_than_nesting(run_cli, csv_file, tmp_path, tree):
    # Spec: "`/` encoded as `%2F`"
    a = csv_file("a.csv", "id,g\n1,a/b\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert tree(out) == ["g=a%2Fb/part-00000.csv"]


def test_unreserved_characters_are_left_alone(run_cli, csv_file, tmp_path, tree):
    # Spec: "percent-encoding of UTF-8 bytes for characters outside `[A-Za-z0-9._-]`"
    a = csv_file("a.csv", "id,g\n1,Ab9._-\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert tree(out) == ["g=Ab9._-/part-00000.csv"]


def test_other_ascii_characters_are_percent_encoded(run_cli, csv_file, tmp_path, tree):
    # Spec: "for characters outside `[A-Za-z0-9._-]`" — `~`, `%` and `=` are outside it
    a = csv_file("a.csv", "id,g\n1,~a%b=c\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert tree(out) == ["g=%7Ea%25b%3Dc/part-00000.csv"]


def test_non_ascii_values_are_encoded_as_utf8_bytes(run_cli, csv_file, tmp_path, tree):
    # Spec: "Apply percent-encoding of UTF-8 bytes"
    a = csv_file("a.csv", "id,g\n1,café\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert tree(out) == ["g=caf%C3%A9/part-00000.csv"]


def test_missing_partition_values_use_the_null_literal(run_cli, csv_file, tmp_path, tree):
    # Spec: "Null (missing) partition values use literal `_null`"
    a = csv_file("a.csv", "id,g\n1,x\n2,\n")
    b = csv_file("b.csv", "id\n3\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", a, b)
    assert tree(out) == ["g=_null/part-00000.csv", "g=x/part-00000.csv"]
    assert (out / "g=_null" / "part-00000.csv").read_text(encoding="utf-8") == "g,id\n,2\n,3\n"


def test_empty_string_partition_value_is_not_null(run_cli, jsonl_file, tmp_path, tree):
    # Spec: "Null (missing) partition values use literal `_null`" — an empty JSON
    # string is a value, not a missing one (AMBIGUITIES T43)
    a = jsonl_file("a.jsonl", [{"id": 1, "g": ""}, {"id": 2, "g": None}])
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert tree(out) == ["g=/part-00000.csv", "g=_null/part-00000.csv"]


def test_one_file_per_partition_without_cutting_rules(run_cli, csv_file, tmp_path, tree):
    # Spec: "Must respect size/row-based cutting rules if set ...; otherwise one file
    # per partition"
    rows = "".join(f"{index},{'xy'[index % 2]}\n" for index in range(40))
    a = csv_file("a.csv", "id,g\n" + rows)
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    assert tree(out) == ["g=x/part-00000.csv", "g=y/part-00000.csv"]


def test_partition_files_carry_the_resolved_schema_header(run_cli, csv_file, tmp_path):
    # Spec: "Each file contains header row (resolved schema header)"
    a = csv_file("a.csv", "id,g,note\n1,x,hello\n")
    out = tmp_path / "out"
    run_cli("--output", out, "--key", "id", "--partition-by", "g", a)
    lines = (out / "g=x" / "part-00000.csv").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "g,id,note"
