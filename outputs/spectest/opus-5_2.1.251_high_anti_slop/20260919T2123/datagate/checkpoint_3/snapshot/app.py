"""HTTP layer: ingestion, dataset queries, CORS and the JSON response envelope."""

import time

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from csv_parsing import parse_table
from errors import DatagateError
from fetching import fetch_bytes, validate_url
from querying import parse_query, select_rows
from store import Dataset, DatasetStore

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Max-Age": "86400",
}


def error_response(status: int, message: str):
    return jsonify(ok=False, error=message), status


def create_app() -> Flask:
    """Build the datagate application around a fresh in-memory dataset store."""
    app = Flask(__name__)
    # Serialise dicts in insertion order so object-shaped rows keep their source column order.
    app.json.sort_keys = False
    datasets = DatasetStore()

    @app.get("/convert")
    def convert():
        """Fetch a remote CSV and expose it under a stable dataset endpoint."""
        source = request.args.get("source", "").strip()
        if not source:
            raise DatagateError(400, "Query parameter 'source' is required")
        validate_url(source)
        charset = request.args.get("charset", "").strip() or None

        columns, rows = parse_table(fetch_bytes(source), charset)
        dataset_id = datasets.save(source, Dataset(columns, rows))
        return jsonify(ok=True, endpoint=f"/datasets/{dataset_id}")

    @app.get("/datasets/<dataset_id>")
    def read_dataset(dataset_id: str):
        """Return the stored columns and a filtered, sorted, paginated, shaped page of rows."""
        started = time.perf_counter()
        dataset = datasets.get(dataset_id)
        if dataset is None:
            raise DatagateError(404, f"Unknown dataset id: {dataset_id!r}")

        query = parse_query(request.args, dataset.columns)
        page = select_rows(dataset, query)
        payload = {"ok": True, "columns": dataset.columns, "rows": page.rows}
        if query.show_total:
            payload["total"] = page.total
        payload["query_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return jsonify(payload)

    @app.errorhandler(DatagateError)
    def handle_datagate_error(exc: DatagateError):
        return error_response(exc.status, exc.message)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        """Render framework errors (unknown routes, wrong methods) with the JSON envelope."""
        return error_response(exc.code, f"{exc.name}: {request.path}")

    @app.after_request
    def allow_cross_origin(response):
        response.headers.update(CORS_HEADERS)
        return response

    return app
