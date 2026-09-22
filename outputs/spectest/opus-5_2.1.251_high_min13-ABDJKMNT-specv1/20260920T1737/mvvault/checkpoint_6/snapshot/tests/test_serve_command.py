"""Spec section: `serve` Command -- syntax, bind address and browser URL."""

from conftest import (
    DEFAULT_VIEWER_PORT,
    EPOCH_KEY,
    browser_recorder,
    free_port,
    legacy_entry,
    opened_url,
    v1_catalog,
    v3_catalog,
    v3_entry,
    write_vault,
)


# Phrase: "| Syntax | `python mvault.py serve [<name>] [--host=<host>]
# [--port=<port>]` |" -- the subcommand is part of the CLI surface.
def test_serve_is_listed_as_a_subcommand(run_cli):
    result = run_cli("--help")

    assert result.returncode == 0
    assert "serve" in result.stdout


# Phrase: "| Default bind address | `127.0.0.1:8840` |".
def test_serve_binds_the_default_address(serve_viewer):
    viewer = serve_viewer(port=DEFAULT_VIEWER_PORT)

    assert viewer.client.get("/").status == 200


# Phrase: "| `serve` without `<name>` | Start server and open browser to `/` |".
def test_serve_without_name_opens_the_landing_page(serve_viewer, tmp_path):
    command, record = browser_recorder(tmp_path)
    port = free_port()

    serve_viewer(f"--port={port}", port=port, env={"BROWSER": command})

    assert opened_url(record) == f"http://127.0.0.1:{port}/"


# Phrase: "| `serve <name>` | Start server and open browser to default category
# page for vault |" -- a v3 vault defaults to `episodes`.
def test_serve_with_name_opens_the_default_category_page(serve_viewer, tmp_path):
    write_vault(tmp_path, "demo", v3_catalog("https://example.test/feed", episodes=[v3_entry("e1")]))
    command, record = browser_recorder(tmp_path)
    port = free_port()

    serve_viewer("demo", f"--port={port}", port=port, env={"BROWSER": command})

    assert opened_url(record) == f"http://127.0.0.1:{port}/catalog/demo/episodes"


# Phrase: "| `serve <name>` | ... default category page for vault |" -- the
# resolved category follows the vault version, so a v1 vault opens `entries`.
def test_serve_with_v1_vault_opens_entries(serve_viewer, tmp_path):
    write_vault(tmp_path, "demo", v1_catalog(legacy_entry("e1", EPOCH_KEY)))
    command, record = browser_recorder(tmp_path)
    port = free_port()

    serve_viewer("demo", f"--port={port}", port=port, env={"BROWSER": command})

    assert opened_url(record) == f"http://127.0.0.1:{port}/catalog/demo/entries"


# Phrase: "| `--host=<host>` | Override bind host; the browser URL uses this
# host as given |".
def test_host_override_binds_that_host_and_appears_in_the_browser_url(serve_viewer, tmp_path):
    command, record = browser_recorder(tmp_path)
    port = free_port()

    viewer = serve_viewer(
        "--host=localhost", f"--port={port}", host="localhost", port=port, env={"BROWSER": command}
    )

    assert viewer.client.get("/").status == 200
    assert opened_url(record) == f"http://localhost:{port}/"


# Phrase: "| `--port=<port>` | Override bind port |".
def test_port_override_binds_that_port(serve_viewer):
    port = free_port()

    viewer = serve_viewer(f"--port={port}", port=port)

    assert viewer.client.get("/").status == 200
