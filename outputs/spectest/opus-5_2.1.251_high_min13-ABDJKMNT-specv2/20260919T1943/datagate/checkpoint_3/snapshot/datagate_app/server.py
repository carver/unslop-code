"""HTTP layer: routes, the JSON envelope and CORS."""

import time

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .controls import parse_controls
from .errors import DataGateError
from .filtering import parse_filters
from .ingestion import build_dataset
from .results import build_body
from .store import DatasetStore


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
        controls = parse_controls(request.args, dataset.columns)
        body = build_body(dataset, controls, parse_filters(request.args, dataset.columns))
        elapsed_ms = (time.perf_counter() - started) * 1000
        return jsonify(**body, query_ms=round(elapsed_ms, 3))

    _register_error_handlers(app)
    _register_cors(app)
    return app


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
