"""HTTP layer: routes, the JSON envelope and CORS."""

import time

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .budget import Deadline
from .controls import parse_controls, render_rows, select_rows
from .errors import ApiError
from .filtering import parse_filters
from .ingestion import ingest
from .store import DatasetStore

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}


def create_app() -> Flask:
    """Build the datagate application with its own dataset store."""
    app = Flask(__name__)
    store = DatasetStore()

    @app.get("/convert")
    def convert():
        """Ingest the CSV at `source` and hand back its dataset endpoint."""
        source = request.args.get("source", "")
        if not source.strip():
            raise ApiError(400, "query parameter 'source' is required")

        dataset = ingest(source, request.args.get("charset"))
        store.save(dataset)
        return jsonify(ok=True, endpoint=f"/datasets/{dataset.id}")

    @app.get("/datasets/<identifier>")
    def read_dataset(identifier):
        """Serve a stored dataset's columns and the window of rows asked for."""
        started = time.perf_counter()
        dataset = store.get(identifier)
        if dataset is None:
            raise ApiError(404, f"unknown dataset '{identifier}'")

        controls = parse_controls(request.args, dataset.columns)
        filters = parse_filters(request.args, dataset.columns)
        page = select_rows(dataset.rows, controls, filters, Deadline())
        payload = {
            "ok": True,
            "columns": dataset.columns,
            "rows": render_rows(page.rows, dataset.columns, controls),
        }
        if controls.show_total:
            payload["total"] = page.total
        payload["query_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return jsonify(payload)

    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return jsonify(ok=False, error=error.message), error.status

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        """Answer routing and method failures with the JSON envelope too."""
        return jsonify(ok=False, error=error.description), error.code

    @app.after_request
    def allow_cross_origin(response):
        response.headers.update(CORS_HEADERS)
        return response

    return app
