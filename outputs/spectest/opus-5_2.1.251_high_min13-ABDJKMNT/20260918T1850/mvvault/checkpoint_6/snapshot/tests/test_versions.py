"""Spec sections: Supported Versions, Multi-Version Loading."""

from conftest import (
    payload,
    read_catalog,
    source_entry,
    v1_catalog,
    v1_entry,
    v2_catalog,
    v2_entry,
    write_vault,
)


# Spec: `1` | Supported
def test_version_1_catalog_is_supported(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    result = run("migrate", "vault")
    assert result.returncode == 0, result.stderr


# Spec: `2` | Supported
def test_version_2_catalog_is_supported(run, tmp_path):
    write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")]))
    result = run("migrate", "vault")
    assert result.returncode == 0, result.stderr


# Spec: `3` | Native format
def test_version_3_catalog_is_the_native_format(run, source, vault):
    assert read_catalog(vault)["version"] == 3
    source.serve(payload(episodes=[source_entry("e1")]))
    assert run("sync", "vault").returncode == 0
    assert read_catalog(vault)["version"] == 3


# Spec: `1` | ... Flat `entries` list; `source_id`; UNIX-epoch history keys; no `removed`;
# no `annotations` (a v1 vault loads despite lacking every v3-only field)
def test_version_1_shape_loads_without_v3_fields(run, tmp_path):
    entry = v1_entry("e1")
    assert "removed" not in entry and "annotations" not in entry
    write_vault(tmp_path, v1_catalog(entries=[entry]))

    assert run("migrate", "vault").returncode == 0
    assert read_catalog(tmp_path / "vault")["episodes"][0]["id"] == "e1"


# Spec: `2` | ... Category arrays; full `source`; ISO 8601 history keys; no `removed`;
# no `annotations`
def test_version_2_shape_loads_without_v3_fields(run, tmp_path):
    entry = v2_entry("s1")
    assert "removed" not in entry and "annotations" not in entry
    write_vault(tmp_path, v2_catalog(streams=[entry]))

    assert run("migrate", "vault").returncode == 0
    assert read_catalog(tmp_path / "vault")["streams"][0]["id"] == "s1"


# Spec: Version detection | Read `version` field from `catalog.json`
# (the declared version decides the layout, not the keys that happen to be present)
def test_version_field_decides_how_the_catalog_is_read(run, tmp_path):
    mislabelled = {**v2_catalog(episodes=[v2_entry("e1")]), "version": 1}
    write_vault(tmp_path, mislabelled)

    result = run("migrate", "vault")
    assert result.returncode != 0
    assert "Traceback" not in result.stderr


# Spec: Load trigger | Any command that reads a vault (`sync`, ...)
def test_sync_loads_a_version_1_catalog_without_a_version_error(run, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    result = run("sync", "vault")
    assert "version" not in result.stderr.lower()


# Spec: In-memory representation | All versions are usable by every command
def test_sync_runs_against_a_version_2_vault(run, tmp_path, source):
    write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")], source=source.url))
    source.serve(payload(episodes=[source_entry("e1", views=99)]))

    assert run("sync", "vault").returncode == 0
    assert source.request_count == 1


# Spec: Read-only access | Loading a v1 or v2 catalog for a read-only operation does
# **not** rewrite `catalog.json` (T20: no read-only command exists yet, so this is
# checked through a load that never reaches a write)
def test_loading_a_v2_catalog_without_writing_leaves_it_untouched(run, tmp_path, dead_url):
    directory = write_vault(tmp_path, v2_catalog(episodes=[v2_entry("e1")], source=dead_url))
    before = (directory / "catalog.json").read_bytes()

    assert run("sync", "vault").returncode != 0
    assert (directory / "catalog.json").read_bytes() == before
    assert not (directory / "catalog.bak").exists()
