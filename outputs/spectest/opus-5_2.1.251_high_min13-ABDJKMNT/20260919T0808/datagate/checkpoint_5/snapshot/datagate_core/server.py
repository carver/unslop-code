"""HTTP surface: the ingestion, dataset and export routes, and the JSON envelope."""

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from datagate_core.caching import cache_enabled, is_forced
from datagate_core.controls import parse_controls
from datagate_core.errors import (
    DataGateError,
    DatasetNotFoundError,
    InvalidRequestError,
)
from datagate_core.exporting import csv_attachment
from datagate_core.fetching import fetch, validate_url
from datagate_core.filters import parse_filters
from datagate_core.ingestion import ingest
from datagate_core.store import DatasetStore, dataset_id
from datagate_core.tables import Table
from datagate_core.timing import Deadline
from datagate_core.uploads import uploaded_bytes
from datagate_core.views import page_of, render


def create_app() -> Flask:
    """Build the datagate application with its own dataset store.

    Reading `CACHE_ENABLED` here is what makes an invalid setting fail startup.
    """
    app = Flask(__name__)
    # Wildcard origin on every response, so browsers can read successes and errors alike.
    CORS(app, origins="*", send_wildcard=True, methods=["GET", "POST", "OPTIONS"])
    store = DatasetStore()
    caching = cache_enabled()

    @app.get("/convert")
    def convert():
        source = request.args.get("source", "")
        if not source:
            raise InvalidRequestError("query parameter 'source' is required")
        validate_url(source)
        forced = is_forced(request.args)

        identifier = dataset_id(source)
        # Ingesting before storing is what keeps a failed re-ingestion from
        # disturbing the dataset a previous request left behind.
        if forced or not caching or not store.has(identifier):
            store.save(source, ingest(fetch(source), request.args.get("charset") or None))
        return jsonify(ok=True, endpoint=f"/datasets/{identifier}")

    @app.post("/upload")
    def upload():
        # The file's bytes are both what is parsed and what the id is derived from.
        data = uploaded_bytes(request)
        table = ingest(data, request.args.get("charset") or None)
        return jsonify(ok=True, endpoint=f"/datasets/{store.save(data, table)}")

    @app.get("/datasets/<dataset_id>")
    def dataset(dataset_id):
        deadline = Deadline()
        table = _stored(store, dataset_id)
        controls = parse_controls(request.args, table.columns)
        filters = parse_filters(request.args, table.columns)
        return jsonify(
            ok=True,
            **render(table, controls, filters, deadline),
            query_ms=deadline.elapsed_ms,
        )

    @app.get("/datasets/<dataset_id>/export")
    def export(dataset_id):
        table = _stored(store, dataset_id)
        # The presentation controls are still validated here, but only filtering,
        # sorting and pagination reach the CSV (T38).
        controls = parse_controls(request.args, table.columns)
        filters = parse_filters(request.args, table.columns)
        page, _ = page_of(table, controls, filters, Deadline())
        return csv_attachment(dataset_id, table.columns, page)

    _register_error_handlers(app)
    return app


def _stored(store: DatasetStore, dataset_id: str) -> Table:
    """The table saved under `dataset_id`, or the 404 that its absence is."""
    table = store.get(dataset_id)
    if table is None:
        raise DatasetNotFoundError(f"unknown dataset: {dataset_id}")
    return table


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
