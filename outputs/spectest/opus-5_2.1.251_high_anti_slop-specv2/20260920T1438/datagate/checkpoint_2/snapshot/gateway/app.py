"""HTTP layer: routes, CORS headers and error rendering."""

from time import perf_counter

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from gateway.errors import GateError, error_response
from gateway.fetching import fetch, validate_source
from gateway.parsing import decode_payload, parse_table
from gateway.query import parse_query
from gateway.results import build_body
from gateway.store import Dataset, DatasetStore
from gateway.values import coerce_rows


def create_app(store: DatasetStore | None = None) -> Flask:
    """Build the datagate application, optionally on top of an existing store."""
    app = Flask(__name__)
    datasets = store if store is not None else DatasetStore()

    @app.get("/convert")
    def convert():
        """Ingest a remote CSV and answer with the endpoint serving it."""
        source = request.args.get("source")
        if not source:
            raise GateError("Query parameter 'source' is required", 400)

        validate_source(source)
        text = decode_payload(fetch(source), request.args.get("charset"))
        columns, rows = parse_table(text)
        identifier = datasets.save(
            Dataset(source=source, columns=columns, rows=coerce_rows(rows))
        )
        return jsonify({"ok": True, "endpoint": f"/datasets/{identifier}"})

    @app.get("/datasets/<identifier>")
    def read_dataset(identifier: str):
        """Return the stored table, sorted, paginated and shaped as asked."""
        started = perf_counter()
        dataset = datasets.get(identifier)
        if dataset is None:
            raise GateError(f"Unknown dataset: {identifier!r}", 404)

        body = build_body(dataset, parse_query(request.args, dataset.columns))
        body["query_ms"] = round((perf_counter() - started) * 1000, 3)
        return jsonify(body)

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
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    return app
