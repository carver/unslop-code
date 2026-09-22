"""HTTP layer: routes, CORS headers and error rendering."""

from time import perf_counter

from flask import Flask, jsonify, request
from flask.wrappers import Response
from werkzeug.exceptions import HTTPException

from gateway.access import check_referer
from gateway.caching import force_requested
from gateway.config import Settings, load_settings
from gateway.enrichment import describe, enrichment_requested
from gateway.errors import GateError, error_response
from gateway.export import csv_response
from gateway.fetching import enforce_size, fetch, read_upload, validate_source
from gateway.ingestion import build_table
from gateway.query import parse_query
from gateway.results import build_body, select_rows
from gateway.store import Dataset, DatasetStore, dataset_id, upload_origin
from gateway.values import coerce_rows


def create_app(settings: Settings | None = None) -> Flask:
    """Build the datagate application, on the given settings or the ambient ones.

    Settings are read here, so a value that cannot be understood fails the
    startup rather than a request.
    """
    app = Flask(__name__)
    config = settings if settings is not None else load_settings()
    datasets = DatasetStore(config.storage_dir)

    def endpoint_response(identifier: str) -> Response:
        """Answer an ingestion with the endpoint the dataset is readable at.

        The endpoint is relative unless TLS is required, in which case it is
        the absolute ``https`` URL of the host the request arrived on.
        """
        endpoint = f"/datasets/{identifier}"
        if config.require_tls:
            endpoint = f"https://{request.host}{endpoint}"
        return jsonify({"ok": True, "endpoint": endpoint})

    def ingest(origin: str, payload: bytes, enrich: bool) -> Response:
        """Parse a payload into a dataset and answer with its endpoint.

        An enriched ingestion is described before it is stored, so a
        description that cannot be made fails the request with nothing written:
        whatever was stored before stays as enriched as it was.
        """
        enforce_size(payload, config.max_source_size)
        filetype, columns, rows = build_table(payload, request.args.get("charset"))
        values = coerce_rows(rows)
        identifier = datasets.save(
            Dataset(
                origin=origin,
                columns=columns,
                rows=values,
                metadata=describe(filetype, columns, values) if enrich else None,
            )
        )
        return endpoint_response(identifier)

    def cache_answers(identifier: str, enrich: bool) -> bool:
        """Report whether the stored dataset may answer this ``/convert``.

        A dataset stored without a description cannot answer a request asking
        for one; that request re-ingests its source and upgrades what is
        stored. A described one answers either kind of request.
        """
        dataset = datasets.get(identifier) if config.cache_enabled else None
        return dataset is not None and not (enrich and dataset.metadata is None)

    def load(identifier: str) -> Dataset:
        """Return the stored dataset, or fail the request when the id is unknown."""
        dataset = datasets.get(identifier)
        if dataset is None:
            raise GateError(f"Unknown dataset: {identifier!r}", 404)
        return dataset

    @app.get("/convert")
    def convert():
        """Ingest a remote table and answer with the endpoint serving it.

        A source that was ingested before is answered from the store, without
        downloading it again, unless caching is off, ``force`` asks for a fresh
        copy, or ``enrich=yes`` asks for a description the stored dataset does
        not carry. Re-ingesting replaces the stored dataset, and a failed
        attempt leaves the one already stored untouched and readable.
        """
        source = request.args.get("source")
        if not source:
            raise GateError("Query parameter 'source' is required", 400)

        validate_source(source)
        forced = force_requested(request.query_string)
        enrich = enrichment_requested(request.args)
        identifier = dataset_id(source)
        if not forced and cache_answers(identifier, enrich):
            return endpoint_response(identifier)
        return ingest(source, fetch(source), enrich)

    @app.post("/upload")
    def upload():
        """Ingest an uploaded table and answer with the endpoint serving it.

        Enrichment is asked for on ``/convert`` alone, so an upload is stored
        as the plain table it arrived as.
        """
        payload = read_upload(request)
        return ingest(upload_origin(payload), payload, enrich=False)

    @app.get("/datasets/<identifier>")
    def read_dataset(identifier: str):
        """Return the stored table, sorted, paginated and shaped as asked."""
        started = perf_counter()
        dataset = load(identifier)
        body = build_body(dataset, parse_query(request.args, dataset.columns))
        body["query_ms"] = round((perf_counter() - started) * 1000, 3)
        return jsonify(body)

    @app.get("/datasets/<identifier>/export")
    def export_dataset(identifier: str):
        """Serve the same rows as a CSV download, in source column order.

        The response shaping parameters have no CSV equivalent and are ignored
        here; the filters, the sort and the pagination all still apply.
        """
        dataset = load(identifier)
        page, _ = select_rows(dataset, parse_query(request.args, dataset.columns))
        return csv_response(identifier, dataset.columns, [row for _, row in page])

    @app.before_request
    def check_origin():
        """Turn away requests from sites the allowlist does not name."""
        check_referer(request.headers.get("Referer"), config.origin_allowlist)

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
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    return app
