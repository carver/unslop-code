"""Spec section: Usage — the command-line interface of merge_files.py."""

from conftest import header_of, rows_of


# Phrase: "python merge_files.py --output <PATH|-> --key <col>[,<col>...] <INPUT1.csv> [<INPUT2.csv> ...]"
# Context: Usage. --output, --key and at least one input are the mandatory parts.
def test_minimal_invocation_succeeds(csv_file, run_tool):
    csv_file("a.csv", "id,note\n2,b\n1,a\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1", "a"], ["2", "b"]]


# Phrase: "--output <PATH|->"
# Context: Usage. The flag is required.
def test_missing_output_flag_is_an_error(csv_file, run_tool):
    csv_file("a.csv", "id\n1\n")
    result = run_tool("--key", "id", "a.csv")
    assert result.returncode != 0
    assert result.stderr


# Phrase: "--key <col>[,<col>...]"
# Context: Usage. The flag is required.
def test_missing_key_flag_is_an_error(csv_file, run_tool):
    csv_file("a.csv", "id\n1\n")
    result = run_tool("--output", "-", "a.csv")
    assert result.returncode != 0
    assert result.stderr


# Phrase: "<INPUT1.csv> [<INPUT2.csv> ...]"
# Context: Usage. At least one input is required.
def test_no_inputs_is_an_error(run_tool):
    result = run_tool("--output", "-", "--key", "id")
    assert result.returncode != 0


# Phrase: "ingests multiple CSVs ... produces one sorted CSV output"
# Context: Introduction. Several inputs collapse into a single output stream.
def test_multiple_inputs_are_merged(csv_file, run_tool):
    csv_file("a.csv", "id,note\n3,c\n1,a\n")
    csv_file("b.csv", "id,note\n2,b\n4,d\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert result.returncode == 0, result.stderr
    assert rows_of(result.stdout) == [["1", "a"], ["2", "b"], ["3", "c"], ["4", "d"]]


# Phrase: "[--infer {strict,loose}]"
# Context: Usage. Only the two listed values are accepted.
def test_unknown_infer_mode_is_rejected(csv_file, run_tool):
    csv_file("a.csv", "id\n1\n")
    result = run_tool("--output", "-", "--key", "id", "--infer", "medium", "a.csv")
    assert result.returncode != 0


# Phrase: "[--on-type-error {coerce-null,fail,keep-string}]"
# Context: Usage. Only the three listed values are accepted.
def test_unknown_type_error_policy_is_rejected(csv_file, run_tool):
    csv_file("a.csv", "id\n1\n")
    result = run_tool("--output", "-", "--key", "id", "--on-type-error", "shout", "a.csv")
    assert result.returncode != 0


# Phrase: "All inputs are UTF-8 ... with a header row"
# Context: Fixed CSV assumptions. Non-ASCII text survives the round trip.
def test_utf8_content_is_preserved(csv_file, run_tool):
    csv_file("a.csv", "id,note\n1,café\n2,naïve\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert rows_of(result.stdout) == [["1", "café"], ["2", "naïve"]]


# Phrase: "with a header row"
# Context: Fixed CSV assumptions. The first line names columns and is not data.
def test_header_row_is_not_treated_as_data(csv_file, run_tool):
    csv_file("a.csv", "id,note\n7,a\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv")
    assert header_of(result.stdout) == ["id", "note"]
    assert rows_of(result.stdout) == [["7", "a"]]


# Phrase: "A command-line tool that ingests multiple CSVs"
# Context: Introduction. A file with only a header contributes no rows.
def test_header_only_input_contributes_no_rows(csv_file, run_tool):
    csv_file("a.csv", "id,note\n")
    csv_file("b.csv", "id,note\n7,a\n")
    result = run_tool("--output", "-", "--key", "id", "a.csv", "b.csv")
    assert rows_of(result.stdout) == [["7", "a"]]
