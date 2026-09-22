"""HTTP layer: routes, the JSON response envelope and CORS headers."""

import time

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

from .errors import DataGateError
from .fetching import fetch_source
from .parsing import parse_table
from .store import Dataset, DatasetStore

DEFAULT_ROW_LIMIT = 100


def _row_limit() -> int:
    """Read the optional ``limit`` query parameter, defaulting to 100 rows."""
    raw = request.args.get("limit")
    if raw is None:
        return DEFAULT_ROW_LIMIT
    if not raw.isdigit() or int(raw) == 0:
        raise DataGateError("query parameter 'limit' must be a positive integer", 400)
    return int(raw)


def create_app() -> Flask:
    """Build the datagate application with its dataset store."""
    app = Flask(__name__)
    app.json.sort_keys = False
    store = DatasetStore()

    @app.after_request
    def allow_cross_origin(response: Response) -> Response:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    @app.errorhandler(DataGateError)
    def report_error(error: DataGateError):
        return jsonify(ok=False, error=error.message), error.status

    @app.errorhandler(HTTPException)
    def report_http_error(error: HTTPException):
        return jsonify(ok=False, error=error.description), error.code

    @app.get("/convert")
    def convert():
        """Fetch, parse and store a remote CSV, returning its dataset endpoint."""
        source = request.args.get("source")
        if not source:
            raise DataGateError("query parameter 'source' is required", 400)

        columns, rows = parse_table(fetch_source(source), request.args.get("charset"))
        identifier = store.add(Dataset(source=source, columns=columns, rows=rows))
        return jsonify(ok=True, endpoint=f"/datasets/{identifier}")

    @app.get("/datasets/<identifier>")
    def read_dataset(identifier: str):
        """Return a stored dataset's columns and its first rows, in source order."""
        started = time.perf_counter()
        dataset = store.get(identifier)
        rows = dataset.rows[: _row_limit()]
        elapsed_ms = (time.perf_counter() - started) * 1000
        return jsonify(
            ok=True,
            columns=dataset.columns,
            rows=rows,
            query_ms=round(elapsed_ms, 3),
        )

    return app
