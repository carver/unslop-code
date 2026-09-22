"""HTTP surface of datagate: table ingestion, dataset queries and CSV export."""

import time

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

from cache import cache_enabled, force_requested
from errors import ApiError
from fetcher import fetch, validate_source
from filters import apply_filters, parse_filters
from query import Controls, parse_controls, render, select
from store import Dataset, DatasetStore, Row
from tabular import ingest, to_csv
from uploads import read_upload, upload_origin


def create_app(store: DatasetStore | None = None) -> Flask:
    """Build the datagate application, optionally over a pre-seeded store."""
    app = Flask(__name__)
    datasets = store if store is not None else DatasetStore()
    caching = cache_enabled()

    def resolve(dataset_id: str) -> tuple[Dataset, Controls, list[Row]]:
        """Look up a dataset and narrow it down to the rows a request asks for.

        Both dataset routes read the same filters and controls; they differ
        only in how they present the rows that survive.
        """
        dataset = datasets.get(dataset_id)
        if dataset is None:
            raise ApiError(f"Unknown dataset {dataset_id!r}", 404)

        controls = parse_controls(request.args, dataset.columns)
        matched = apply_filters(dataset.rows, parse_filters(request.args, dataset.columns))
        return dataset, controls, matched

    @app.get("/convert")
    def convert():
        """Fetch a remote table and expose it under a stable dataset endpoint.

        A source that is already stored is served straight from the store,
        unless caching is switched off or the request forces a re-read. The
        stored rows are replaced only once fresh ones have been parsed, so a
        failed re-ingestion leaves the previous dataset queryable.
        """
        source = request.args.get("source")
        if not source:
            raise ApiError("Query parameter 'source' is required", 400)

        validate_source(source)
        forced = force_requested(request.query_string.decode())
        dataset_id = DatasetStore.identify(source)
        if forced or not caching or datasets.get(dataset_id) is None:
            columns, rows = ingest(fetch(source), request.args.get("charset"))
            datasets.add(Dataset(source, columns, rows))
        return jsonify(ok=True, endpoint=f"/datasets/{dataset_id}")

    @app.post("/upload")
    def upload():
        """Ingest an uploaded table, keyed by the bytes rather than by a URL."""
        payload = read_upload(request)
        columns, rows = ingest(payload, request.args.get("charset"))
        dataset_id = datasets.add(Dataset(upload_origin(payload), columns, rows))
        return jsonify(ok=True, endpoint=f"/datasets/{dataset_id}")

    @app.get("/datasets/<dataset_id>")
    def read_dataset(dataset_id: str):
        """Return the columns and the filtered, sorted, paginated, shaped rows."""
        started = time.perf_counter()
        dataset, controls, matched = resolve(dataset_id)
        body = {
            "ok": True,
            "columns": dataset.columns,
            "rows": render(select(matched, controls), dataset.columns, controls),
        }
        if controls.show_total:
            body["total"] = len(matched)
        body["query_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return jsonify(body)

    @app.get("/datasets/<dataset_id>/export")
    def export_dataset(dataset_id: str):
        """Serve the rows of a dataset query as a downloadable CSV file.

        Filters, sorting and pagination all apply. The presentation controls
        (`_shape`, `_rowid`, `_total`) describe a JSON body and have nothing to
        say about a CSV file, which always holds the source columns in order.
        """
        dataset, controls, matched = resolve(dataset_id)
        return Response(
            to_csv(dataset.columns, select(matched, controls)),
            content_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{dataset_id}.csv"'},
        )

    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return jsonify(ok=False, error=error.message), error.status

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        """Render framework errors (unknown routes, bad methods) as JSON too."""
        return jsonify(ok=False, error=error.description), error.code

    @app.after_request
    def allow_cross_origin(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    return app
