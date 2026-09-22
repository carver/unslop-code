"""HTTP layer: routes, the JSON response envelope and CORS headers."""

import time

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

from .errors import DataGateError
from .fetching import fetch_source
from .filtering import read_filters
from .parsing import parse_table
from .query import read_controls, select_rows
from .store import Dataset, DatasetStore


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
        """Return a dataset's rows, filtered, sorted, paginated and shaped on request."""
        started = time.perf_counter()
        dataset = store.get(identifier)
        controls = read_controls(request.args, dataset.columns)
        filters = read_filters(request.args, dataset.columns)

        selection = select_rows(dataset, controls, filters)
        body = {"ok": True, "columns": dataset.columns, "rows": selection.rows}
        if controls.with_total:
            body["total"] = selection.total
        body["query_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return jsonify(body)

    return app
