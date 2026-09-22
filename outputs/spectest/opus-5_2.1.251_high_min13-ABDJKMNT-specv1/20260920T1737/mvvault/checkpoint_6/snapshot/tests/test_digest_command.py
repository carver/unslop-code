"""`digest` command surface: syntax, streams, read-only guarantee, errors."""

from conftest import ISO_KEY, legacy_entry, v1_catalog, v2_catalog, v3_catalog, v3_entry, write_vault

LATER_KEY = "2024-07-01T10:00:00"


# Spec: "| Syntax | `python mvault.py digest <name>` |",
# "| Input | Existing vault of any supported version |",
# "| Output stream | stdout |".
def test_digest_writes_its_summary_to_stdout(tmp_path, run_cli):
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed", episodes=[v3_entry("e1")]))

    result = run_cli("digest", "demo")

    assert result.returncode == 0, result.stderr
    assert "title-e1" in result.stdout
    assert result.stderr == ""


# Spec: "| Catalog modification | `digest` is read-only; it never writes
# `catalog.json` or `catalog.bak` |".
def test_digest_never_writes_the_catalog_or_a_backup(tmp_path, run_cli):
    vault = write_vault(tmp_path, "demo", v2_catalog("https://example.test/feed", episodes=[legacy_entry("e1", ISO_KEY)]))
    before = (vault / "catalog.json").read_text()

    result = run_cli("digest", "demo")

    assert result.returncode == 0, result.stderr
    assert (vault / "catalog.json").read_text() == before
    assert not (vault / "catalog.bak").exists()


# Spec: "The `digest` command works on vaults of any supported version without
# requiring prior migration." -- a v1 vault is never rewritten either.
def test_digest_on_v1_vault_leaves_version_one_on_disk(tmp_path, run_cli):
    vault = write_vault(tmp_path, "demo", v1_catalog(legacy_entry("e1", "1718444400")))

    result = run_cli("digest", "demo")

    assert result.returncode == 0, result.stderr
    assert '"version": 1' in (vault / "catalog.json").read_text()


# Spec: "| Missing vault | Error to stderr including vault name; exit non-zero |".
def test_missing_vault_reports_the_name_on_stderr(run_cli):
    result = run_cli("digest", "ghost")

    assert result.returncode != 0
    assert "ghost" in result.stderr
    assert result.stdout == ""


# Spec: "| `digest` on vault with unsupported version | stderr | non-zero |
# Message includes version value |".
def test_unsupported_version_reports_the_version_value(tmp_path, run_cli):
    write_vault(tmp_path, "demo", {"version": 9, "source": "https://example.test/feed"})

    result = run_cli("digest", "demo")

    assert result.returncode != 0
    assert "9" in result.stderr


# Spec: "| Trailing line | Metadata about the digest run |" and
# "| Source reference | The trailing line includes the resolved source URL ... |".
def test_trailing_line_is_the_last_line_and_names_the_source(tmp_path, run_cli):
    write_vault(
        tmp_path,
        "demo",
        v3_catalog(
            "https://example.test/feed",
            episodes=[v3_entry("e1", title={ISO_KEY: "old", LATER_KEY: "new"})],
        ),
    )

    result = run_cli("digest", "demo")

    assert result.stdout.strip().splitlines()[-1].find("https://example.test/feed") != -1
