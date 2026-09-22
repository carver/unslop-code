"""HTTP surface: the two routes, the JSON envelope and CORS headers."""

import time

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .conversion import convert_source
from .errors import DatagateError
from .store import DatasetStore

DEFAULT_ROW_LIMIT = 100
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Max-Age": "86400",
}


def create_app(store=None):
    """Build the datagate Flask application, optionally over an existing store."""
    app = Flask(__name__)
    datasets = store if store is not None else DatasetStore()

    @app.get("/convert")
    def convert():
        identifier = convert_source(
            request.args.get("source"), request.args.get("charset"), datasets
        )
        return jsonify(ok=True, endpoint=f"/datasets/{identifier}")

    @app.get("/datasets/<identifier>")
    def dataset(identifier):
        started = time.perf_counter()
        table = datasets.get(identifier)
        if table is None:
            raise DatagateError(404, f"Unknown dataset id: {identifier!r}.")

        rows = table.rows[: _row_limit(request.args.get("limit"))]
        elapsed_ms = (time.perf_counter() - started) * 1000
        return jsonify(ok=True, columns=table.columns, rows=rows, query_ms=round(elapsed_ms, 3))

    @app.errorhandler(DatagateError)
    def handle_datagate_error(error):
        return _error(error.status, error.message)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return _error(error.code, error.description)

    app.after_request(_with_cors)
    return app


def _row_limit(requested):
    """Rows per response: 100 by default, overridable with `?limit=<positive int>`."""
    if requested is not None and requested.isdigit() and int(requested) > 0:
        return int(requested)
    return DEFAULT_ROW_LIMIT


def _error(status, message):
    return jsonify(ok=False, error=message), status


def _with_cors(response):
    response.headers.update(CORS_HEADERS)
    return response
