"""HTTP layer: routes, the JSON envelope and CORS."""

import time

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

from .budget import Deadline
from .controls import Controls, Page, parse_controls, render_rows, select_rows
from .errors import ApiError
from .exporting import to_csv
from .filtering import parse_filters
from .ingestion import ingest_source, ingest_upload
from .store import Dataset, DatasetStore
from .uploads import uploaded_bytes

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}


def create_app() -> Flask:
    """Build the datagate application with its own dataset store."""
    app = Flask(__name__)
    store = DatasetStore()

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
        """The success envelope both ingestion routes answer with."""
        store.save(dataset)
        return jsonify(ok=True, endpoint=f"/datasets/{dataset.id}")

    @app.get("/convert")
    def convert():
        """Ingest the file at `source` and hand back its dataset endpoint."""
        source = request.args.get("source", "")
        if not source.strip():
            raise ApiError(400, "query parameter 'source' is required")
        return endpoint_of(ingest_source(source, request.args.get("charset")))

    @app.post("/upload")
    def upload():
        """Ingest an uploaded file and hand back its dataset endpoint."""
        raw = uploaded_bytes(request)
        return endpoint_of(ingest_upload(raw, request.args.get("charset")))

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
