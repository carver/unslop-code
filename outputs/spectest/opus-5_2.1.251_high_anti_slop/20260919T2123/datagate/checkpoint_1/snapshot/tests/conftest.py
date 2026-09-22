"""Shared fixtures: a throwaway HTTP server that serves CSV fixtures to the app."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import create_app

FIXTURES = {
    "basic.csv": b"name,age,score,start\nAda,36,9.5,08:30\nGrace,45,8.25,9:15\n",
    "semicolon.csv": b"city;population\nOslo;709000\nBergen;286000\n",
    "tabbed.tsv": b"product\tprice\nWidget\t19.99\nGadget\t5\n",
    "latin1.csv": "name,city\nJosé,Málaga\nRené,Nîmes\n".encode("cp1252"),
    "latin1_semicolon.csv": "name;city\nJosé;Málaga\nRené;Nîmes\n".encode("cp1252"),
    "bom.csv": "name,city\nAda,Bath\n".encode("utf-8-sig"),
    "header_only.csv": b"name,age\n",
    "page.html": b"<html><body><p>Not a table at all.</p></body></html>\n",
    "wide.csv": b"n,label\n" + b"".join(b"%d,row%d\n" % (i, i) for i in range(150)),
}


@pytest.fixture(scope="session")
def base_url(tmp_path_factory):
    """Serve the fixture files on a loopback port for the duration of the test session."""
    root = tmp_path_factory.mktemp("fixtures")
    for name, content in FIXTURES.items():
        (root / name).write_bytes(content)

    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def client():
    return create_app().test_client()
