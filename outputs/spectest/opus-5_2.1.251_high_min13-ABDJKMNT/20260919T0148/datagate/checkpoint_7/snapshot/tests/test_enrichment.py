"""Spec section: Optional Dataset Enrichment -- the `enrich=yes` ingestion metadata."""

import pytest
from builders import make_xls, make_xlsx
from helpers import post_upload

from datagate_core.store import dataset_id

CSV = "name,age,score\nada,36,1.5\ngrace,,2.0\nada,41,3.25\n"
LONGER = "name,age,score\nada,36,1.5\ngrace,37,2.0\nhopper,45,3.0\nlin,50,4.0\n"
SHEET = [("first", [["name", "age"], ["ada", 36], ["grace", 37]])]

METADATA_FIELDS = ("dataset_summary", "column_details")


def convert(client, source, **params):
    """Call `/convert` for `source` with the extra query parameters given."""
    return client.get("/convert", query_string={"source": source, **params})


def _explode(*args, **kwargs):
    """Stand in for the metadata builder to prove a failure cannot be stored."""
    raise RuntimeError("enrichment exploded")


def _has_metadata(body):
    """True when a dataset payload carries either enrichment field."""
    return any(field in body for field in METADATA_FIELDS)


@pytest.fixture()
def enriched(client, origin):
    """Serve a body, convert it with `enrich=yes` and hand back source and endpoint."""

    def ingest(body=CSV, path="/data.csv", **serve_kwargs):
        source = origin.serve(path, body, **serve_kwargs)
        response = convert(client, source, enrich="yes")
        assert response.status_code == 200, response.get_json()
        return source, response.get_json()["endpoint"]

    return ingest


@pytest.fixture()
def query(client):
    """Fetch a dataset endpoint and hand back its parsed payload."""

    def fetch(endpoint, params=None):
        response = client.get(endpoint, query_string=params or {})
        assert response.status_code == 200, response.get_json()
        return response.get_json()

    return fetch


# --------------------------------------------------------------------------
# Enrichment trigger
# --------------------------------------------------------------------------


# Phrase: "Only exact `enrich=yes` enables enrichment."
def test_exact_yes_enables_enrichment(client, origin, query):
    source = origin.serve("/data.csv", CSV)

    endpoint = convert(client, source, enrich="yes").get_json()["endpoint"]

    assert "dataset_summary" in query(endpoint)


# Phrase: "All other states keep enrichment off."
# Context: a value that is not exactly `yes`, whatever it means elsewhere.
@pytest.mark.parametrize("value", ["Yes", "YES", "yes ", " yes", "true", "1", "on", "no", ""])
def test_other_values_keep_enrichment_off(client, origin, query, value):
    source = origin.serve("/data.csv", CSV)

    endpoint = convert(client, source, enrich=value).get_json()["endpoint"]

    assert not _has_metadata(query(endpoint))


# Phrase: "All other states keep enrichment off."
# Context: the parameter present as a bare flag, carrying no value at all.
def test_bare_enrich_flag_keeps_enrichment_off(client, origin, query):
    source = origin.serve("/data.csv", CSV)

    response = client.get(f"/convert?source={source}&enrich")

    assert not _has_metadata(query(response.get_json()["endpoint"]))


# Phrase: "All other states keep enrichment off."
# Context: the parameter absent entirely.
def test_absent_enrich_keeps_enrichment_off(client, origin, query):
    source = origin.serve("/data.csv", CSV)

    endpoint = convert(client, source).get_json()["endpoint"]

    assert not _has_metadata(query(endpoint))


# Phrase: "Only exact `enrich=yes` enables enrichment."
# Context: a repeated parameter whose first value is exactly `yes` (AMBIGUITIES T74).
def test_repeated_enrich_reads_the_first_value(client, origin, query):
    source = origin.serve("/data.csv", CSV)

    response = client.get(f"/convert?source={source}&enrich=yes&enrich=no")

    assert "dataset_summary" in query(response.get_json()["endpoint"])


# Phrase: "Success response remains: {"ok": true, "endpoint": "/datasets/<id>"}"
def test_enriched_convert_answers_the_usual_envelope(client, origin):
    source = origin.serve("/data.csv", CSV)

    response = convert(client, source, enrich="yes")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "endpoint": f"/datasets/{dataset_id(source)}"}


# Phrase: "Success response remains ..."
# Context: enrichment does not change the id a source maps to.
def test_enrichment_does_not_change_the_dataset_id(client, origin):
    source = origin.serve("/data.csv", CSV)

    plain = convert(client, source).get_json()["endpoint"]
    enriched_endpoint = convert(client, source, enrich="yes").get_json()["endpoint"]

    assert plain == enriched_endpoint


# --------------------------------------------------------------------------
# Enriched query output
# --------------------------------------------------------------------------


# Phrase: "For enriched CSV datasets, add: `dataset_summary` with at least
# `filetype`, `row_count`, `column_count`"
def test_dataset_summary_carries_the_required_keys(enriched, query):
    _, endpoint = enriched()

    summary = query(endpoint)["dataset_summary"]

    assert set(summary) >= {"filetype", "row_count", "column_count"}


# Phrase: "... `filetype` ..."
# Context: a CSV source is labelled `csv` (AMBIGUITIES T75).
def test_csv_summary_reports_the_csv_filetype(enriched, query):
    _, endpoint = enriched()

    assert query(endpoint)["dataset_summary"]["filetype"] == "csv"


# Phrase: "... `row_count`, `column_count`"
# Context: rows are the data rows, the header is not one of them (AMBIGUITIES T76).
def test_summary_counts_data_rows_and_columns(enriched, query):
    _, endpoint = enriched()

    summary = query(endpoint)["dataset_summary"]

    assert (summary["row_count"], summary["column_count"]) == (3, 3)


# Phrase: "`column_details` keyed by column name"
def test_column_details_are_keyed_by_column_name(enriched, query):
    _, endpoint = enriched()

    assert set(query(endpoint)["column_details"]) == {"name", "age", "score"}


# Phrase: "... with at least `type`, `distinct_count`, `missing_count`"
def test_every_column_detail_carries_the_required_keys(enriched, query):
    _, endpoint = enriched()

    details = query(endpoint)["column_details"]

    assert all(set(entry) >= {"type", "distinct_count", "missing_count"} for entry in details.values())


# Phrase: "Type labels: `text`, `number`, `integer`, `float`."
# Context: a column of strings is `text`.
def test_text_column_is_labelled_text(enriched, query):
    _, endpoint = enriched()

    assert query(endpoint)["column_details"]["name"]["type"] == "text"


# Phrase: "Type labels: ... `integer` ..."
# Context: every present cell parsed as a whole number (AMBIGUITIES T77).
def test_whole_number_column_is_labelled_integer(enriched, query):
    _, endpoint = enriched()

    assert query(endpoint)["column_details"]["age"]["type"] == "integer"


# Phrase: "Type labels: ... `float` ..."
# Context: every present cell parsed as a decimal (AMBIGUITIES T77).
def test_decimal_column_is_labelled_float(enriched, query):
    _, endpoint = enriched()

    assert query(endpoint)["column_details"]["score"]["type"] == "float"


# Phrase: "Type labels: ... `number` ..."
# Context: a numeric column mixing whole numbers and decimals (AMBIGUITIES T77).
def test_mixed_numeric_column_is_labelled_number(enriched, query):
    _, endpoint = enriched("label,value\na,1\nb,2.5\n")

    assert query(endpoint)["column_details"]["value"]["type"] == "number"


# Phrase: "Type labels: `text`, ..."
# Context: a column mixing numbers and words is not numeric (AMBIGUITIES T77).
def test_column_with_any_word_is_labelled_text(enriched, query):
    _, endpoint = enriched("label,value\na,1\nb,none\n")

    assert query(endpoint)["column_details"]["value"]["type"] == "text"


# Phrase: "Type labels: `text`, ..."
# Context: a column with nothing present to type (AMBIGUITIES T77).
def test_entirely_missing_column_is_labelled_text(enriched, query):
    _, endpoint = enriched("label,value\na,\nb,\n")

    assert query(endpoint)["column_details"]["value"]["type"] == "text"


# Phrase: "... `missing_count`"
def test_missing_count_counts_empty_cells(enriched, query):
    _, endpoint = enriched()

    details = query(endpoint)["column_details"]

    assert [details[name]["missing_count"] for name in ("name", "age", "score")] == [0, 1, 0]


# Phrase: "... `distinct_count` ..."
# Context: repeated values count once (AMBIGUITIES T78).
def test_distinct_count_counts_each_value_once(enriched, query):
    _, endpoint = enriched()

    assert query(endpoint)["column_details"]["name"]["distinct_count"] == 2


# Phrase: "... `distinct_count`, `missing_count`"
# Context: a blank cell is counted as missing, not as a distinct value
# (AMBIGUITIES T78).
def test_distinct_count_ignores_missing_cells(enriched, query):
    _, endpoint = enriched()

    assert query(endpoint)["column_details"]["age"]["distinct_count"] == 2


# Phrase: "For enriched spreadsheet datasets, add only `dataset_summary` with
# `filetype: "excel"`."
@pytest.mark.parametrize("build", [make_xlsx, make_xls])
def test_spreadsheet_summary_reports_the_excel_filetype(enriched, query, build):
    _, endpoint = enriched(build(SHEET), content_type="application/octet-stream")

    assert query(endpoint)["dataset_summary"]["filetype"] == "excel"


# Phrase: "... add only `dataset_summary` ..."
# Context: a workbook gets no column details (AMBIGUITIES T79).
@pytest.mark.parametrize("build", [make_xlsx, make_xls])
def test_spreadsheet_gets_no_column_details(enriched, query, build):
    _, endpoint = enriched(build(SHEET), content_type="application/octet-stream")

    assert "column_details" not in query(endpoint)


# Phrase: "... add only `dataset_summary` with `filetype: "excel"`."
# Context: the summary keeps the shape declared for it (AMBIGUITIES T79).
def test_spreadsheet_summary_still_counts_rows_and_columns(enriched, query):
    _, endpoint = enriched(make_xlsx(SHEET), content_type="application/octet-stream")

    summary = query(endpoint)["dataset_summary"]

    assert (summary["row_count"], summary["column_count"]) == (2, 2)


# Phrase: "Non-enriched responses omit both metadata fields (no `null`/empty objects)."
def test_non_enriched_response_omits_both_fields(client, origin, query):
    source = origin.serve("/data.csv", CSV)
    endpoint = convert(client, source).get_json()["endpoint"]

    body = query(endpoint)

    assert "dataset_summary" not in body and "column_details" not in body


# Phrase: "Non-enriched responses omit both metadata fields ..."
# Context: an uploaded dataset is never enriched either.
def test_upload_response_omits_both_fields(client, query):
    endpoint = post_upload(client, CSV).get_json()["endpoint"]

    assert not _has_metadata(query(endpoint))


# Phrase: "`rows`, `columns`, `ok`, `query_ms`, and `total` do not change."
def test_enrichment_leaves_the_rest_of_the_envelope_alone(client, origin, query):
    source = origin.serve("/data.csv", CSV)
    plain = query(convert(client, source).get_json()["endpoint"])
    endpoint = convert(client, source, enrich="yes").get_json()["endpoint"]

    body = query(endpoint)

    assert {key: body[key] for key in ("ok", "columns", "rows", "total")} == {
        key: plain[key] for key in ("ok", "columns", "rows", "total")
    }


# Phrase: "`rows`, `columns`, `ok`, `query_ms`, and `total` do not change."
# Context: `query_ms` is still reported on an enriched dataset.
def test_enriched_response_still_reports_query_ms(enriched, query):
    _, endpoint = enriched()

    assert isinstance(query(endpoint)["query_ms"], float)


# Phrase: "`rows`, `columns`, `ok`, `query_ms`, and `total` do not change."
# Context: enrichment adds exactly the two metadata keys, nothing else.
def test_enriched_response_adds_only_the_metadata_keys(client, origin, query):
    source = origin.serve("/data.csv", CSV)
    plain = set(query(convert(client, source).get_json()["endpoint"]))
    endpoint = convert(client, source, enrich="yes").get_json()["endpoint"]

    assert set(query(endpoint)) - plain == set(METADATA_FIELDS)


# Phrase: "the metadata is ingestion enrichment" / "`rows` ... do not change."
# Context: metadata describes the stored dataset, not the requested page
# (AMBIGUITIES T80).
def test_metadata_ignores_pagination_and_filters(enriched, query):
    _, endpoint = enriched()

    body = query(endpoint, {"_size": "1", "name__exact": "ada"})

    assert body["dataset_summary"]["row_count"] == 3
    assert body["column_details"]["name"]["distinct_count"] == 2


# Phrase: "... do not change."
# Context: metadata survives the object shape as its own top-level field.
def test_metadata_is_unaffected_by_the_row_shape(enriched, query):
    _, endpoint = enriched()

    body = query(endpoint, {"_shape": "objects", "_total": "hide"})

    assert body["dataset_summary"]["row_count"] == 3


# --------------------------------------------------------------------------
# Cache and enrichment
# --------------------------------------------------------------------------


# Phrase: "`enrich=yes` on a cached non-enriched dataset forces re-ingestion
# and upgrades stored state."
def test_enrich_on_a_non_enriched_hit_re_ingests(client, origin):
    source = origin.serve("/data.csv", CSV)
    convert(client, source)

    convert(client, source, enrich="yes")

    assert origin.downloads("/data.csv") == 2


# Phrase: "... and upgrades stored state."
def test_enrich_on_a_non_enriched_hit_upgrades_the_dataset(client, origin, query):
    source = origin.serve("/data.csv", CSV)
    endpoint = convert(client, source).get_json()["endpoint"]

    convert(client, source, enrich="yes")

    assert "dataset_summary" in query(endpoint)


# Phrase: "... upgrades stored state."
# Context: the upgrade is stored, so a later plain request still sees it.
def test_the_upgrade_outlives_the_request_that_made_it(client, origin, query):
    source = origin.serve("/data.csv", CSV)
    convert(client, source)
    endpoint = convert(client, source, enrich="yes").get_json()["endpoint"]

    convert(client, source)

    assert "dataset_summary" in query(endpoint)


# Phrase: "`enrich=yes` on a cached enriched dataset may use cache."
def test_enrich_on_an_enriched_hit_does_not_re_download(client, origin, enriched):
    source, _ = enriched()

    convert(client, source, enrich="yes")

    assert origin.downloads("/data.csv") == 1


# Phrase: "`enrich=yes` on a cached enriched dataset may use cache."
# Context: the cached answer is the usual envelope.
def test_enriched_cache_hit_answers_the_usual_envelope(client, enriched):
    source, endpoint = enriched()

    response = convert(client, source, enrich="yes")

    assert response.get_json() == {"ok": True, "endpoint": endpoint}


# Phrase: "Requests without re-ingestion do not change stored enrichment state."
def test_a_plain_cache_hit_does_not_downgrade_an_enriched_dataset(client, origin, enriched, query):
    source, endpoint = enriched()

    convert(client, source)

    assert origin.downloads("/data.csv") == 1
    assert "dataset_summary" in query(endpoint)


# Phrase: "Requests without re-ingestion do not change stored enrichment state."
# Context: a non-enriched dataset answered from the cache stays non-enriched.
def test_a_plain_cache_hit_does_not_enrich_a_stored_dataset(client, origin, query):
    source = origin.serve("/data.csv", CSV)
    endpoint = convert(client, source).get_json()["endpoint"]

    convert(client, source, enrich="maybe")

    assert not _has_metadata(query(endpoint))


# Phrase: "Re-ingestion recomputes metadata from current source bytes."
def test_upgrade_reads_the_current_source_bytes(client, origin, query):
    source = origin.serve("/data.csv", CSV)
    endpoint = convert(client, source).get_json()["endpoint"]
    origin.serve("/data.csv", LONGER)

    convert(client, source, enrich="yes")

    assert query(endpoint)["dataset_summary"]["row_count"] == 4


# Phrase: "Re-ingestion recomputes metadata from current source bytes."
# Context: `force` re-ingests an already enriched dataset.
def test_forced_re_ingestion_recomputes_the_metadata(client, origin, enriched, query):
    source, endpoint = enriched()
    origin.serve("/data.csv", LONGER)

    convert(client, source, enrich="yes", force="")

    assert query(endpoint)["dataset_summary"]["row_count"] == 4


# Phrase: "Re-ingestion recomputes metadata from current source bytes."
# Context: with caching off every request re-ingests (AMBIGUITIES T81).
def test_re_ingestion_without_enrich_drops_the_metadata(client, origin, enriched, query):
    source, endpoint = enriched()

    convert(client, source, force="")

    assert not _has_metadata(query(endpoint))


# Phrase: "`enrich=yes` on a cached non-enriched dataset forces re-ingestion ..."
# Context: with `CACHE_ENABLED=false` there is no cached state to consult.
def test_enrichment_works_with_caching_disabled(configured_client, origin, query):
    client = configured_client("false")
    source = origin.serve("/data.csv", CSV)

    endpoint = convert(client, source, enrich="yes").get_json()["endpoint"]

    assert "dataset_summary" in query(endpoint)


# Phrase: "Requests without re-ingestion do not change stored enrichment state."
# Context: with caching off, every request re-ingests and so does set the state
# (AMBIGUITIES T81).
def test_caching_disabled_lets_a_plain_request_drop_the_metadata(configured_client, origin):
    client = configured_client("false")
    source = origin.serve("/data.csv", CSV)
    endpoint = convert(client, source, enrich="yes").get_json()["endpoint"]

    convert(client, source)

    assert "dataset_summary" not in client.get(endpoint).get_json()


# Phrase: "`enrich` applies only on `/convert`."
# Context: an upload carrying the parameter stores a plain dataset.
def test_enrich_is_ignored_on_upload(client, query):
    response = post_upload(client, CSV, query_string={"enrich": "yes"})

    assert not _has_metadata(query(response.get_json()["endpoint"]))


# Phrase: "`enrich` applies only on `/convert`."
# Context: the parameter on a dataset query is neither a filter nor an upgrade
# (AMBIGUITIES T82).
def test_enrich_is_ignored_on_a_dataset_query(client, origin, query):
    source = origin.serve("/data.csv", CSV)
    endpoint = convert(client, source).get_json()["endpoint"]

    assert not _has_metadata(query(endpoint, {"enrich": "yes"}))


# Phrase: "`enrich` applies only on `/convert`."
# Context: it does not enrich an export either.
def test_enrich_does_not_change_an_export(client, origin, enriched):
    source, endpoint = enriched()
    plain = origin.serve("/plain.csv", CSV)
    other = convert(client, plain).get_json()["endpoint"]

    assert client.get(endpoint + "/export").data == client.get(other + "/export").data


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------


# Phrase: "Enrichment failures return standard JSON errors ..."
# Context: an unreachable source keeps the status it has without enrichment.
def test_a_failed_enriched_convert_answers_the_error_envelope(client, origin):
    source = origin.serve("/missing.csv", "boom", status=500)

    response = convert(client, source, enrich="yes")

    assert response.status_code == 404
    assert set(response.get_json()) == {"ok", "error"}
    assert response.get_json()["ok"] is False


# Phrase: "Enrichment failures return standard JSON errors ..."
# Context: content that cannot be parsed is rejected before it can be enriched.
def test_non_tabular_enriched_convert_is_rejected(client, origin):
    source = origin.serve("/page.html", "<html><body>hi</body></html>")

    response = convert(client, source, enrich="yes")

    assert response.status_code == 400 and response.get_json()["ok"] is False


# Phrase: "Enrichment failures return standard JSON errors ..."
# Context: a failure while computing the metadata itself (AMBIGUITIES T83).
def test_metadata_failure_answers_a_json_error(client, origin, monkeypatch):
    source = origin.serve("/data.csv", CSV)
    monkeypatch.setattr("datagate_core.conversion.build_metadata", _explode)

    response = convert(client, source, enrich="yes")

    assert response.status_code >= 400
    assert response.get_json()["ok"] is False


# Phrase: "... and must not downgrade to non-enriched storage."
def test_metadata_failure_leaves_the_enriched_dataset_alone(client, origin, enriched, query, monkeypatch):
    source, endpoint = enriched()
    origin.serve("/data.csv", LONGER)
    monkeypatch.setattr("datagate_core.conversion.build_metadata", _explode)

    convert(client, source, enrich="yes", force="")

    assert query(endpoint)["dataset_summary"]["row_count"] == 3


# Phrase: "... must not downgrade to non-enriched storage."
# Context: a first ingestion that fails to enrich stores nothing at all.
def test_metadata_failure_stores_no_plain_dataset(client, origin, monkeypatch):
    source = origin.serve("/data.csv", CSV)
    monkeypatch.setattr("datagate_core.conversion.build_metadata", _explode)

    convert(client, source, enrich="yes")

    assert client.get(f"/datasets/{dataset_id(source)}").status_code == 404
