"""HTTP layer: routes, the JSON envelope and CORS."""

import time

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .errors import ApiError
from .ingestion import ingest
from .store import DatasetStore

DEFAULT_ROW_LIMIT = 100
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
        """Serve a stored dataset's columns and a window of its rows."""
        started = time.perf_counter()
        dataset = store.get(identifier)
        if dataset is None:
            raise ApiError(404, f"unknown dataset '{identifier}'")

        rows = dataset.rows[: _row_limit(request.args.get("limit"))]
        return jsonify(
            ok=True,
            columns=dataset.columns,
            rows=rows,
            query_ms=round((time.perf_counter() - started) * 1000, 3),
        )

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


def _row_limit(requested: str | None) -> int:
    """Row window for a dataset read: a positive `limit`, else the default 100."""
    if requested and requested.isdigit() and int(requested) > 0:
        return int(requested)
    return DEFAULT_ROW_LIMIT
