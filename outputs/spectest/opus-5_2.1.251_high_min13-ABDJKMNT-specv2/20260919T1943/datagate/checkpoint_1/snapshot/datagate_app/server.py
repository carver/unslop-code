"""HTTP layer: routes, the JSON envelope and CORS."""

import time

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .errors import DataGateError
from .ingestion import build_dataset
from .store import DatasetStore

DEFAULT_ROW_LIMIT = 100


def create_app(store: DatasetStore | None = None) -> Flask:
    """Build the datagate application, optionally over a pre-populated store."""
    app = Flask(__name__)
    datasets = store if store is not None else DatasetStore()

    @app.get("/convert")
    def convert():
        source = request.args.get("source")
        if not source:
            raise DataGateError("Missing required query parameter 'source'", 400)
        identifier = datasets.save(source, build_dataset(source, request.args.get("charset")))
        return jsonify(ok=True, endpoint=f"/datasets/{identifier}")

    @app.get("/datasets/<dataset_id>")
    def query_dataset(dataset_id):
        started = time.perf_counter()
        dataset = datasets.get(dataset_id)
        if dataset is None:
            raise DataGateError(f"Unknown dataset: {dataset_id!r}", 404)
        rows = dataset.rows[: _row_limit(request.args.get("limit"))]
        elapsed_ms = (time.perf_counter() - started) * 1000
        return jsonify(ok=True, columns=dataset.columns, rows=rows, query_ms=round(elapsed_ms, 3))

    _register_error_handlers(app)
    _register_cors(app)
    return app


def _row_limit(raw: str | None) -> int:
    """Honour a usable `limit` override, otherwise page at the default size."""
    if raw is not None and raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_ROW_LIMIT


def _register_error_handlers(app: Flask) -> None:
    """Render every failure -- ours and the framework's -- as the JSON envelope."""

    @app.errorhandler(DataGateError)
    def handle_datagate_error(error: DataGateError):
        return jsonify(ok=False, error=str(error)), error.status

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):
        return jsonify(ok=False, error=error.description), error.code


def _register_cors(app: Flask) -> None:
    """Allow browsers on any origin to read the API, errors included."""

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response
