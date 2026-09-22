"""HTTP surface: the two routes, the JSON envelope and CORS headers."""

import time

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .controls import parse_controls
from .conversion import convert_source
from .errors import DatagateError
from .projection import response_body
from .store import DatasetStore

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

        body = response_body(table, parse_controls(request.args, table.columns))
        body["query_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return jsonify(body)

    @app.errorhandler(DatagateError)
    def handle_datagate_error(error):
        return _error(error.status, error.message)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return _error(error.code, error.description)

    app.after_request(_with_cors)
    return app


def _error(status, message):
    return jsonify(ok=False, error=message), status


def _with_cors(response):
    response.headers.update(CORS_HEADERS)
    return response
