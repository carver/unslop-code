"""`New Input Types`: gzip handling (`--compression`)."""
import gzip

from conftest import merge_paths, write, write_bytes, write_gz, write_jsonl_gz


# --- Spec: "--compression=auto (default): detect `.gz` -> gzip" -----------
def test_auto_gunzips_dot_gz(tmp_path):
    a = write_gz(tmp_path, "a.csv.gz", "id,name\n7,x\n")
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["7", "x"]]


# --- Spec: "... otherwise none" -------------------------------------------
def test_auto_reads_plain_file_uncompressed(tmp_path):
    a = write(tmp_path, "a.csv", "id,name\n7,x\n")
    r = merge_paths([a], "--key", "id")
    assert r.ok, r
    assert r.rows()[1] == ["7", "x"]


# --- Spec: "--compression=gzip forces gzip" -------------------------------
def test_forced_gzip_reads_gzip_named_without_suffix(tmp_path):
    a = write_bytes(tmp_path, "a.csv", gzip.compress(b"id,name\n7,x\n"))
    r = merge_paths([a], "--key", "id", "--compression", "gzip")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["7", "x"]]


# --- Spec: "--compression=none forces no decompression" -------------------
def test_forced_none_on_plain_dot_gz_named_file(tmp_path):
    # Name says .gz, content is plain text; --compression none forces plain.
    a = write(tmp_path, "a.csv.gz", "id,name\n7,x\n")
    r = merge_paths([a], "--key", "id", "--compression", "none")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["7", "x"]]


# --- Spec: "Mismatch is error 5" ------------------------------------------
def test_forced_gzip_on_plain_file_is_error_5(tmp_path):
    a = write(tmp_path, "a.csv", "id,name\n1,x\n")
    r = merge_paths([a], "--key", "id", "--compression", "gzip")
    assert r.returncode == 5, r
    assert r.stderr.strip()


def test_forced_none_on_gzip_content_is_error_5(tmp_path):
    a = write_bytes(tmp_path, "a.csv", gzip.compress(b"id,name\n1,x\n"))
    r = merge_paths([a], "--key", "id", "--compression", "none")
    assert r.returncode == 5, r


def test_auto_dot_gz_name_with_plain_content_is_error_5(tmp_path):
    a = write(tmp_path, "a.csv.gz", "id,name\n1,x\n")
    r = merge_paths([a], "--key", "id")
    assert r.returncode == 5, r


def test_auto_plain_name_with_gzip_content_is_error_5(tmp_path):
    a = write_bytes(tmp_path, "a.csv", gzip.compress(b"id,name\n1,x\n"))
    r = merge_paths([a], "--key", "id")
    assert r.returncode == 5, r


# --- Spec: "For gzip, allow `.gz` suffix after base extension" - gzip and
#            plain sources merge together ---------------------------------
def test_gzip_and_plain_sources_merge(tmp_path):
    a = write(tmp_path, "a.csv", "id,name\n1,plain\n")
    b = write_jsonl_gz(tmp_path, "b.jsonl.gz", [{"id": 2, "name": "gz"}])
    r = merge_paths([a, b], "--key", "id")
    assert r.ok, r
    assert r.rows() == [["id", "name"], ["1", "plain"], ["2", "gz"]]


# --- Spec: "--compression {auto,none,gzip}" - a bad value is rejected ------
def test_unknown_compression_value_rejected(tmp_path):
    a = write(tmp_path, "a.csv", "id\n1\n")
    r = merge_paths([a], "--key", "id", "--compression", "bzip2")
    assert r.returncode == 2, r
