"""HTTP layer: routes, the JSON envelope and CORS."""

import time

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

from .access import enforce_allowlist
from .caching import force_requested
from .config import Settings, load_settings
from .controls import parse_controls
from .errors import DataGateError
from .exporting import CONTENT_TYPE, export_csv
from .fetching import fetch_source
from .filtering import parse_filters
from .ingestion import build_dataset
from .parsing import Dataset
from .results import build_body
from .store import DatasetStore, dataset_id, upload_id
from .uploads import uploaded_document


def create_app(store: DatasetStore | None = None) -> Flask:
    """Build the datagate application, optionally over a pre-populated store.

    Reading the settings here is what makes an unusable value fail startup: the
    server never reaches `app.run` (T51). Opening the store is what creates
    `STORAGE_DIR` when it is missing.
    """
    app = Flask(__name__)
    settings = load_settings()
    datasets = store if store is not None else DatasetStore(settings.storage_dir)

    @app.before_request
    def guard_origin():
        """Apply the origin allowlist to every request, routed or not."""
        enforce_allowlist(request.headers.get("Referer"), settings.origin_allowlist)

    @app.get("/convert")
    def convert():
        """Ingest `source`, or answer from the cache when it already holds it.

        A cache hit re-uses the stored dataset untouched, so the response is the
        one the original parse produced and nothing is downloaded again (T55, T56).
        """
        source = request.args.get("source")
        if not source:
            raise DataGateError("Missing required query parameter 'source'", 400)
        identifier = dataset_id(source)
        if force_requested(request.args) or not settings.cache_enabled or datasets.get(identifier) is None:
            document = fetch_source(source)
            datasets.save(identifier, build_dataset(document, request.args.get("charset"), settings.max_source_size))
        return jsonify(ok=True, endpoint=_endpoint(identifier, settings))

    @app.post("/upload")
    def upload():
        document = uploaded_document(request)
        identifier = upload_id(document.data)
        datasets.save(identifier, build_dataset(document, request.args.get("charset"), settings.max_source_size))
        return jsonify(ok=True, endpoint=_endpoint(identifier, settings))

    @app.get("/datasets/<dataset_id>")
    def query_dataset(dataset_id):
        started = time.perf_counter()
        dataset = _require_dataset(datasets, dataset_id)
        controls = parse_controls(request.args, dataset.columns)
        body = build_body(dataset, controls, parse_filters(request.args, dataset.columns))
        elapsed_ms = (time.perf_counter() - started) * 1000
        return jsonify(**body, query_ms=round(elapsed_ms, 3))

    @app.get("/datasets/<dataset_id>/export")
    def export_dataset(dataset_id):
        """Serve the same rows as `/datasets/<id>` as a downloadable CSV file."""
        dataset = _require_dataset(datasets, dataset_id)
        controls = parse_controls(request.args, dataset.columns)
        body = export_csv(dataset, controls, parse_filters(request.args, dataset.columns))
        disposition = f'attachment; filename="{dataset_id}.csv"'
        return Response(body, content_type=CONTENT_TYPE, headers={"Content-Disposition": disposition})

    _register_error_handlers(app)
    _register_cors(app)
    return app


def _endpoint(identifier: str, settings: Settings) -> str:
    """Address a dataset relatively, or absolutely over `https` when TLS is required.

    The absolute form is built from the host the client asked for, so a service
    behind several names advertises the one in hand (T67).
    """
    path = f"/datasets/{identifier}"
    return f"https://{request.host}{path}" if settings.require_tls else path


def _require_dataset(datasets: DatasetStore, identifier: str) -> Dataset:
    """Look up a stored dataset, or raise the 404 that names the missing id."""
    dataset = datasets.get(identifier)
    if dataset is None:
        raise DataGateError(f"Unknown dataset: {identifier!r}", 404)
    return dataset


def _register_error_handlers(app: Flask) -> None:
    """Render every failure -- ours and the framework's -- as the JSON envelope."""

    @app.errorhandler(DataGateError)
    def handle_datagate_error(error: DataGateError):
        return jsonify(ok=False, error=str(error)), error.status

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):
        return jsonify(ok=False, error=error.description), error.code


def _register_cors(app: Flask) -> None:
    """Allow browsers on any origin to read the API, errors included."""

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response
