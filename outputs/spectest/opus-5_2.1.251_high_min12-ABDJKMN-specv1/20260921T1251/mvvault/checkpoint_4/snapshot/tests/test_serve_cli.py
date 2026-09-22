"""Spec section: `serve` Command / `serve` Required Public Surface.

| Syntax | `python mvault.py serve [<name>] [--host=<host>] [--port=<port>]` |
"""

from __future__ import annotations

import re


def payload_with(helpers, **categories):
    return helpers.make_payload(
        **{name: [helpers.make_source_entry(i) for i in ids]
           for name, ids in categories.items()})


# ---------------------------------------------------------------------------
# | CLI `serve` command | Required |
# ---------------------------------------------------------------------------

# Spec: | CLI `serve` command | Required |
def test_serve_is_an_available_subcommand(run_cli):
    result = run_cli("--help")
    assert "serve" in result.stdout


# Spec: | Syntax | `python mvault.py serve [<name>] ...` |
# Context: `<name>` is optional, so bare `serve` is accepted.
def test_serve_without_name_starts_a_server(serve):
    process = serve()
    assert process.client.get("/").status == 200


# Spec: | Syntax | `python mvault.py serve [<name>] ...` |
# Context: a vault name is accepted as the single positional argument.
def test_serve_with_name_starts_a_server(serve, vault, catalogs, make_vault):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    process = serve("vault")
    assert process.client.get("/").status == 200


# Spec: | `serve` command | Required | (public surface: the process keeps serving)
def test_serve_keeps_running_after_a_request(serve):
    process = serve()
    assert process.client.get("/").status == 200
    assert process.client.get("/").status == 200
    assert process.proc.poll() is None


# ---------------------------------------------------------------------------
# | Default bind address | `127.0.0.1:8840` |
# ---------------------------------------------------------------------------

# Spec: | Default bind address | `127.0.0.1:8840` |
# Context: with neither override given, the server binds the documented address.
def test_default_bind_address_is_localhost_8840(serve, viewer_helpers):
    process = serve(port=None)  # no --port, no --host: pure defaults
    assert process.host == viewer_helpers.DEFAULT_HOST
    assert process.port == viewer_helpers.DEFAULT_PORT


# Spec: | Default port | `8840` | (Determinism)
def test_default_port_is_8840_in_the_announced_url(serve, viewer_helpers):
    process = serve(port=None)
    assert any(f":{viewer_helpers.DEFAULT_PORT}" in url for url in process.urls()), \
        process.output()


# ---------------------------------------------------------------------------
# | `serve` without `<name>` | Start server and open browser to `/` |
# ---------------------------------------------------------------------------

# Spec: | `serve` without `<name>` | Start server and open browser to `/` |
def test_serve_without_name_targets_the_landing_page(serve):
    process = serve()
    urls = process.urls()
    assert urls, process.output()
    target = urls[-1]
    assert re.fullmatch(rf"http://[^/]+:{process.port}/?", target), target


# ---------------------------------------------------------------------------
# | `serve <name>` | Start server and open browser to default category page
#   for vault |
# ---------------------------------------------------------------------------

# Spec: | `serve <name>` | ... open browser to default category page for vault |
# Context: a v3 vault's default category page is `/catalog/<name>/episodes`.
def test_serve_name_targets_the_v3_default_category_page(
    serve, make_vault, catalogs
):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    process = serve("vault")
    assert any(url.endswith("/catalog/vault/episodes") for url in process.urls()), \
        process.output()


# Spec: | `serve <name>` | ... default category page for vault |
# Context: a v1 vault's default category page is `/catalog/<name>/entries`.
def test_serve_name_targets_the_v1_default_category_page(
    serve, make_vault, legacy
):
    make_vault(legacy.v1_catalog(entries=[legacy.v1_entry("e1")]))
    process = serve("vault")
    assert any(url.endswith("/catalog/vault/entries") for url in process.urls()), \
        process.output()


# Spec: | `serve <name>` | ... default category page for vault |
# Context: a v2 vault's default category page is `/catalog/<name>/episodes`.
def test_serve_name_targets_the_v2_default_category_page(
    serve, make_vault, legacy
):
    make_vault(legacy.v2_catalog(episodes=[legacy.v2_entry("e1")]))
    process = serve("vault")
    assert any(url.endswith("/catalog/vault/episodes") for url in process.urls()), \
        process.output()


# ---------------------------------------------------------------------------
# | `--host=<host>` | Override bind host; the browser URL uses this host as
#   given |
# ---------------------------------------------------------------------------

# Spec: | `--host=<host>` | Override bind host ... |
def test_host_override_binds_the_given_host(serve):
    process = serve("--host=0.0.0.0")
    assert process.client.get("/").status == 200


# Spec: | `--host=<host>` | ... the browser URL uses this host as given |
def test_host_override_appears_verbatim_in_the_browser_url(serve):
    process = serve("--host=0.0.0.0")
    assert any(url.startswith("http://0.0.0.0:") for url in process.urls()), \
        process.output()


# Spec: | `--host=<host>` | ... this host as given |
# Context: `localhost` is served and echoed as written, not canonicalized to an IP.
def test_host_override_is_not_canonicalized(serve):
    process = serve("--host=localhost")
    assert any(url.startswith("http://localhost:") for url in process.urls()), \
        process.output()


# ---------------------------------------------------------------------------
# | `--port=<port>` | Override bind port |
# ---------------------------------------------------------------------------

# Spec: | `--port=<port>` | Override bind port |
def test_port_override_binds_the_given_port(serve, viewer_helpers):
    chosen = viewer_helpers.free_port()
    process = serve(f"--port={chosen}", port=None)
    assert process.port == chosen
    assert process.client.get("/").status == 200


# Spec: | `--port=<port>` | Override bind port |
# Context: the browser URL carries the overridden port.
def test_port_override_appears_in_the_browser_url(serve, viewer_helpers):
    chosen = viewer_helpers.free_port()
    process = serve(f"--port={chosen}", port=None)
    assert any(f":{chosen}" in url for url in process.urls()), process.output()


# Spec: | `--host=<host>` | ... | `--port=<port>` | ... |
# Context: both overrides together, with a vault name.
def test_host_and_port_overrides_combine_with_a_name(
    serve, make_vault, catalogs, viewer_helpers
):
    make_vault(catalogs.catalog(episodes=[catalogs.entry("e1")]))
    chosen = viewer_helpers.free_port()
    process = serve("vault", "--host=127.0.0.1", f"--port={chosen}", port=None)
    assert any(url == f"http://127.0.0.1:{chosen}/catalog/vault/episodes"
               for url in process.urls()), process.output()
