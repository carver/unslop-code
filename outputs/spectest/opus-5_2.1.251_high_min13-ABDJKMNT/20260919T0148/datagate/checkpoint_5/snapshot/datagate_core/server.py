"""HTTP surface: the routes, the JSON envelope, the CSV download and CORS headers."""

import time

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .caching import cache_enabled, force_requested
from .controls import parse_controls
from .conversion import convert_source, convert_upload
from .errors import DatagateError
from .exporting import attachment_headers, csv_bytes
from .filtering import parse_filters
from .projection import page_rows, response_body
from .store import DatasetStore
from .timing import Deadline
from .uploads import uploaded_bytes

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Max-Age": "86400",
}


def create_app(store=None):
    """Build the datagate Flask application, optionally over an existing store.

    `CACHE_ENABLED` is read here, so an invalid value fails startup however the
    application is launched (AMBIGUITIES T53).
    """
    app = Flask(__name__)
    datasets = store if store is not None else DatasetStore()
    caching = cache_enabled()

    @app.get("/convert")
    def convert():
        """Convert `source`, from the cache when one is stored and nothing forbids it.

        `force` is read before the setting is consulted so that a repeated flag is
        rejected even when caching is off and the flag would change nothing.
        """
        forced = force_requested(request.args)
        identifier = convert_source(
            request.args.get("source"),
            request.args.get("charset"),
            datasets,
            reuse_cached=caching and not forced,
        )
        return _endpoint_of(identifier)

    @app.post("/upload")
    def upload():
        identifier = convert_upload(
            uploaded_bytes(request), request.args.get("charset"), datasets
        )
        return _endpoint_of(identifier)

    @app.get("/datasets/<identifier>")
    def dataset(identifier):
        started = time.perf_counter()
        table = _table(datasets, identifier)

        body = response_body(table, *_query(table), Deadline())
        body["query_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return jsonify(body)

    @app.get("/datasets/<identifier>/export")
    def export(identifier):
        """Download the page `/datasets/<id>` would return, as a CSV attachment.

        `_shape`, `_rowid` and `_total` are still validated by the shared control
        parser but cannot change the bytes (AMBIGUITIES T34).
        """
        table = _table(datasets, identifier)
        _, page = page_rows(table, *_query(table), Deadline())

        payload = csv_bytes(table.columns, [values for _, values in page])
        return payload, 200, attachment_headers(identifier)

    @app.errorhandler(DatagateError)
    def handle_datagate_error(error):
        return _error(error.status, error.message)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return _error(error.code, error.description)

    app.after_request(_with_cors)
    return app


def _query(table):
    """The controls and filters of the current request, validated against `table`."""
    return parse_controls(request.args, table.columns), parse_filters(request.args, table.columns)


def _table(datasets, identifier):
    """Look a dataset up, raising the documented 404 when it was never converted."""
    table = datasets.get(identifier)
    if table is None:
        raise DatagateError(404, f"Unknown dataset id: {identifier!r}.")
    return table


def _endpoint_of(identifier):
    """The success envelope both ingestion routes answer with."""
    return jsonify(ok=True, endpoint=f"/datasets/{identifier}")


def _error(status, message):
    return jsonify(ok=False, error=message), status


def _with_cors(response):
    response.headers.update(CORS_HEADERS)
    return response
