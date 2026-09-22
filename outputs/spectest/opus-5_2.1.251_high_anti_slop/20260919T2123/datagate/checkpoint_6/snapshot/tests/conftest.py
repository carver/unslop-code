"""Shared fixtures: a throwaway HTTP server that serves CSV and workbook fixtures to the app."""

import io
import threading
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import openpyxl
import pytest
import xlwt
from flask.testing import FlaskClient

from app import create_app
from config import Settings

STAFF_ROWS = [
    ["name", "role", "age", "rating"],
    ["Ada", "engineer", 36, 9.5],
    ["Grace", "engineer", 45, 8.25],
    ["Alan", "analyst", 41, 9.5],
    ["ada", "analyst", 29, "n/a"],
]
# A second worksheet that no endpoint should ever read.
NOTES_ROWS = [["note"], ["only the first sheet is ingested"]]


def xlsx_bytes(sheets: dict[str, list[list]]) -> bytes:
    """Build an .xlsx workbook in memory, one worksheet per name, in order."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def xls_bytes(sheets: dict[str, list[list]]) -> bytes:
    """Build a legacy .xls workbook in memory, one worksheet per name, in order."""
    workbook = xlwt.Workbook()
    for title, rows in sheets.items():
        sheet = workbook.add_sheet(title)
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                sheet.write(row_index, column_index, value)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def zip_bytes() -> bytes:
    """A zip archive that is not a workbook: it opens, but holds no worksheets."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "name,age\nAda,36\n")
    return buffer.getvalue()


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
    "ties.csv": b"team,player\nblue,ada\nred,grace\nblue,alan\nred,edsger\n",
    "mixed.csv": b"name,score\nAda,7\nGrace,n/a\nAlan,2\n",
    "quoted.csv": b'name,note\nAda,"first, and foremost"\nGrace,"said ""hi"""\n',
    "staff.csv": (
        b"name,role,age,rating\n"
        b"Ada,engineer,36,9.5\n"
        b"Grace,engineer,45,8.25\n"
        b"Alan,analyst,41,9.5\n"
        b"ada,analyst,29,n/a\n"
    ),
    "staff.xlsx": xlsx_bytes({"staff": STAFF_ROWS, "notes": NOTES_ROWS}),
    "staff.xls": xls_bytes({"staff": STAFF_ROWS, "notes": NOTES_ROWS}),
    "header_only.xlsx": xlsx_bytes({"staff": [["name", "age"]]}),
    "header_only.xls": xls_bytes({"staff": [["name", "age"]]}),
    "accents.xlsx": xlsx_bytes({"people": [["name", "city"], ["José", "Málaga"]]}),
    "archive.xlsx": zip_bytes(),
}


@pytest.fixture(scope="session")
def fixtures_root(tmp_path_factory):
    """The directory the fixture server serves, written out once for the whole session."""
    root = tmp_path_factory.mktemp("fixtures")
    for name, content in FIXTURES.items():
        (root / name).write_bytes(content)
    return root


@pytest.fixture(scope="session")
def base_url(fixtures_root):
    """Serve the fixture files on a loopback port for the duration of the test session."""
    handler = partial(SimpleHTTPRequestHandler, directory=str(fixtures_root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def changing_source(fixtures_root):
    """Write and rewrite one fixture file, so a test can change what a source URL serves.

    The name is unique to the test, which keeps a rewrite from reaching any other test, and it is
    what the write returns so the test can convert it.
    """
    name = f"{uuid4().hex}.csv"

    def write(content: bytes) -> str:
        (fixtures_root / name).write_bytes(content)
        return name

    return write


@pytest.fixture
def make_client(tmp_path):
    """Build a test client for a service configured however the test needs it.

    Each client gets its own storage directory under the test's own temporary path, so nothing a
    test ingests reaches another one.
    """

    def build(**overrides) -> FlaskClient:
        settings = Settings(storage_dir=tmp_path / "storage", **overrides)
        return create_app(settings).test_client()

    return build


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def uncached_client(make_client):
    return make_client(cache_enabled=False)
