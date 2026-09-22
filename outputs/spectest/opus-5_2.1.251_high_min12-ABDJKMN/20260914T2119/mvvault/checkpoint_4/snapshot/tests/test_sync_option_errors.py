"""Spec: Error Handling rows for `sync` option parsing."""
import pytest

from conftest import make_entry, read_catalog, catalog_bytes, media_files


# Spec: "| Malformed numeric category limit | stderr | non-zero | Abort before
# any sync work |" -- non-numeric value.
@pytest.mark.parametrize("option", ["--episodes=abc", "--streams=x",
                                    "--clips=1.5"])
def test_non_numeric_limit_is_an_error(run, source, vault, option):
    source.serve(episodes=[make_entry(id="e1")])
    res = run("sync", "vault", option)
    assert res.returncode != 0
    assert res.stderr != ""


# Spec: "| `--episodes=<n>` | non-negative integer |" + "Malformed numeric
# category limit ... non-zero" -- a negative limit is malformed.
@pytest.mark.parametrize("option", ["--episodes=-1", "--streams=-2",
                                    "--clips=-10"])
def test_negative_limit_is_an_error(run, source, vault, option):
    source.serve(episodes=[make_entry(id="e1")])
    res = run("sync", "vault", option)
    assert res.returncode != 0
    assert res.stderr != ""


# Spec: "Malformed numeric category limit ... Abort before any sync work" --
# no source request is made and the catalog is untouched.
def test_malformed_limit_aborts_before_any_sync_work(run, source, tmp_path,
                                                     vault):
    source.serve(episodes=[make_entry(id="e1")])
    before = catalog_bytes(tmp_path)
    res = run("sync", "vault", "--episodes=nope")
    assert res.returncode != 0
    assert source.requests == []
    assert catalog_bytes(tmp_path) == before
    assert media_files(tmp_path) == []


# Spec: "Malformed numeric category limit | stderr | ..." -- nothing goes to
# stdout.
def test_malformed_limit_writes_nothing_to_stdout(run, source, vault):
    source.serve(episodes=[make_entry(id="e1")])
    assert run("sync", "vault", "--episodes=nope").stdout == ""


# Spec: "| Unrecognized CLI option | stderr | non-zero | Abort before any sync
# work |"
def test_unrecognized_option_is_an_error(run, source, vault):
    source.serve(episodes=[make_entry(id="e1")])
    res = run("sync", "vault", "--bogus")
    assert res.returncode != 0
    assert res.stderr != ""


# Spec: "Unrecognized CLI option ... Abort before any sync work"
def test_unrecognized_option_aborts_before_any_sync_work(run, source, tmp_path,
                                                         vault):
    source.serve(episodes=[make_entry(id="e1")])
    before = catalog_bytes(tmp_path)
    res = run("sync", "vault", "--nope=1")
    assert res.returncode != 0
    assert source.requests == []
    assert catalog_bytes(tmp_path) == before
    assert res.stdout == ""


# Spec: "Unrecognized CLI option" -- also applies to options that exist for a
# different subcommand.
def test_unknown_option_on_digest_is_an_error(run, source, vault):
    res = run("digest", "vault", "--episodes=1")
    assert res.returncode != 0
    assert res.stderr != ""


# Spec: the documented options are recognized (they are not "unrecognized").
@pytest.mark.parametrize("option", [
    "--episodes=1", "--streams=1", "--clips=1",
    "--skip-metadata", "--skip-download", "--format=mp4",
])
def test_documented_options_are_recognized(run, source, vault, option):
    source.serve(episodes=[make_entry(id="e1")])
    res = run("sync", "vault", option)
    assert res.returncode == 0, res


# Spec: "| `--episodes=<n>` | non-negative integer |" -- large and zero values
# are both well-formed.
@pytest.mark.parametrize("value", ["0", "1", "999999"])
def test_well_formed_limits_accepted(run, source, vault, value):
    source.serve(episodes=[make_entry(id="e1")])
    assert run("sync", "vault", "--episodes=%s" % value).returncode == 0
