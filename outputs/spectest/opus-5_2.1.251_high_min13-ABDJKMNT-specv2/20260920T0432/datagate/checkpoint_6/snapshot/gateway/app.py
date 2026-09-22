"""HTTP layer: routes, the JSON envelope, the origin allowlist and CORS."""

import os
import time

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

from .access import check_origin
from .budget import Deadline
from .caching import forced
from .config import load_settings
from .controls import Controls, Page, parse_controls, render_rows, select_rows
from .errors import ApiError
from .exporting import to_csv
from .filtering import parse_filters
from .ingestion import ingest_source, ingest_upload
from .store import Dataset, DatasetStore, dataset_id
from .uploads import uploaded_bytes

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}


def create_app(environ=os.environ) -> Flask:
    """Build the datagate application from the configuration in `environ`.

    Raises `ConfigError` if that configuration is unusable — an unreadable
    config file, a setting outside its type, a storage directory that cannot be
    created — so a misconfigured process fails at startup instead of serving.
    """
    settings = load_settings(environ)
    app = Flask(__name__)
    store = DatasetStore(settings.storage_dir)

    def read_page(identifier: str) -> tuple[Dataset, Controls, Page]:
        """Apply the current request's controls and filters to a stored dataset.

        Both dataset routes select their rows through here, which is what makes
        an export answer the same query string with the same rows.
        """
        dataset = store.get(identifier)
        if dataset is None:
            raise ApiError(404, f"unknown dataset '{identifier}'")
        controls = parse_controls(request.args, dataset.columns)
        filters = parse_filters(request.args, dataset.columns)
        return dataset, controls, select_rows(dataset.rows, controls, filters, Deadline())

    def endpoint_of(dataset: Dataset) -> Response:
        """The success envelope both ingestion routes answer with.

        Under `REQUIRE_TLS` the endpoint is absolute and addressed to the host
        the caller used; otherwise it stays relative to it.
        """
        path = f"/datasets/{dataset.id}"
        endpoint = f"https://{request.host}{path}" if settings.require_tls else path
        return jsonify(ok=True, endpoint=endpoint)

    def cached_dataset(source: str) -> Dataset | None:
        """The stored dataset this request may be answered from, if any.

        A cache hit needs caching to be on for the process and `force` to be
        absent from the request; `force` is validated either way, since a
        valued flag is a caller mistake no configuration excuses.
        """
        if forced(request.args) or not settings.cache_enabled:
            return None
        return store.get(dataset_id(source))

    @app.get("/convert")
    def convert():
        """Ingest the file at `source` and hand back its dataset endpoint.

        A source already converted skips the download entirely, answering with
        the envelope its first conversion produced. Otherwise it is fetched and
        parsed afresh, and only a successful parse replaces what is stored — a
        failed re-ingestion leaves the previous dataset queryable.
        """
        source = request.args.get("source", "")
        if not source.strip():
            raise ApiError(400, "query parameter 'source' is required")
        cached = cached_dataset(source)
        if cached is not None:
            return endpoint_of(cached)
        dataset = ingest_source(
            source, request.args.get("charset"), settings.max_source_size
        )
        store.save(dataset)
        return endpoint_of(dataset)

    @app.post("/upload")
    def upload():
        """Ingest an uploaded file and hand back its dataset endpoint.

        An upload carries its own bytes, so there is nothing to re-download and
        nothing to serve from the cache: it is always a fresh parse.
        """
        dataset = ingest_upload(
            uploaded_bytes(request), request.args.get("charset"), settings.max_source_size
        )
        store.save(dataset)
        return endpoint_of(dataset)

    @app.get("/datasets/<identifier>")
    def read_dataset(identifier):
        """Serve a stored dataset's columns and the window of rows asked for."""
        started = time.perf_counter()
        dataset, controls, page = read_page(identifier)
        payload = {
            "ok": True,
            "columns": dataset.columns,
            "rows": render_rows(page.rows, dataset.columns, controls),
        }
        if controls.show_total:
            payload["total"] = page.total
        payload["query_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return jsonify(payload)

    @app.get("/datasets/<identifier>/export")
    def export_dataset(identifier):
        """Serve the same window of rows as a CSV file attachment.

        The response shape controls are parsed like everywhere else but say
        nothing about CSV, which always carries the source columns alone.
        """
        dataset, _, page = read_page(identifier)
        body = to_csv(dataset.columns, [row for _, row in page.rows])
        return Response(
            body,
            headers={
                "Content-Type": "text/csv",
                "Content-Disposition": f'attachment; filename="{dataset.id}.csv"',
            },
        )

    @app.before_request
    def enforce_origin_allowlist():
        """Hold every request to the allowlist, ahead of the route lookup."""
        check_origin(request.headers.get("Referer"), settings.origin_allowlist)

    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return jsonify(ok=False, error=error.message), error.status

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        """Answer routing and method failures with the JSON envelope too."""
        return jsonify(ok=False, error=error.description), error.code

    @app.after_request
    def allow_cross_origin(response):
        response.headers.update(CORS_HEADERS)
        return response

    return app
