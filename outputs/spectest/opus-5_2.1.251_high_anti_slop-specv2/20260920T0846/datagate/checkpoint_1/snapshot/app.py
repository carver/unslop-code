"""HTTP surface of datagate: CSV ingestion and dataset queries."""

import time

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from errors import ApiError
from fetcher import fetch, validate_source
from store import Dataset, DatasetStore
from tabular import decode, parse

DEFAULT_ROW_LIMIT = 100


def create_app(store: DatasetStore | None = None) -> Flask:
    """Build the datagate application, optionally over a pre-seeded store."""
    app = Flask(__name__)
    datasets = store if store is not None else DatasetStore()

    @app.get("/convert")
    def convert():
        """Fetch a remote CSV and expose it under a stable dataset endpoint."""
        source = request.args.get("source")
        if not source:
            raise ApiError("Query parameter 'source' is required", 400)

        validate_source(source)
        columns, rows = parse(decode(fetch(source), request.args.get("charset")))
        dataset_id = datasets.add(Dataset(source, columns, rows))
        return jsonify(ok=True, endpoint=f"/datasets/{dataset_id}")

    @app.get("/datasets/<dataset_id>")
    def read_dataset(dataset_id: str):
        """Return the stored columns and up to ``limit`` rows, in source order."""
        started = time.perf_counter()
        dataset = datasets.get(dataset_id)
        if dataset is None:
            raise ApiError(f"Unknown dataset {dataset_id!r}", 404)

        rows = dataset.rows[: _row_limit()]
        query_ms = round((time.perf_counter() - started) * 1000, 3)
        return jsonify(ok=True, columns=dataset.columns, rows=rows, query_ms=query_ms)

    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return jsonify(ok=False, error=error.message), error.status

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        """Render framework errors (unknown routes, bad methods) as JSON too."""
        return jsonify(ok=False, error=error.description), error.code

    @app.after_request
    def allow_cross_origin(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    return app


def _row_limit() -> int:
    """Read the optional ``limit`` query parameter, defaulting to 100 rows."""
    raw = request.args.get("limit")
    if raw is None:
        return DEFAULT_ROW_LIMIT
    if not raw.isdigit():
        raise ApiError("Query parameter 'limit' must be a non-negative integer", 400)
    return int(raw)
