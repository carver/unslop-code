"""HTTP surface: the `/convert` and `/datasets/<id>` routes and the JSON envelope."""

import time

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from datagate_core.controls import parse_controls
from datagate_core.decoding import decode
from datagate_core.errors import (
    DataGateError,
    DatasetNotFoundError,
    InvalidRequestError,
)
from datagate_core.fetching import fetch, validate_url
from datagate_core.store import DatasetStore
from datagate_core.tables import parse_table
from datagate_core.views import render


def create_app() -> Flask:
    """Build the datagate application with its own dataset store."""
    app = Flask(__name__)
    # Wildcard origin on every response, so browsers can read successes and errors alike.
    CORS(app, origins="*", send_wildcard=True, methods=["GET", "OPTIONS"])
    store = DatasetStore()

    @app.get("/convert")
    def convert():
        source = request.args.get("source", "")
        if not source:
            raise InvalidRequestError("query parameter 'source' is required")
        validate_url(source)

        charset = request.args.get("charset") or None
        table = parse_table(decode(fetch(source), charset))
        return jsonify(ok=True, endpoint=f"/datasets/{store.save(source, table)}")

    @app.get("/datasets/<dataset_id>")
    def dataset(dataset_id):
        started = time.perf_counter()
        table = store.get(dataset_id)
        if table is None:
            raise DatasetNotFoundError(f"unknown dataset: {dataset_id}")

        body = render(table, parse_controls(request.args, table.columns))
        return jsonify(
            ok=True,
            **body,
            query_ms=round((time.perf_counter() - started) * 1000, 3),
        )

    _register_error_handlers(app)
    return app


def _register_error_handlers(app: Flask) -> None:
    """Render every failure - ours and Flask's - as the JSON error envelope."""

    @app.errorhandler(DataGateError)
    def handle_datagate_error(error: DataGateError):
        return jsonify(ok=False, error=str(error)), error.status

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):
        return jsonify(ok=False, error=error.description), error.code

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        app.logger.exception("unhandled error", exc_info=error)
        return jsonify(ok=False, error="internal server error"), 500
