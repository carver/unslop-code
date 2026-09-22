"""HTTP layer: ingestion, dataset queries, exports, CORS and the JSON response envelope."""

import time
from dataclasses import replace

from flask import Flask, Request, jsonify, request
from werkzeug.exceptions import HTTPException

from caching import parse_force
from config import Settings
from errors import DatagateError
from exporting import csv_response
from fetching import fetch_bytes, validate_url
from ingestion import parse_payload
from limits import check_source_size
from origins import REFERER_HEADER, check_origin
from querying import DEFAULT_SHAPE, parse_query, select_rows
from store import DatasetStore, dataset_id_for

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Max-Age": "86400",
}
UPLOAD_FIELDS = ("file", "attachment")


def error_response(status: int, message: str):
    return jsonify(ok=False, error=message), status


def endpoint_response(dataset_id: str, require_tls: bool):
    """The reply both ingestion endpoints give: where the dataset is now served from.

    The endpoint is a path on this service, so it is returned relative. Where TLS is required it
    is returned as an absolute `https://` URL on the requested host instead, which keeps a client
    that reached the service over plain HTTP from following it back over plain HTTP.
    """
    path = f"/datasets/{dataset_id}"
    endpoint = f"https://{request.host}{path}" if require_tls else path
    return jsonify(ok=True, endpoint=endpoint)


def read_upload(upload_request: Request) -> bytes:
    """Take the uploaded file's bytes from a multipart request.

    A request that is not multipart cannot carry one at all, which is a 415; a multipart request
    that is malformed or names neither upload field is a 400.
    """
    if not upload_request.mimetype.startswith("multipart/"):
        raise DatagateError(415, "Upload requires a multipart/form-data request")
    for field in UPLOAD_FIELDS:
        if field in upload_request.files:
            return upload_request.files[field].read()
    raise DatagateError(400, f"Upload needs a {' or '.join(UPLOAD_FIELDS)} form field")


def create_app(settings: Settings) -> Flask:
    """Build the datagate application around the dataset store `settings` points at.

    With caching enabled, a `/convert` of an already-converted source URL is answered from the
    store; without it, every `/convert` downloads and parses the source afresh.
    """
    app = Flask(__name__)
    # Serialise dicts in insertion order so object-shaped rows keep their source column order.
    app.json.sort_keys = False
    datasets = DatasetStore(settings.storage_dir)

    @app.get("/convert")
    def convert():
        """Fetch a remote CSV or workbook and expose it under a stable dataset endpoint.

        A cached source is served straight from the store unless `force` asks for it to be
        ingested again. Re-ingestion only replaces the stored dataset once it has parsed, so a
        source that has since broken leaves the previous dataset queryable.
        """
        source = request.args.get("source", "").strip()
        if not source:
            raise DatagateError(400, "Query parameter 'source' is required")
        validate_url(source)
        force = parse_force(request.args)
        charset = request.args.get("charset", "").strip() or None

        origin = source.encode()
        cached_id = dataset_id_for(origin)
        if settings.cache_enabled and not force and datasets.holds(cached_id):
            return endpoint_response(cached_id, settings.require_tls)
        data = fetch_bytes(source)
        check_source_size(len(data), settings.max_source_size)
        dataset = parse_payload(data, charset)
        return endpoint_response(datasets.save(origin, dataset), settings.require_tls)

    @app.post("/upload")
    def upload():
        """Ingest an uploaded CSV or workbook, keyed by its content so re-uploads share an id."""
        data = read_upload(request)
        check_source_size(len(data), settings.max_source_size)
        dataset = parse_payload(data, None)
        return endpoint_response(datasets.save(data, dataset), settings.require_tls)

    @app.get("/datasets/<dataset_id>")
    def read_dataset(dataset_id: str):
        """Return the stored columns and a filtered, sorted, paginated, shaped page of rows."""
        started = time.perf_counter()
        dataset = datasets.require(dataset_id)

        query = parse_query(request.args, dataset.columns)
        page = select_rows(dataset, query)
        payload = {"ok": True, "columns": dataset.columns, "rows": page.rows}
        if query.show_total:
            payload["total"] = page.total
        payload["query_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return jsonify(payload)

    @app.get("/datasets/<dataset_id>/export")
    def export_dataset(dataset_id: str):
        """Return the rows the dataset endpoint would return, rendered as a CSV attachment.

        Filters, sorting and pagination apply as usual; the response-shape parameters have
        nothing to say about a CSV file, so the rows are always selected as lists.
        """
        dataset = datasets.require(dataset_id)
        query = parse_query(request.args, dataset.columns)
        page = select_rows(dataset, replace(query, shape=DEFAULT_SHAPE))
        return csv_response(dataset_id, dataset.columns, page.rows)

    @app.before_request
    def enforce_origin_allowlist():
        """Apply the allowlist to every request, including ones no route would have served."""
        check_origin(request.headers.get(REFERER_HEADER), settings.origin_allowlist)

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
