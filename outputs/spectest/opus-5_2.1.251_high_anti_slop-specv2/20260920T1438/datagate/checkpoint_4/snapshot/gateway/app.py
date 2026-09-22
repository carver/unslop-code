"""HTTP layer: routes, CORS headers and error rendering."""

from time import perf_counter

from flask import Flask, jsonify, request
from flask.wrappers import Response
from werkzeug.exceptions import HTTPException

from gateway.errors import GateError, error_response
from gateway.export import csv_response
from gateway.fetching import fetch, read_upload, validate_source
from gateway.ingestion import build_table
from gateway.query import parse_query
from gateway.results import build_body, select_rows
from gateway.store import Dataset, DatasetStore, upload_origin
from gateway.values import coerce_rows


def create_app(store: DatasetStore | None = None) -> Flask:
    """Build the datagate application, optionally on top of an existing store."""
    app = Flask(__name__)
    datasets = store if store is not None else DatasetStore()

    def ingest(origin: str, payload: bytes) -> Response:
        """Parse a payload into a dataset and answer with its endpoint."""
        columns, rows = build_table(payload, request.args.get("charset"))
        identifier = datasets.save(
            Dataset(origin=origin, columns=columns, rows=coerce_rows(rows))
        )
        return jsonify({"ok": True, "endpoint": f"/datasets/{identifier}"})

    def load(identifier: str) -> Dataset:
        """Return the stored dataset, or fail the request when the id is unknown."""
        dataset = datasets.get(identifier)
        if dataset is None:
            raise GateError(f"Unknown dataset: {identifier!r}", 404)
        return dataset

    @app.get("/convert")
    def convert():
        """Ingest a remote table and answer with the endpoint serving it."""
        source = request.args.get("source")
        if not source:
            raise GateError("Query parameter 'source' is required", 400)

        validate_source(source)
        return ingest(source, fetch(source))

    @app.post("/upload")
    def upload():
        """Ingest an uploaded table and answer with the endpoint serving it."""
        payload = read_upload(request)
        return ingest(upload_origin(payload), payload)

    @app.get("/datasets/<identifier>")
    def read_dataset(identifier: str):
        """Return the stored table, sorted, paginated and shaped as asked."""
        started = perf_counter()
        dataset = load(identifier)
        body = build_body(dataset, parse_query(request.args, dataset.columns))
        body["query_ms"] = round((perf_counter() - started) * 1000, 3)
        return jsonify(body)

    @app.get("/datasets/<identifier>/export")
    def export_dataset(identifier: str):
        """Serve the same rows as a CSV download, in source column order.

        The response shaping parameters have no CSV equivalent and are ignored
        here; the filters, the sort and the pagination all still apply.
        """
        dataset = load(identifier)
        page, _ = select_rows(dataset, parse_query(request.args, dataset.columns))
        return csv_response(identifier, dataset.columns, [row for _, row in page])

    @app.errorhandler(GateError)
    def on_gate_error(exc: GateError):
        return error_response(str(exc), exc.status)

    @app.errorhandler(HTTPException)
    def on_http_error(exc: HTTPException):
        """Render Flask's own errors -- unknown routes above all -- as JSON."""
        return error_response(exc.description, exc.code)

    @app.after_request
    def allow_cross_origin(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    return app
