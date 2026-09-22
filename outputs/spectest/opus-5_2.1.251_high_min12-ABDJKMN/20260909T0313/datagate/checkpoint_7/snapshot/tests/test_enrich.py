"""Spec section: Optional Dataset Enrichment.

    `/convert` supports optional ingestion enrichment with `enrich=yes`.

Every test below is labelled with the spec phrase it exercises.
"""

from urllib.parse import quote

import pytest


SIMPLE = "name,age\nalice,30\nbob,41\n"

# One column per type label plus a column with blanks, so a single fixture can
# carry the whole `column_details` contract.
MIXED = (
    "name,age,ratio,mixed,note\n"
    "alice,30,1.5,1,x\n"
    "bob,41,2.25,2.5,\n"
    "cleo,30,0.5,3,x\n"
)


def _hits(origin, path):
    return origin.hits.get(path, 0)


def _payload(client, endpoint, query=None):
    response = client.get(endpoint, query_string=query or {})
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def _convert(client, origin, path, params=None):
    query = {"source": origin.url(path)}
    query.update(params or {})
    return client.get("/convert", query_string=query)


@pytest.fixture
def enriched(convert, client):
    """Ingest a CSV with `enrich=yes` and return the /datasets/<id> payload."""

    def _enriched(path, body, params=None, query=None, **kwargs):
        params = dict(params or {})
        params.setdefault("enrich", "yes")
        response = convert(path, body, params=params, **kwargs)
        assert response.status_code == 200, response.get_data(as_text=True)
        return _payload(client, response.get_json()["endpoint"], query)

    return _enriched


# ---------------------------------------------------------------------------
# Enrichment trigger
# ---------------------------------------------------------------------------


# Phrase: "`/convert` supports optional ingestion enrichment with `enrich=yes`."
def test_convert_accepts_enrich_yes(convert):
    response = convert("/trigger.csv", SIMPLE, params={"enrich": "yes"})
    assert response.status_code == 200


# Phrase: "Only exact `enrich=yes` enables enrichment."
def test_enrich_yes_enables_enrichment(enriched):
    payload = enriched("/on.csv", SIMPLE)
    assert "dataset_summary" in payload
    assert "column_details" in payload


# Phrase: "Only exact `enrich=yes` enables enrichment."
# Context: "exact" -- the value must match `yes` character for character.
@pytest.mark.parametrize(
    "value",
    ["YES", "Yes", "yEs", " yes", "yes ", "yes\t", "y", "yep", "1", "true",
     "on", "no", "false", "0", "off", ""],
)
def test_only_exact_yes_enables_enrichment(convert, client, value):
    response = convert("/exact-{}.csv".format(quote(value, safe="")), SIMPLE,
                       params={"enrich": value})
    assert response.status_code == 200
    payload = _payload(client, response.get_json()["endpoint"])
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


# Phrase: "All other states keep enrichment off."
# Context: the parameter absent altogether.
def test_absent_enrich_keeps_enrichment_off(dataset):
    payload = dataset("/absent.csv", SIMPLE).get_json()
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


# Phrase: "All other states keep enrichment off."
# Context: a valueless `enrich` (present in the query string, no `=value`).
def test_valueless_enrich_keeps_enrichment_off(client, origin):
    path = "/valueless.csv"
    origin.add(path, SIMPLE)
    response = client.get(
        "/convert?source={}&enrich".format(quote(origin.url(path), safe=""))
    )
    assert response.status_code == 200
    payload = _payload(client, response.get_json()["endpoint"])
    assert "dataset_summary" not in payload


# Phrase: "All other states keep enrichment off."
# Context: an unrecognized value is not an error, just enrichment off.
def test_unrecognized_enrich_value_is_not_an_error(convert):
    response = convert("/weird.csv", SIMPLE, params={"enrich": "maybe"})
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


# Phrase: 'Success response remains: {"ok": true, "endpoint": "/datasets/<id>"}'
def test_success_response_shape_is_unchanged_by_enrich(convert):
    response = convert("/envelope.csv", SIMPLE, params={"enrich": "yes"})
    payload = response.get_json()
    assert payload["ok"] is True
    assert set(payload) == {"ok", "endpoint"}
    assert payload["endpoint"].startswith("/datasets/")


# Phrase: 'Success response remains: {"ok": true, "endpoint": "/datasets/<id>"}'
# Context: enrichment does not change which id a source maps to.
def test_enrich_does_not_change_the_dataset_id(convert):
    plain = convert("/sameid.csv", SIMPLE).get_json()["endpoint"]
    enriched_endpoint = convert(
        "/sameid.csv", SIMPLE, params={"enrich": "yes"}
    ).get_json()["endpoint"]
    assert plain == enriched_endpoint


# ---------------------------------------------------------------------------
# Enriched query output -- CSV
# ---------------------------------------------------------------------------


# Phrase: "For enriched CSV datasets, add: `dataset_summary` with at least
# `filetype`, `row_count`, `column_count`"
def test_dataset_summary_has_the_required_keys(enriched):
    summary = enriched("/summary.csv", MIXED)["dataset_summary"]
    assert {"filetype", "row_count", "column_count"} <= set(summary)


# Phrase: "`dataset_summary` with at least `filetype` ..."
# Context: the CSV counterpart of the spreadsheet's `filetype: "excel"` (T87).
def test_csv_summary_filetype(enriched):
    assert enriched("/filetype.csv", MIXED)["dataset_summary"]["filetype"] == "csv"


# Phrase: "`dataset_summary` with at least ... `row_count`, `column_count`"
def test_summary_counts_describe_the_dataset(enriched):
    summary = enriched("/counts.csv", MIXED)["dataset_summary"]
    assert summary["row_count"] == 3
    assert summary["column_count"] == 5


# Phrase: "`dataset_summary` with at least ... `row_count`, `column_count`"
# Context: metadata is ingestion-time, so query controls cannot move it (T94).
def test_summary_counts_ignore_pagination_and_filters(enriched):
    payload = enriched("/static-counts.csv", MIXED,
                       query={"_size": "1", "age__exact": "30"})
    assert payload["dataset_summary"]["row_count"] == 3
    assert payload["dataset_summary"]["column_count"] == 5
    assert payload["total"] == 2
    assert len(payload["rows"]) == 1


# Phrase: "`column_details` keyed by column name"
def test_column_details_is_keyed_by_column_name(enriched):
    payload = enriched("/keys.csv", MIXED)
    assert set(payload["column_details"]) == set(payload["columns"])


# Phrase: "`column_details` keyed by column name with at least `type`,
# `distinct_count`, `missing_count`"
def test_every_column_detail_has_the_required_keys(enriched):
    details = enriched("/detail-keys.csv", MIXED)["column_details"]
    for entry in details.values():
        assert {"type", "distinct_count", "missing_count"} <= set(entry)


# Phrase: "Type labels: `text`, `number`, `integer`, `float`."
# Context: a column of whole numbers (T84).
def test_integer_column_type(enriched):
    details = enriched("/types.csv", MIXED)["column_details"]
    assert details["age"]["type"] == "integer"


# Phrase: "Type labels: `text`, `number`, `integer`, `float`."
# Context: a column of fractional numbers (T84).
def test_float_column_type(enriched):
    details = enriched("/types-float.csv", MIXED)["column_details"]
    assert details["ratio"]["type"] == "float"


# Phrase: "Type labels: `text`, `number`, `integer`, `float`."
# Context: an all-numeric column mixing whole and fractional values (T84).
def test_mixed_numeric_column_type(enriched):
    details = enriched("/types-number.csv", MIXED)["column_details"]
    assert details["mixed"]["type"] == "number"


# Phrase: "Type labels: `text`, `number`, `integer`, `float`."
# Context: non-numeric values (T84).
def test_text_column_type(enriched):
    details = enriched("/types-text.csv", MIXED)["column_details"]
    assert details["name"]["type"] == "text"


# Phrase: "Type labels: `text`, `number`, `integer`, `float`."
# Context: only these four labels are ever emitted.
def test_type_labels_come_from_the_documented_set(enriched):
    details = enriched("/label-set.csv", MIXED)["column_details"]
    for entry in details.values():
        assert entry["type"] in ("text", "number", "integer", "float")


# Phrase: "Type labels: ..." Context: a column mixing numbers and words is
# not numeric.
def test_numbers_mixed_with_words_are_text(enriched):
    body = "v,w\n1,a\n2,b\nthree,c\n"
    details = enriched("/mixed-text.csv", body)["column_details"]
    assert details["v"]["type"] == "text"


# Phrase: "Type labels: ..." Context: blanks do not defeat numeric typing
# because `missing_count` reports them separately (T93).
def test_blanks_do_not_prevent_numeric_typing(enriched):
    body = "v,w\n1,a\n,b\n3,c\n"
    details = enriched("/blank-numeric.csv", body)["column_details"]
    assert details["v"]["type"] == "integer"
    assert details["v"]["missing_count"] == 1


# Phrase: "Type labels: ..." Context: a column with no values at all (T84).
def test_all_missing_column_is_text(enriched):
    body = "v,w\n1,\n2,\n"
    details = enriched("/all-missing.csv", body)["column_details"]
    assert details["w"]["type"] == "text"


# Phrase: "`column_details` ... `distinct_count`"
def test_distinct_count_counts_unique_values(enriched):
    details = enriched("/distinct.csv", MIXED)["column_details"]
    assert details["age"]["distinct_count"] == 2  # 30, 41, 30
    assert details["name"]["distinct_count"] == 3


# Phrase: "`column_details` ... `distinct_count`, `missing_count`"
# Context: the two fields partition the column, so blanks are not distinct
# values (T86).
def test_distinct_count_excludes_missing_values(enriched):
    body = "v,w\na,1\n,2\nb,3\n,4\na,5\n"
    details = enriched("/distinct-missing.csv", body)["column_details"]
    assert details["v"]["distinct_count"] == 2
    assert details["v"]["missing_count"] == 2


# Phrase: "`column_details` ... `missing_count`"
def test_missing_count_counts_empty_cells(enriched):
    details = enriched("/missing.csv", MIXED)["column_details"]
    assert details["note"]["missing_count"] == 1
    assert details["name"]["missing_count"] == 0


# Phrase: "`column_details` ... `missing_count`"
# Context: whitespace-only cells count as missing (T85).
def test_whitespace_only_cells_are_missing(enriched):
    body = 'v,w\na,1\n"   ",2\n'
    details = enriched("/whitespace.csv", body)["column_details"]
    assert details["v"]["missing_count"] == 1
    assert details["v"]["distinct_count"] == 1


# Phrase: "`column_details` ... `missing_count`"
# Context: a row shorter than the header is padded, and the padding is missing.
def test_short_rows_pad_into_missing_cells(enriched):
    body = "a,b\n1,2\n3\n"
    details = enriched("/short-row.csv", body)["column_details"]
    assert details["b"]["missing_count"] == 1


# Phrase: "`column_details` keyed by column name"
# Context: duplicate headers collapse onto one key (T92).
def test_duplicate_column_names_collapse_to_one_key(enriched):
    payload = enriched("/dupe.csv", "v,v\n1,x\n2,y\n")
    assert payload["columns"] == ["v", "v"]
    assert list(payload["column_details"]) == ["v"]
    assert payload["column_details"]["v"]["type"] == "text"


# ---------------------------------------------------------------------------
# Enriched query output -- spreadsheets
# ---------------------------------------------------------------------------


# Phrase: "For enriched spreadsheet datasets, add only `dataset_summary` with
# `filetype: "excel"`."
def test_xlsx_summary_filetype_is_excel(enriched, xlsx):
    book = xlsx([("Sheet1", [["name", "age"], ["alice", 30], ["bob", 41]])])
    payload = enriched("/book.xlsx", book,
                       content_type="application/vnd.openxmlformats-"
                                    "officedocument.spreadsheetml.sheet")
    assert payload["dataset_summary"]["filetype"] == "excel"


# Phrase: "For enriched spreadsheet datasets, add only `dataset_summary` ..."
def test_xlsx_has_no_column_details(enriched, xlsx):
    book = xlsx([("Sheet1", [["name", "age"], ["alice", 30], ["bob", 41]])])
    payload = enriched("/no-details.xlsx", book)
    assert "dataset_summary" in payload
    assert "column_details" not in payload


# Phrase: "For enriched spreadsheet datasets, add only `dataset_summary` with
# `filetype: "excel"`." Context: legacy .xls is the same dataset class.
def test_xls_summary_filetype_is_excel(enriched, xls):
    book = xls([("Sheet1", [["name", "age"], ["alice", 30], ["bob", 41]])])
    payload = enriched("/legacy.xls", book, content_type="application/vnd.ms-excel")
    assert payload["dataset_summary"]["filetype"] == "excel"
    assert "column_details" not in payload


# Phrase: "`dataset_summary` with at least `filetype`, `row_count`,
# `column_count`" -- the summary keeps its shape for spreadsheets too (T88).
def test_spreadsheet_summary_keeps_the_documented_keys(enriched, xlsx):
    book = xlsx([("Sheet1", [["name", "age"], ["alice", 30], ["bob", 41]])])
    summary = enriched("/shape.xlsx", book)["dataset_summary"]
    assert {"filetype", "row_count", "column_count"} <= set(summary)
    assert summary["row_count"] == 2
    assert summary["column_count"] == 2


# Phrase: "For enriched spreadsheet datasets ..."
# Context: a non-enriched spreadsheet gets no summary either.
def test_non_enriched_spreadsheet_has_no_summary(convert, client, xlsx):
    book = xlsx([("Sheet1", [["name", "age"], ["alice", 30]])])
    response = convert("/plain.xlsx", book)
    payload = _payload(client, response.get_json()["endpoint"])
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


# ---------------------------------------------------------------------------
# Non-enriched responses and untouched fields
# ---------------------------------------------------------------------------


# Phrase: "Non-enriched responses omit both metadata fields (no `null`/empty
# objects)."
def test_non_enriched_response_omits_both_fields(dataset):
    payload = dataset("/omit.csv", MIXED).get_json()
    assert "dataset_summary" not in payload
    assert "column_details" not in payload
    assert set(payload) == {"ok", "columns", "rows", "query_ms", "total"}


# Phrase: "Non-enriched responses omit both metadata fields (no `null`/empty
# objects)." Context: an uploaded dataset is never enriched (T95).
def test_uploaded_dataset_omits_metadata(uploaded):
    payload = uploaded(MIXED).get_json()
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


# Phrase: "`rows`, `columns`, `ok`, `query_ms`, and `total` do not change."
def test_shared_fields_are_identical_with_and_without_enrichment(
    convert, client, origin
):
    origin.add("/plainx.csv", MIXED)
    origin.add("/enrichx.csv", MIXED)
    plain = _payload(
        client, _convert(client, origin, "/plainx.csv").get_json()["endpoint"]
    )
    rich = _payload(
        client,
        _convert(client, origin, "/enrichx.csv",
                 {"enrich": "yes"}).get_json()["endpoint"],
    )
    assert rich["ok"] == plain["ok"]
    assert rich["columns"] == plain["columns"]
    assert rich["rows"] == plain["rows"]
    assert rich["total"] == plain["total"]
    assert isinstance(rich["query_ms"], float)


# Phrase: "`rows`, `columns`, `ok`, `query_ms`, and `total` do not change."
# Context: the enriched payload is the plain one plus exactly two fields.
def test_enriched_payload_adds_exactly_two_fields(enriched):
    payload = enriched("/exact-fields.csv", MIXED)
    assert set(payload) == {
        "ok", "columns", "rows", "query_ms", "total",
        "dataset_summary", "column_details",
    }


# Phrase: "`rows`, `columns`, `ok`, `query_ms`, and `total` do not change."
# Context: `_total=no` still suppresses `total` on an enriched dataset.
def test_enrichment_does_not_reinstate_a_suppressed_total(enriched):
    payload = enriched("/no-total.csv", MIXED, query={"_total": "hide"})
    assert "total" not in payload
    assert "dataset_summary" in payload


# Phrase: "`rows`, `columns` ... do not change."
# Context: `_shape=objects` rows are unaffected by enrichment.
def test_object_shape_is_unaffected_by_enrichment(enriched):
    payload = enriched("/objects.csv", SIMPLE, query={"_shape": "objects"})
    assert payload["rows"][0]["name"] == "alice"
    assert "dataset_summary" in payload


# Phrase: "`rows`, `columns` ... do not change."
# Context: /export stays plain CSV, with no metadata anywhere.
def test_export_of_an_enriched_dataset_is_unchanged(convert, client):
    endpoint = convert("/exp.csv", SIMPLE,
                       params={"enrich": "yes"}).get_json()["endpoint"]
    response = client.get(endpoint + "/export")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "name,age\r\nalice,30\r\nbob,41\r\n"


# ---------------------------------------------------------------------------
# Cache and enrichment
# ---------------------------------------------------------------------------


# Phrase: "`enrich=yes` on a cached non-enriched dataset forces re-ingestion
# and upgrades stored state." Context: re-ingestion == the source is refetched.
def test_enrich_on_cached_plain_dataset_refetches(client, origin):
    path = "/upgrade-fetch.csv"
    origin.add(path, MIXED)
    _convert(client, origin, path)
    before = _hits(origin, path)

    response = _convert(client, origin, path, {"enrich": "yes"})
    assert response.status_code == 200
    assert _hits(origin, path) - before == 1


# Phrase: "`enrich=yes` on a cached non-enriched dataset forces re-ingestion
# and upgrades stored state."
def test_enrich_on_cached_plain_dataset_upgrades_stored_state(client, origin):
    path = "/upgrade-state.csv"
    origin.add(path, MIXED)
    endpoint = _convert(client, origin, path).get_json()["endpoint"]
    assert "dataset_summary" not in _payload(client, endpoint)

    _convert(client, origin, path, {"enrich": "yes"})
    payload = _payload(client, endpoint)
    assert payload["dataset_summary"]["filetype"] == "csv"
    assert set(payload["column_details"]) == set(payload["columns"])


# Phrase: "`enrich=yes` on a cached enriched dataset may use cache."
def test_enrich_on_cached_enriched_dataset_does_not_refetch(client, origin):
    path = "/cached-enriched.csv"
    origin.add(path, MIXED)
    _convert(client, origin, path, {"enrich": "yes"})
    before = _hits(origin, path)

    response = _convert(client, origin, path, {"enrich": "yes"})
    assert response.status_code == 200
    assert _hits(origin, path) - before == 0


# Phrase: "`enrich=yes` on a cached enriched dataset may use cache."
# Context: the cached response is the same envelope as the fresh one.
def test_cached_enriched_convert_returns_the_same_endpoint(client, origin):
    path = "/cached-endpoint.csv"
    origin.add(path, MIXED)
    first = _convert(client, origin, path, {"enrich": "yes"}).get_json()
    second = _convert(client, origin, path, {"enrich": "yes"}).get_json()
    assert first == second


# Phrase: "Requests without re-ingestion do not change stored enrichment
# state." Context: a plain cache hit leaves an enriched dataset enriched.
def test_plain_cache_hit_keeps_a_dataset_enriched(client, origin):
    path = "/keep-enriched.csv"
    origin.add(path, MIXED)
    endpoint = _convert(client, origin, path, {"enrich": "yes"}).get_json()["endpoint"]
    before = _hits(origin, path)

    _convert(client, origin, path)
    assert _hits(origin, path) - before == 0
    assert "dataset_summary" in _payload(client, endpoint)


# Phrase: "Requests without re-ingestion do not change stored enrichment
# state." Context: a plain cache hit leaves a plain dataset plain.
def test_plain_cache_hit_keeps_a_dataset_non_enriched(client, origin):
    path = "/keep-plain.csv"
    origin.add(path, MIXED)
    endpoint = _convert(client, origin, path).get_json()["endpoint"]
    _convert(client, origin, path)
    assert "dataset_summary" not in _payload(client, endpoint)


# Phrase: "Requests without re-ingestion do not change stored enrichment
# state." Context: querying the dataset does not flip its state either.
def test_querying_does_not_change_stored_enrichment_state(client, origin):
    path = "/query-state.csv"
    origin.add(path, MIXED)
    endpoint = _convert(client, origin, path, {"enrich": "yes"}).get_json()["endpoint"]
    _payload(client, endpoint)
    _payload(client, endpoint, {"enrich": "yes"})
    assert "dataset_summary" in _payload(client, endpoint)


# Phrase: "Re-ingestion recomputes metadata from current source bytes."
def test_reingestion_recomputes_metadata(client, origin):
    path = "/recompute.csv"
    origin.add(path, "a,b\n1,2\n")
    endpoint = _convert(client, origin, path, {"enrich": "yes"}).get_json()["endpoint"]
    assert _payload(client, endpoint)["dataset_summary"]["row_count"] == 1

    origin.add(path, "a,b,c\n1,2,3\n4,5,6\n")
    _convert(client, origin, path, {"enrich": "yes", "force": "1"})
    summary = _payload(client, endpoint)["dataset_summary"]
    assert summary["row_count"] == 2
    assert summary["column_count"] == 3


# Phrase: "Re-ingestion recomputes metadata from current source bytes."
# Context: an upgrade reads the bytes as they are now, not as they were.
def test_upgrade_uses_the_current_source_bytes(client, origin):
    path = "/upgrade-bytes.csv"
    origin.add(path, "a,b\n1,x\n")
    endpoint = _convert(client, origin, path).get_json()["endpoint"]

    origin.add(path, "a,b\n1,x\n2,y\n3,z\n")
    _convert(client, origin, path, {"enrich": "yes"})
    payload = _payload(client, endpoint)
    assert payload["dataset_summary"]["row_count"] == 3
    assert payload["column_details"]["a"]["distinct_count"] == 3


# Phrase: "Re-ingestion recomputes metadata from current source bytes."
# Context: with caching off every request re-ingests (T90).
def test_caching_disabled_reingests_each_request(client, origin, configure):
    configure(CACHE_ENABLED="false")
    path = "/nocache.csv"
    origin.add(path, MIXED)
    endpoint = _convert(client, origin, path, {"enrich": "yes"}).get_json()["endpoint"]
    assert "dataset_summary" in _payload(client, endpoint)

    _convert(client, origin, path)
    assert "dataset_summary" not in _payload(client, endpoint)


# Phrase: "Re-ingestion recomputes metadata from current source bytes."
# Context: a forced plain re-ingest stores plain state (T90).
def test_forced_plain_reingest_stores_non_enriched_state(client, origin):
    path = "/force-plain.csv"
    origin.add(path, MIXED)
    endpoint = _convert(client, origin, path, {"enrich": "yes"}).get_json()["endpoint"]
    _convert(client, origin, path, {"force": "1"})
    assert "dataset_summary" not in _payload(client, endpoint)


# Phrase: "`enrich` applies only on `/convert`."
# Context: `/upload` ignores it (T95).
def test_upload_ignores_enrich(client, upload):
    response = upload(MIXED, extra={"enrich": "yes"})
    assert response.status_code == 200
    payload = _payload(client, response.get_json()["endpoint"])
    assert "dataset_summary" not in payload


# Phrase: "`enrich` applies only on `/convert`."
# Context: `/datasets/<id>` ignores it (T95).
def test_dataset_query_ignores_enrich(convert, client):
    endpoint = convert("/query-enrich.csv", MIXED).get_json()["endpoint"]
    payload = _payload(client, endpoint, {"enrich": "yes"})
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


# Phrase: "`enrich` applies only on `/convert`."
# Context: `enrich` is not read as a column filter or rejected as unknown.
def test_enrich_on_dataset_query_is_not_an_error(convert, client):
    endpoint = convert("/enrich-noop.csv", SIMPLE).get_json()["endpoint"]
    assert client.get(endpoint, query_string={"enrich": "yes"}).status_code == 200
    assert client.get(
        endpoint + "/export", query_string={"enrich": "yes"}
    ).status_code == 200


# Phrase: "`enrich=yes` on a cached non-enriched dataset forces re-ingestion
# and upgrades stored state." Context: the upgraded state survives a restart.
def test_enrichment_state_is_persisted(convert, client):
    import datagate

    endpoint = convert("/persisted.csv", MIXED,
                       params={"enrich": "yes"}).get_json()["endpoint"]
    datagate.load_store()  # same STORAGE_DIR, as after a restart
    payload = _payload(client, endpoint)
    assert payload["dataset_summary"]["row_count"] == 3
    assert set(payload["column_details"]) == set(payload["columns"])


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


# Phrase: "Enrichment failures return standard JSON errors ..."
# Context: an unreachable source is still the documented 404 envelope.
def test_enrich_on_unreachable_source_is_a_standard_error(client, origin):
    response = client.get(
        "/convert", query_string={"source": origin.dead_url(), "enrich": "yes"}
    )
    assert response.status_code == 404
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]


# Phrase: "Enrichment failures return standard JSON errors ..."
# Context: unparseable bytes are still the documented 400 envelope.
def test_enrich_on_unparseable_source_is_a_standard_error(convert):
    response = convert("/bad.csv", b"\x00\x01\x02notatable",
                       params={"enrich": "yes"},
                       content_type="application/octet-stream")
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert isinstance(payload["error"], str) and payload["error"]


# Phrase: "... and must not downgrade to non-enriched storage."
def test_failed_reingest_keeps_the_stored_dataset_enriched(client, origin):
    path = "/fail-keep.csv"
    origin.add(path, MIXED)
    endpoint = _convert(client, origin, path, {"enrich": "yes"}).get_json()["endpoint"]

    origin.add(path, "boom", status=500)
    failed = _convert(client, origin, path, {"enrich": "yes", "force": "1"})
    assert failed.status_code == 404
    assert failed.get_json()["ok"] is False

    payload = _payload(client, endpoint)
    assert payload["dataset_summary"]["row_count"] == 3
    assert payload["column_details"]["age"]["type"] == "integer"


# Phrase: "... and must not downgrade to non-enriched storage."
# Context: an unparseable refetch leaves the enriched dataset intact.
def test_failed_parse_keeps_the_stored_dataset_enriched(client, origin):
    path = "/fail-parse.csv"
    origin.add(path, MIXED)
    endpoint = _convert(client, origin, path, {"enrich": "yes"}).get_json()["endpoint"]

    origin.add(path, "{\"not\": \"a table\"}", content_type="application/json")
    failed = _convert(client, origin, path, {"enrich": "yes", "force": "1"})
    assert failed.status_code == 400

    payload = _payload(client, endpoint)
    assert "dataset_summary" in payload
    assert payload["rows"][0] == ["alice", 30, 1.5, 1, "x"]


# Phrase: "... and must not downgrade to non-enriched storage."
# Context: an over-limit refetch leaves the enriched dataset intact.
def test_size_rejected_reingest_keeps_enriched_state(client, origin, configure):
    path = "/fail-size.csv"
    origin.add(path, MIXED)
    endpoint = _convert(client, origin, path, {"enrich": "yes"}).get_json()["endpoint"]

    configure(MAX_SOURCE_SIZE="4")
    failed = _convert(client, origin, path, {"enrich": "yes", "force": "1"})
    assert failed.status_code == 400
    assert "dataset_summary" in _payload(client, endpoint)
