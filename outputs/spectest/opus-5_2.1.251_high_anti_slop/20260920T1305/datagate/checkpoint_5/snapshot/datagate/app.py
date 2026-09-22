"""HTTP layer: routes, the JSON response envelope and CORS headers."""

import time

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

from .caching import may_reuse, read_cache_enabled
from .errors import DataGateError
from .export import render_csv
from .fetching import fetch_source
from .filtering import read_filters
from .parsing import parse_source
from .query import read_controls, select_rows, shape_rows
from .store import Dataset, DatasetStore, dataset_id
from .uploads import read_upload


def create_app() -> Flask:
    """Build the datagate application with its dataset store.

    Reads ``CACHE_ENABLED`` once here, so an unusable value fails startup.
    """
    app = Flask(__name__)
    app.json.sort_keys = False
    store = DatasetStore()
    cache_enabled = read_cache_enabled()

    @app.after_request
    def allow_cross_origin(response: Response) -> Response:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    @app.errorhandler(DataGateError)
    def report_error(error: DataGateError):
        return jsonify(ok=False, error=error.message), error.status

    @app.errorhandler(HTTPException)
    def report_http_error(error: HTTPException):
        return jsonify(ok=False, error=error.description), error.code

    @app.get("/convert")
    def convert():
        """Fetch, parse and store a remote file, returning its dataset endpoint.

        A source converted before is answered from the store, unless caching is off or
        the request carries ``force``, either of which re-ingests and replaces it. A
        failed re-ingestion leaves the dataset already stored untouched.
        """
        source = request.args.get("source")
        if not source:
            raise DataGateError("query parameter 'source' is required", 400)

        identifier = dataset_id(source)
        if may_reuse(request.args, enabled=cache_enabled) and store.has(identifier):
            return jsonify(ok=True, endpoint=f"/datasets/{identifier}")

        columns, rows = parse_source(fetch_source(source), request.args.get("charset"))
        store.add(Dataset(origin=source, columns=columns, rows=rows))
        return jsonify(ok=True, endpoint=f"/datasets/{identifier}")

    @app.post("/upload")
    def upload():
        """Parse and store a posted file, returning its dataset endpoint.

        The endpoint is derived from the file's bytes, so posting the same file twice
        addresses the same dataset.
        """
        posted = read_upload(request)
        columns, rows = parse_source(posted.data, request.args.get("charset"))
        identifier = store.add(
            Dataset(origin=posted.origin, columns=columns, rows=rows)
        )
        return jsonify(ok=True, endpoint=f"/datasets/{identifier}")

    @app.get("/datasets/<identifier>")
    def read_dataset(identifier: str):
        """Return a dataset's rows, filtered, sorted, paginated and shaped on request."""
        started = time.perf_counter()
        dataset = store.get(identifier)
        controls = read_controls(request.args, dataset.columns)
        filters = read_filters(request.args, dataset.columns)

        selection = select_rows(dataset, controls, filters)
        body = {
            "ok": True,
            "columns": dataset.columns,
            "rows": shape_rows(selection, dataset.columns, controls),
        }
        if controls.with_total:
            body["total"] = selection.total
        body["query_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return jsonify(body)

    @app.get("/datasets/<identifier>/export")
    def export_dataset(identifier: str):
        """Return the same rows as ``/datasets/<id>`` as a downloadable CSV file.

        Filters, sorting and pagination apply as they do to the JSON endpoint, while
        the response-shaping controls have nothing to act on and are ignored.
        """
        dataset = store.get(identifier)
        controls = read_controls(request.args, dataset.columns)
        filters = read_filters(request.args, dataset.columns)

        selection = select_rows(dataset, controls, filters)
        document = render_csv(dataset.columns, [row for _, row in selection.rows])
        return Response(
            document,
            content_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{identifier}.csv"'
            },
        )

    return app
