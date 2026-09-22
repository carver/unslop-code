"""Spec sections: `serve` Command, its bind defaults and browser targets."""

import http.client
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager

from conftest import MVAULT, run_cli, v1_catalog, v1_entry, v3_catalog, v3_entry, write_vault

DEFAULT_PORT = 8840
SOURCE = "https://example.test/a"


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def browser_stub(tmp_path):
    """A `BROWSER` command that records the URL it is asked to open."""
    script = tmp_path / "browser.sh"
    recorded = tmp_path / "opened-url.txt"
    script.write_text(f'#!/bin/sh\nprintf "%s" "$1" > {recorded}\n')
    script.chmod(0o755)
    return f"{script} %s", recorded


def wait_for(host, port, process):
    """Block until the viewer accepts connections, or the process gives up."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        assert process.poll() is None, "serve exited before binding"
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError(f"serve never bound {host}:{port}")


@contextmanager
def serving(tmp_path, *args, host="127.0.0.1", port=None):
    """Run `mvault.py serve` until the block ends; yields the recorded URL path."""
    port = port or free_port()
    command, recorded = browser_stub(tmp_path)
    log = (tmp_path / "serve.log").open("w")
    process = subprocess.Popen(
        [sys.executable, str(MVAULT), "serve", *args, f"--port={port}"],
        cwd=str(tmp_path),
        stdout=log,
        stderr=log,
        env={**os.environ, "BROWSER": command},
    )
    try:
        wait_for(host, port, process)
        yield port, recorded
    finally:
        process.terminate()
        process.wait(timeout=10)
        log.close()


def fetch(host, port, path):
    connection = http.client.HTTPConnection(host, port, timeout=10)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read().decode("utf-8")
    finally:
        connection.close()


def opened_url(recorded):
    """The URL the browser stub was handed, once it has been written."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if recorded.exists() and recorded.read_text():
            return recorded.read_text()
        time.sleep(0.05)
    raise AssertionError("no browser URL was opened")


# `serve` Required Public Surface: "CLI `serve` command | Required"; Syntax:
# "`python mvault.py serve [<name>] [--host=<host>] [--port=<port>]`".
def test_serve_is_a_documented_subcommand():
    result = run_cli("--help", cwd=".")

    assert result.returncode == 0
    assert "serve" in result.stdout


# `serve` Command: "`serve` without `<name>` | Start server and open browser
# to `/`".
def test_serve_without_a_name_opens_the_landing_page(tmp_path):
    with serving(tmp_path) as (port, recorded):
        assert opened_url(recorded) == f"http://127.0.0.1:{port}/"
        assert fetch("127.0.0.1", port, "/")[0] == 200


# `serve` Command: "`serve <name>` | Start server and open browser to default
# category page for vault"; v3 defaults to `episodes`.
def test_serve_with_a_name_opens_the_default_category_page(tmp_path):
    write_vault(tmp_path, v3_catalog(SOURCE, episodes=[v3_entry("e1")]))

    with serving(tmp_path, "demo") as (port, recorded):
        assert opened_url(recorded) == f"http://127.0.0.1:{port}/catalog/demo/episodes"


# `serve` Command: "`serve <name>` | ... default category page for vault" —
# Version-Aware Default Category Redirect: "v1 | `/catalog/<name>/entries`".
def test_serve_with_a_v1_name_opens_the_entries_page(tmp_path):
    write_vault(tmp_path, v1_catalog([v1_entry("e1")]))

    with serving(tmp_path, "demo") as (port, recorded):
        assert opened_url(recorded) == f"http://127.0.0.1:{port}/catalog/demo/entries"


# `serve` Command: "`--host=<host>` | Override bind host; the browser URL uses
# this host as given".
def test_host_option_binds_and_names_that_host(tmp_path):
    with serving(tmp_path, "--host=localhost", host="localhost") as (port, recorded):
        assert opened_url(recorded) == f"http://localhost:{port}/"
        assert fetch("localhost", port, "/")[0] == 200


# `serve` Command: "`--port=<port>` | Override bind port".
def test_port_option_binds_that_port(tmp_path):
    with serving(tmp_path) as (port, _):
        assert fetch("127.0.0.1", port, "/")[0] == 200


# `serve` Command: "Default bind address | `127.0.0.1:8840`"; Determinism:
# "Default port | `8840`".
def test_default_bind_address_is_localhost_8840(tmp_path):
    command, _ = browser_stub(tmp_path)
    log = (tmp_path / "serve.log").open("w")
    process = subprocess.Popen(
        [sys.executable, str(MVAULT), "serve"],
        cwd=str(tmp_path),
        stdout=log,
        stderr=log,
        env={**os.environ, "BROWSER": command},
    )
    try:
        wait_for("127.0.0.1", DEFAULT_PORT, process)
        assert fetch("127.0.0.1", DEFAULT_PORT, "/")[0] == 200
    finally:
        process.terminate()
        process.wait(timeout=10)
        log.close()


# `serve` Required Public Surface: "HTTP behavior defined above | Required" —
# the served viewer answers the catalog routes, not only `/`.
def test_served_viewer_answers_catalog_routes(tmp_path):
    write_vault(tmp_path, v3_catalog(SOURCE, episodes=[v3_entry("e1")]))

    with serving(tmp_path) as (port, _):
        status, body = fetch("127.0.0.1", port, "/catalog/demo/episodes")

    assert status == 200
    assert "title-e1" in body
