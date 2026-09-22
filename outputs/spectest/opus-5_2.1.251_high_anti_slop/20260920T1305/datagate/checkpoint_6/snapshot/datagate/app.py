"""HTTP layer: routes, the JSON response envelope, CORS headers and endpoint URLs."""

import time

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

from .caching import may_reuse
from .config import load_config
from .errors import DataGateError
from .export import render_csv
from .fetching import fetch_source
from .filtering import read_filters
from .parsing import parse_source
from .policy import check_origin, check_source_size
from .query import read_controls, select_rows, shape_rows
from .store import Dataset, DatasetStore, dataset_id
from .uploads import read_upload


def dataset_endpoint(identifier: str, *, host: str, require_tls: bool) -> str:
    """Return the endpoint a converted dataset is served at.

    It is a path on the serving host, or the absolute ``https://`` URL of that same
    path when ``REQUIRE_TLS`` asks clients to come back over TLS.
    """
    path = f"/datasets/{identifier}"
    return f"https://{host}{path}" if require_tls else path


def create_app() -> Flask:
    """Build the datagate application with its dataset store.

    The configuration is read once here, so an unusable setting fails startup.
    """
    config = load_config()
    app = Flask(__name__)
    app.json.sort_keys = False
    store = DatasetStore(config.storage_dir)

    @app.before_request
    def enforce_allowlist() -> None:
        """Turn away requests from outside ``ORIGIN_ALLOWLIST``, before routing."""
        check_origin(request.headers.get("Referer"), config.origin_allowlist)

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
        endpoint = dataset_endpoint(
            identifier, host=request.host, require_tls=config.require_tls
        )
        reusable = may_reuse(request.args, enabled=config.cache_enabled)
        if reusable and store.has(identifier):
            return jsonify(ok=True, endpoint=endpoint)

        data = fetch_source(source)
        check_source_size(len(data), config.max_source_size)
        columns, rows = parse_source(data, request.args.get("charset"))
        store.add(Dataset(origin=source, columns=columns, rows=rows))
        return jsonify(ok=True, endpoint=endpoint)

    @app.post("/upload")
    def upload():
        """Parse and store a posted file, returning its dataset endpoint.

        The endpoint is derived from the file's bytes, so posting the same file twice
        addresses the same dataset.
        """
        posted = read_upload(request)
        check_source_size(len(posted.data), config.max_source_size)
        columns, rows = parse_source(posted.data, request.args.get("charset"))
        identifier = store.add(
            Dataset(origin=posted.origin, columns=columns, rows=rows)
        )
        endpoint = dataset_endpoint(
            identifier, host=request.host, require_tls=config.require_tls
        )
        return jsonify(ok=True, endpoint=endpoint)

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
