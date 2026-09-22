"""Spec: the `serve` Command table and `serve` Required Public Surface."""
import pytest

from digest_helpers import v1, v1_entry, v2, v3, v3_entry, legacy_entry
from viewer_helpers import DEFAULT_HOST, DEFAULT_PORT, free_port, port_is_free


# Spec: "| CLI `serve` command | Required |" -- the subcommand exists and is
# advertised by the top-level help.
def test_serve_is_a_documented_subcommand(run):
    res = run("--help")
    assert res.returncode == 0, res
    assert "serve" in res.stdout


# Spec: "| Syntax | `python mvault.py serve [<name>] [--host=<host>]
# [--port=<port>]` |" -- `<name>` is optional.
def test_serve_accepts_no_positional_argument(serve):
    server = serve()
    assert server.get("/").status == 200


# Spec: "| Syntax | ... serve [<name>] ... |" -- and accepts one vault name.
def test_serve_accepts_a_vault_name(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    server = serve("vault")
    assert server.get("/").status == 200


# Spec: "| Default bind address | `127.0.0.1:8840` |"
def test_default_bind_address_is_127_0_0_1_8840(serve):
    if not port_is_free(DEFAULT_PORT):
        pytest.skip("port %d already in use on this machine" % DEFAULT_PORT)
    server = serve(use_default_port=True)
    assert server.host == DEFAULT_HOST
    assert server.port == DEFAULT_PORT
    assert server.get("/").status == 200


# Spec: "| `--port=<port>` | Override bind port |"
def test_port_option_overrides_the_bind_port(serve):
    port = free_port()
    server = serve(port=port)
    assert server.port == port
    assert server.get("/").status == 200


# Spec: "| `--host=<host>` | Override bind host |"
def test_host_option_overrides_the_bind_host(serve):
    server = serve(host="localhost")
    assert server.get("/").status == 200


# Spec: "| `serve` without `<name>` | Start server and open browser to `/` |"
def test_serve_without_name_opens_the_landing_page(serve):
    server = serve()
    urls = server.wait_browser_urls()
    assert len(urls) == 1, urls
    assert urls[0] == "%s/" % server.origin


# Spec: "| `serve <name>` | Start server and open browser to default category
# page for vault |" -- a v3 vault resolves to `episodes`.
def test_serve_with_v3_name_opens_the_episodes_page(serve, make_vault):
    make_vault(v3(episodes=[v3_entry(id="e1")]))
    server = serve("vault")
    assert server.wait_browser_urls() == ["%s/catalog/vault/episodes" % server.origin]


# Spec: "| `serve <name>` | ... default category page for vault |" -- a v1
# vault resolves to `entries`.
def test_serve_with_v1_name_opens_the_entries_page(serve, make_vault):
    make_vault(v1(entries=[v1_entry(id="e1")]))
    server = serve("vault")
    assert server.wait_browser_urls() == ["%s/catalog/vault/entries" % server.origin]


# Spec: "| `serve <name>` | ... default category page for vault |" -- a v2
# vault resolves to `episodes`.
def test_serve_with_v2_name_opens_the_episodes_page(serve, make_vault):
    make_vault(v2(episodes=[legacy_entry(id="e1")]))
    server = serve("vault")
    assert server.wait_browser_urls() == ["%s/catalog/vault/episodes" % server.origin]


# Spec: "| Default bind address | `127.0.0.1:8840` |" + `--host`/`--port` --
# the opened URL uses the address the server actually bound.
def test_browser_url_uses_the_overridden_address(serve):
    port = free_port()
    server = serve(port=port)
    assert server.wait_browser_urls() == ["http://127.0.0.1:%d/" % port]


# Spec: "The viewer works on vaults of any supported version without requiring
# prior migration." -- serving a v1 vault leaves `catalog.json` byte-identical.
def test_serving_a_v1_vault_does_not_migrate_it(serve, make_vault):
    directory = make_vault(v1(entries=[v1_entry(id="e1")]))
    before = (directory / "catalog.json").read_bytes()
    server = serve("vault")
    assert server.get("/catalog/vault/entries").status == 200
    assert (directory / "catalog.json").read_bytes() == before
    assert not (directory / "catalog.bak").exists()


# Spec: "The viewer works on vaults of any supported version without requiring
# prior migration." -- likewise for v2.
def test_serving_a_v2_vault_does_not_migrate_it(serve, make_vault):
    directory = make_vault(v2(episodes=[legacy_entry(id="e1")]))
    before = (directory / "catalog.json").read_bytes()
    server = serve("vault")
    assert server.get("/catalog/vault/episodes").status == 200
    assert (directory / "catalog.json").read_bytes() == before
