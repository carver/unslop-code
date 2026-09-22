"""HTTP surface: the origin gate, the ingestion, dataset and export routes, and the envelope."""

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from datagate_core.access import REFERER_HEADER, check_referer
from datagate_core.caching import is_forced
from datagate_core.config import Settings, load_settings
from datagate_core.controls import parse_controls
from datagate_core.datasets import Dataset
from datagate_core.enrichment import wants_enrichment
from datagate_core.errors import (
    DataGateError,
    DatasetNotFoundError,
    InvalidRequestError,
)
from datagate_core.exporting import csv_attachment
from datagate_core.fetching import fetch, validate_url
from datagate_core.filters import parse_filters
from datagate_core.ingestion import ingest
from datagate_core.limits import check_source_size
from datagate_core.store import DatasetStore, dataset_id
from datagate_core.timing import Deadline
from datagate_core.uploads import uploaded_bytes
from datagate_core.views import page_of, render


def create_app() -> Flask:
    """Build the datagate application from the service configuration.

    Settings are read here, which is what makes an unreadable config file or an
    invalid value stop startup instead of surfacing on some later request; the
    dataset store is opened on the `STORAGE_DIR` they name.
    """
    settings = load_settings()
    app = Flask(__name__)
    # Wildcard origin on every response, so browsers can read successes and errors alike.
    CORS(app, origins="*", send_wildcard=True, methods=["GET", "POST", "OPTIONS"])
    store = DatasetStore(settings.storage_dir)

    @app.before_request
    def check_origin():
        """Gate every request on the allowlist, ahead of routing (T66)."""
        check_referer(request.headers.get(REFERER_HEADER), settings.origin_allowlist)

    @app.get("/convert")
    def convert():
        source = request.args.get("source", "")
        if not source:
            raise InvalidRequestError("query parameter 'source' is required")
        validate_url(source)
        forced = is_forced(request.args)
        enrich = wants_enrichment(request.args)

        identifier = dataset_id(source)
        cached = store.get(identifier) if settings.cache_enabled else None
        # Ingesting before storing is what keeps a failed re-ingestion from
        # disturbing the dataset a previous request left behind (T82).
        if forced or _must_ingest(cached, enrich):
            data = fetch(source)
            check_source_size(data, settings.max_source_size)
            store.save(source, ingest(data, request.args.get("charset") or None, enrich))
        return jsonify(ok=True, endpoint=_endpoint(settings, identifier))

    @app.post("/upload")
    def upload():
        # The file's bytes are both what is parsed and what the id is derived from.
        data = uploaded_bytes(request)
        check_source_size(data, settings.max_source_size)
        # `enrich` is a `/convert` parameter, so an upload is never enriched (T79).
        uploaded = ingest(data, request.args.get("charset") or None, enrich=False)
        return jsonify(ok=True, endpoint=_endpoint(settings, store.save(data, uploaded)))

    @app.get("/datasets/<dataset_id>")
    def dataset(dataset_id):
        deadline = Deadline()
        stored = _stored(store, dataset_id)
        table = stored.table
        controls = parse_controls(request.args, table.columns)
        filters = parse_filters(request.args, table.columns)
        return jsonify(
            ok=True,
            **render(table, controls, filters, deadline),
            # Empty for a dataset ingested without enrichment, which is how a
            # plain response comes to carry no metadata fields at all (T83).
            **stored.metadata,
            query_ms=deadline.elapsed_ms,
        )

    @app.get("/datasets/<dataset_id>/export")
    def export(dataset_id):
        table = _stored(store, dataset_id).table
        # The presentation controls are still validated here, but only filtering,
        # sorting and pagination reach the CSV (T38).
        controls = parse_controls(request.args, table.columns)
        filters = parse_filters(request.args, table.columns)
        page, _ = page_of(table, controls, filters, Deadline())
        return csv_attachment(dataset_id, table.columns, page)

    _register_error_handlers(app)
    return app


def _endpoint(settings: Settings, identifier: str) -> str:
    """The dataset endpoint as `/convert` and `/upload` advertise it.

    Relative by default; under `REQUIRE_TLS` it is the same path as an absolute
    `https://` URL on the host the request itself named (T69).
    """
    path = f"/datasets/{identifier}"
    return f"https://{request.host}{path}" if settings.require_tls else path


def _must_ingest(cached: Dataset | None, enrich: bool) -> bool:
    """Whether `/convert` has to ingest rather than answer from the store.

    Nothing cached has to be ingested, and so does an enriching request that
    finds a dataset stored without metadata - that is the upgrade enrichment
    forces. A plain request over an enriched dataset re-ingests nothing, which
    is what leaves the stored enrichment state alone.
    """
    return cached is None or (enrich and not cached.metadata)


def _stored(store: DatasetStore, dataset_id: str) -> Dataset:
    """The dataset saved under `dataset_id`, or the 404 that its absence is."""
    dataset = store.get(dataset_id)
    if dataset is None:
        raise DatasetNotFoundError(f"unknown dataset: {dataset_id}")
    return dataset


def _register_error_handlers(app: Flask) -> None:
    """Render every failure - ours and Flask's - as the JSON error envelope."""

    @app.errorhandler(DataGateError)
    def handle_datagate_error(error: DataGateError):
        return jsonify(ok=False, error=str(error)), error.status

    @app.errorhandler(HTTPException)
    def handle_http_exception(error: HTTPException):
        return jsonify(ok=False, error=error.description), error.code

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        app.logger.exception("unhandled error", exc_info=error)
        return jsonify(ok=False, error="internal server error"), 500
