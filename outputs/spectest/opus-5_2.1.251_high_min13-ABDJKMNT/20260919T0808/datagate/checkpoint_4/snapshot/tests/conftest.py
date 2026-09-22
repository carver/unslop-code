"""Shared fixtures: a datagate test client, a local origin server, and workbook builders."""

import csv
import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import xlwt
from openpyxl import Workbook

from datagate_core.server import create_app


class OriginServer:
    """Local HTTP server that serves byte payloads registered by the tests."""

    def __init__(self, host, port):
        self._responses = {}
        self.base_url = f"http://{host}:{port}"

    def serve(self, path, body, status=200, content_type="text/csv"):
        """Register `body` (bytes or str) at `path` and return its absolute URL."""
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self._responses[path] = (status, content_type, payload)
        return f"{self.base_url}{path}"

    def url_for(self, path):
        return f"{self.base_url}{path}"

    def response_for(self, path):
        return self._responses.get(path)


@pytest.fixture(scope="session")
def origin():
    server_state = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            registered = server_state["origin"].response_for(self.path)
            if registered is None:
                self.send_error(404, "not registered")
                return
            status, content_type, payload = registered
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_state["origin"] = OriginServer(*httpd.server_address)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield server_state["origin"]
    httpd.shutdown()


@pytest.fixture
def client():
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


@pytest.fixture
def convert(client, origin):
    """Serve `body` at a unique path, convert it, and return the parsed JSON."""
    counter = iter(range(1000))

    def _convert(body, query="", path=None, **serve_kwargs):
        url = origin.serve(path or f"/fixture-{next(counter)}.csv", body, **serve_kwargs)
        return client.get(f"/convert?source={url}{query}")

    return _convert


@pytest.fixture
def dataset(client, convert):
    """Convert `body` and return the parsed `/datasets/<id>` payload."""

    def _dataset(body, query="", dataset_query="", **serve_kwargs):
        converted = convert(body, query=query, **serve_kwargs)
        assert converted.status_code == 200, converted.get_json()
        endpoint = converted.get_json()["endpoint"]
        response = client.get(f"{endpoint}{dataset_query}")
        assert response.status_code == 200, response.get_json()
        return response.get_json()

    return _dataset


SIMPLE_CSV = "name,age\nada,36\ngrace,45\n"


@pytest.fixture
def endpoint(client, convert):
    """Convert `body` once, then issue raw `/datasets/<id>` queries against it."""

    def _endpoint(body=None, **serve_kwargs):
        converted = convert(body if body is not None else SIMPLE_CSV, **serve_kwargs)
        assert converted.status_code == 200, converted.get_json()
        path = converted.get_json()["endpoint"]
        return lambda query="": client.get(f"{path}{query}")

    return _endpoint


def numbered_csv(count, columns="n,tag"):
    """A `count`-row CSV whose rows are `<i>,row<i>` for i in 0..count-1."""
    return f"{columns}\n" + "".join(f"{i},row{i}\n" for i in range(count))


#: Ties in `team` (blue, red, blue, red) exercise stability; `age` is numeric.
TEAMS_CSV = "name,team,age\nada,blue,36\ngrace,red,45\nalan,blue,41\nedsger,red,30\n"


@pytest.fixture
def upload(client):
    """POST `body` to `/upload` as a multipart file part and return the response."""

    def _upload(body, field="file", filename="data.csv"):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        return client.post(
            "/upload",
            data={field: (io.BytesIO(payload), filename)},
            content_type="multipart/form-data",
        )

    return _upload


@pytest.fixture
def uploaded(client, upload):
    """Upload `body`, assert it converted, and return raw `/datasets/<id>` access."""

    def _uploaded(body, **upload_kwargs):
        response = upload(body, **upload_kwargs)
        assert response.status_code == 200, response.get_json()
        path = response.get_json()["endpoint"]
        return lambda suffix="": client.get(f"{path}{suffix}")

    return _uploaded


def xlsx_bytes(*sheets):
    """Serialise sheets - each a list of row lists - into `.xlsx` bytes."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for index, rows in enumerate(sheets):
        sheet = workbook.create_sheet(f"sheet{index}")
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def xls_bytes(*sheets):
    """Serialise sheets - each a list of row lists - into legacy `.xls` bytes."""
    book = xlwt.Workbook()
    for index, rows in enumerate(sheets):
        sheet = book.add_sheet(f"sheet{index}")
        for row_number, row in enumerate(rows):
            for column_number, cell in enumerate(row):
                sheet.write(row_number, column_number, cell)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def exported_rows(response):
    """Parse an `/export` response body back into a list of row lists."""
    return list(csv.reader(io.StringIO(response.get_data(as_text=True))))


#: The `TEAMS_CSV` table as spreadsheet rows, with `age` stored as a number.
TEAMS_SHEET = [
    ["name", "team", "age"],
    ["ada", "blue", 36],
    ["grace", "red", 45],
    ["alan", "blue", 41],
    ["edsger", "red", 30],
]
