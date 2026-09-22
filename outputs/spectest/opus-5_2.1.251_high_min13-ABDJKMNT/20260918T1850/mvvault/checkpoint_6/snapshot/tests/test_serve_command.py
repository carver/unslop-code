"""Spec section: `serve` Command, `serve` Required Public Surface."""

import time

from conftest import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    v1_catalog,
    v1_entry,
    v3_catalog,
    v3_entry,
    write_vault,
)


def opened(viewer):
    """The URL `serve` sent to the browser, waiting briefly for it to appear."""
    deadline = time.time() + 10
    while time.time() < deadline and not viewer.opened_urls:
        time.sleep(0.05)
    assert viewer.opened_urls, f"no browser URL recorded:\n{viewer.output()}"
    return viewer.opened_urls[0]


# Spec: CLI `serve` command | Required
def test_serve_is_a_subcommand(run):
    assert "serve" in run("--help").stdout


# Spec: Syntax | `serve [<name>] [--host=<host>] [--port=<port>]`
def test_serve_accepts_name_host_and_port(run):
    assert "serve" in run("serve", "--help").stdout
    assert "--host" in run("serve", "--help").stdout
    assert "--port" in run("serve", "--help").stdout


# Spec: Default bind address | `127.0.0.1:8840`
def test_server_binds_the_default_address_without_options(serve):
    viewer = serve(flags=False, host=DEFAULT_HOST, port=DEFAULT_PORT)
    assert viewer.get("/").status_code == 200


# Spec: `--port=<port>` | Override bind port
def test_port_option_overrides_the_bind_port(serve):
    viewer = serve()
    assert not viewer.base.endswith(str(DEFAULT_PORT))
    assert viewer.get("/").status_code == 200


# Spec: `--host=<host>` | Override bind host
def test_host_option_overrides_the_bind_host(serve):
    viewer = serve(host="127.0.0.2")
    assert viewer.get("/").status_code == 200


# Spec: `serve` without `<name>` | Start server and open browser to `/`
def test_serve_without_a_name_opens_the_landing_page(serve):
    viewer = serve()
    assert opened(viewer) == f"{viewer.base}/"


# Spec: `serve <name>` | Start server and open browser to default category page
def test_serve_with_a_name_opens_the_default_category_page(serve, tmp_path):
    write_vault(tmp_path, v3_catalog(episodes=[v3_entry("e1")]))
    viewer = serve("vault")
    assert opened(viewer) == f"{viewer.base}/catalog/vault/episodes"


# Spec: `serve <name>` | ... default category page for vault (version-aware)
def test_serve_with_a_v1_name_opens_the_entries_page(serve, tmp_path):
    write_vault(tmp_path, v1_catalog(entries=[v1_entry("e1")]))
    viewer = serve("vault")
    assert opened(viewer) == f"{viewer.base}/catalog/vault/entries"


# Spec: The viewer works on vaults of any supported version without prior migration
def test_serving_a_legacy_vault_leaves_its_catalog_alone(serve, tmp_path):
    catalog = v1_catalog(entries=[v1_entry("e1")])
    directory = write_vault(tmp_path, catalog)
    stored = (directory / "catalog.json").read_text()

    viewer = serve("vault")
    assert viewer.get("/catalog/vault/entries").status_code == 200
    assert (directory / "catalog.json").read_text() == stored
    assert not (directory / "catalog.bak").exists()
