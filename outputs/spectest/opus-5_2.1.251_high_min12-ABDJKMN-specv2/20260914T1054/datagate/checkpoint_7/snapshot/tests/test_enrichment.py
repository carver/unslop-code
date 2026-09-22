"""Spec section: Optional Dataset Enrichment.

`enrich=yes` is an *ingestion* flag: it decides what `/convert` stores, and the stored
state is what `/datasets/<id>` renders.  The local origin fixture counts HTTP hits per
URL, which is the only direct evidence of "forces re-ingestion" versus "may use cache".
"""
import urllib.parse

import pytest

import datagate
from conftest import assert_error_envelope, xls_bytes, xlsx_bytes

CSV = "name,qty\nwidget,3\nbolt,7\n"
CSV2 = "a,b\n1,2\n"
SHEET = [["name", "qty"], ["widget", 3], ["bolt", 7]]

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLS_TYPE = "application/vnd.ms-excel"


def convert(client, url, extra=""):
    """GET /convert with a raw query string, so `enrich` can be sent bare/repeated."""
    query = "source=" + urllib.parse.quote(url, safe="") + extra
    return client.get("/convert", query_string=query)


def endpoint_of(response):
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["endpoint"]


def body_of(client, endpoint, query_string=None):
    response = client.get(endpoint, query_string=query_string or {})
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def ingest(client, url, extra=""):
    """Convert `url` and return the parsed /datasets/<id> payload."""
    return body_of(client, endpoint_of(convert(client, url, extra)))


def enriched_payload(client, origin, body, content_type="text/csv", extra="&enrich=yes"):
    url = origin.add(body, content_type=content_type)
    return ingest(client, url, extra)


def details(payload, column):
    return payload["column_details"][column]


@pytest.fixture()
def client_factory(monkeypatch):
    """A client whose app started with the given CACHE_ENABLED value."""

    def _make(cache_enabled=None):
        if cache_enabled is None:
            monkeypatch.delenv("CACHE_ENABLED", raising=False)
        else:
            monkeypatch.setenv("CACHE_ENABLED", cache_enabled)
        app = datagate.create_app()
        app.config.update(TESTING=True)
        return app.test_client()

    return _make


# =============================================================================
# Phrase: "`/convert` supports optional ingestion enrichment with `enrich=yes`."
# Context: the flag is accepted on /convert and changes what gets ingested.
# =============================================================================

def test_enrich_yes_is_accepted_by_convert(client, origin):
    url = origin.add(CSV)
    response = convert(client, url, "&enrich=yes")
    assert response.status_code == 200, response.get_data(as_text=True)


def test_enrich_yes_produces_metadata_on_the_dataset(client, origin):
    payload = enriched_payload(client, origin, CSV)
    assert "dataset_summary" in payload
    assert "column_details" in payload


def test_convert_without_enrich_still_works(client, origin):
    url = origin.add(CSV)
    payload = ingest(client, url)
    assert payload["rows"] == [["widget", 3], ["bolt", 7]]


# =============================================================================
# Phrase: "Only a single, exact `enrich=yes` enables enrichment."
# Context: exact value, exactly once (see AMBIGUITIES T78, T79).
# =============================================================================

def test_exact_lowercase_yes_enables_enrichment(client, origin):
    payload = enriched_payload(client, origin, CSV)
    assert payload["dataset_summary"]["row_count"] == 2


@pytest.mark.parametrize("extra", [
    "&enrich=YES",
    "&enrich=Yes",
    "&enrich=yES",
])
def test_other_casings_do_not_enable_enrichment(client, origin, extra):
    payload = enriched_payload(client, origin, CSV, extra=extra)
    assert "dataset_summary" not in payload


@pytest.mark.parametrize("extra", [
    "&enrich=%20yes",
    "&enrich=yes%20",
    "&enrich=yes.",
    "&enrich=yess",
    "&enrich=ayes",
    "&enrich=%22yes%22",
])
def test_near_miss_values_do_not_enable_enrichment(client, origin, extra):
    payload = enriched_payload(client, origin, CSV, extra=extra)
    assert "dataset_summary" not in payload


def test_repeated_enrich_yes_does_not_enable_enrichment(client, origin):
    # "single" counts occurrences, not just spellings (T79).
    payload = enriched_payload(client, origin, CSV, extra="&enrich=yes&enrich=yes")
    assert "dataset_summary" not in payload


def test_enrich_yes_beside_another_enrich_value_does_not_enable(client, origin):
    payload = enriched_payload(client, origin, CSV, extra="&enrich=no&enrich=yes")
    assert "dataset_summary" not in payload


# =============================================================================
# Phrase: "All other states keep enrichment off."
# Context: absent, empty, bare, or any other value - off, and never an error (T78).
# =============================================================================

@pytest.mark.parametrize("extra", [
    "",
    "&enrich=",
    "&enrich",
    "&enrich=no",
    "&enrich=1",
    "&enrich=true",
    "&enrich=on",
    "&enrich=0",
])
def test_all_other_states_keep_enrichment_off(client, origin, extra):
    payload = enriched_payload(client, origin, CSV, extra=extra)
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


@pytest.mark.parametrize("extra", [
    "&enrich=",
    "&enrich",
    "&enrich=no",
    "&enrich=YES",
    "&enrich=yes&enrich=yes",
])
def test_other_enrich_states_are_not_errors(client, origin, extra):
    url = origin.add(CSV)
    response = convert(client, url, extra)
    assert response.status_code == 200, response.get_data(as_text=True)


# =============================================================================
# Phrase: 'Success response remains: {"ok": true, "endpoint": "/datasets/<id>"}'
# Context: enrichment adds nothing to the /convert reply.
# =============================================================================

def test_success_response_shape_is_unchanged_with_enrich(client, origin):
    url = origin.add(CSV)
    payload = convert(client, url, "&enrich=yes").get_json()
    assert set(payload) == {"ok", "endpoint"}
    assert payload["ok"] is True
    assert payload["endpoint"].startswith("/datasets/")


def test_enrich_does_not_change_the_endpoint_for_a_source(client, origin):
    url = origin.add(CSV)
    plain = endpoint_of(convert(client, url))
    enriched = endpoint_of(convert(client, url, "&enrich=yes"))
    assert plain == enriched


# =============================================================================
# Phrase: "For enriched CSV datasets, add `dataset_summary` with at least
#          `filetype`, `row_count`, `column_count`."
# Context: dataset-wide summary of the ingested table (T80, T86).
# =============================================================================

def test_csv_dataset_summary_has_the_three_required_keys(client, origin):
    summary = enriched_payload(client, origin, CSV)["dataset_summary"]
    assert {"filetype", "row_count", "column_count"} <= set(summary)


def test_csv_filetype_label(client, origin):
    summary = enriched_payload(client, origin, CSV)["dataset_summary"]
    assert summary["filetype"] == "csv"


def test_row_count_counts_data_rows_not_the_header(client, origin):
    body = "a,b\n1,2\n3,4\n5,6\n"
    summary = enriched_payload(client, origin, body)["dataset_summary"]
    assert summary["row_count"] == 3


def test_column_count_is_the_header_width(client, origin):
    summary = enriched_payload(client, origin, "a,b,c\n1,2,3\n")["dataset_summary"]
    assert summary["column_count"] == 3


def test_counts_are_dataset_wide_not_page_wide(client, origin):
    # Metadata comes from ingestion, so query controls cannot move it (T86).
    url = origin.add("a,b\n1,2\n3,4\n5,6\n")
    endpoint = endpoint_of(convert(client, url, "&enrich=yes"))
    payload = body_of(client, endpoint, {"_size": "1", "_offset": "1"})
    assert len(payload["rows"]) == 1
    assert payload["dataset_summary"]["row_count"] == 3


def test_counts_are_not_the_filtered_count(client, origin):
    url = origin.add("a,b\n1,2\n3,4\n5,6\n")
    endpoint = endpoint_of(convert(client, url, "&enrich=yes"))
    payload = body_of(client, endpoint, {"a__exact": "1"})
    assert payload["total"] == 1
    assert payload["dataset_summary"]["row_count"] == 3


# =============================================================================
# Phrase: "`column_details` keyed by column name with at least `type`,
#          `distinct_count`, `missing_count`."
# Context: one entry per column, addressed by its header text.
# =============================================================================

def test_column_details_is_keyed_by_column_name(client, origin):
    payload = enriched_payload(client, origin, CSV)
    assert set(payload["column_details"]) == set(payload["columns"])


def test_each_column_entry_has_the_three_required_keys(client, origin):
    payload = enriched_payload(client, origin, CSV)
    for entry in payload["column_details"].values():
        assert {"type", "distinct_count", "missing_count"} <= set(entry)


def test_distinct_count_counts_distinct_values(client, origin):
    body = "c\na\nb\na\nc\n"
    payload = enriched_payload(client, origin, body)
    assert details(payload, "c")["distinct_count"] == 3


def test_distinct_count_excludes_missing_values(client, origin):
    # Blanks are reported by missing_count alone (T83).
    body = "c,d\na,1\nb,2\n,3\na,4\n"
    payload = enriched_payload(client, origin, body)
    assert details(payload, "c")["distinct_count"] == 2
    assert details(payload, "c")["missing_count"] == 1


def test_missing_count_counts_blank_cells(client, origin):
    body = "c,d\n,1\n,2\nx,3\n"
    payload = enriched_payload(client, origin, body)
    assert details(payload, "c")["missing_count"] == 2
    assert details(payload, "d")["missing_count"] == 0


def test_whitespace_only_cells_are_missing(client, origin):
    body = 'c,d\n"   ",1\nx,2\n'
    payload = enriched_payload(client, origin, body)
    assert details(payload, "c")["missing_count"] == 1


def test_short_rows_pad_into_missing_cells(client, origin):
    body = "c,d\nx\ny,2\n"
    payload = enriched_payload(client, origin, body)
    assert details(payload, "d")["missing_count"] == 1


def test_counts_cover_every_row_not_just_the_first_page(client, origin):
    body = "c\n" + "".join("v%d\n" % n for n in range(120))
    payload = enriched_payload(client, origin, body)
    assert details(payload, "c")["distinct_count"] == 120


def test_numeric_distinctness_uses_values_not_text(client, origin):
    body = "n\n1\n1\n2\n"
    payload = enriched_payload(client, origin, body)
    assert details(payload, "n")["distinct_count"] == 2


# =============================================================================
# Phrase: "Type labels: `text`, `number`, `integer`, `float`."
# Context: the closed vocabulary for a column's `type` (T81, T82).
# =============================================================================

TYPED = (
    "words,ints,floats,mixed,blank\n"
    "text,1,1.5,1,\n"
    "more,2,2.5,2.5,\n"
)


def test_text_column_type(client, origin):
    payload = enriched_payload(client, origin, TYPED)
    assert details(payload, "words")["type"] == "text"


def test_integer_column_type(client, origin):
    payload = enriched_payload(client, origin, TYPED)
    assert details(payload, "ints")["type"] == "integer"


def test_float_column_type(client, origin):
    payload = enriched_payload(client, origin, TYPED)
    assert details(payload, "floats")["type"] == "float"


def test_mixed_numeric_column_is_number(client, origin):
    payload = enriched_payload(client, origin, TYPED)
    assert details(payload, "mixed")["type"] == "number"


def test_all_blank_column_is_text(client, origin):
    payload = enriched_payload(client, origin, TYPED)
    assert details(payload, "blank")["type"] == "text"


def test_a_single_non_numeric_value_makes_the_column_text(client, origin):
    body = "n\n1\n2\nn/a\n"
    payload = enriched_payload(client, origin, body)
    assert details(payload, "n")["type"] == "text"


def test_missing_cells_do_not_break_a_numeric_column(client, origin):
    body = "n\n1\n\n3\n"
    payload = enriched_payload(client, origin, body)
    assert details(payload, "n")["type"] == "integer"


def test_every_type_label_is_from_the_documented_vocabulary(client, origin):
    payload = enriched_payload(client, origin, TYPED)
    labels = {entry["type"] for entry in payload["column_details"].values()}
    assert labels <= {"text", "number", "integer", "float"}


def test_negative_and_exponent_literals_keep_their_kinds(client, origin):
    body = "i,f\n-3,-2.5\n+4,1e3\n"
    payload = enriched_payload(client, origin, body)
    assert details(payload, "i")["type"] == "integer"
    assert details(payload, "f")["type"] == "float"


# =============================================================================
# Phrase: "For enriched spreadsheet datasets, add only `dataset_summary` with
#          `filetype: "excel"`."
# Context: workbooks get the summary and no column_details (T85).
# =============================================================================

def test_xlsx_summary_filetype_is_excel(client, origin):
    payload = enriched_payload(client, origin, xlsx_bytes(SHEET),
                               content_type=XLSX_TYPE)
    assert payload["dataset_summary"]["filetype"] == "excel"


def test_xls_summary_filetype_is_excel(client, origin):
    payload = enriched_payload(client, origin, xls_bytes(SHEET),
                               content_type=XLS_TYPE)
    assert payload["dataset_summary"]["filetype"] == "excel"


def test_spreadsheet_has_no_column_details(client, origin):
    payload = enriched_payload(client, origin, xlsx_bytes(SHEET),
                               content_type=XLSX_TYPE)
    assert "column_details" not in payload


def test_spreadsheet_summary_still_carries_the_counts(client, origin):
    payload = enriched_payload(client, origin, xlsx_bytes(SHEET),
                               content_type=XLSX_TYPE)
    summary = payload["dataset_summary"]
    assert summary["row_count"] == 2
    assert summary["column_count"] == 2


def test_non_enriched_spreadsheet_has_no_summary(client, origin):
    payload = enriched_payload(client, origin, xlsx_bytes(SHEET),
                               content_type=XLSX_TYPE, extra="")
    assert "dataset_summary" not in payload


def test_filetype_follows_the_bytes_not_the_url(client, origin):
    # Format is sniffed from the content (T50), so a .csv URL serving a workbook
    # is still "excel".
    url = origin.add(xlsx_bytes(SHEET), path="/looks-like.csv", content_type="text/csv")
    payload = ingest(client, url, "&enrich=yes")
    assert payload["dataset_summary"]["filetype"] == "excel"


# =============================================================================
# Phrase: "Non-enriched responses omit both metadata fields (no `null`/empty
#          objects)."
# Context: absence, not a placeholder.
# =============================================================================

def test_non_enriched_response_omits_both_fields(client, origin):
    url = origin.add(CSV)
    payload = ingest(client, url)
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


def test_non_enriched_response_key_set_is_the_original_one(client, origin):
    url = origin.add(CSV)
    payload = ingest(client, url)
    assert set(payload) == {"ok", "columns", "rows", "total", "query_ms"}


def test_uploaded_dataset_omits_both_fields(client, uploaded):
    status, payload = uploaded(CSV)
    assert status == 200
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


# =============================================================================
# Phrase: "`rows`, `columns`, `ok`, `query_ms`, and `total` do not change."
# Context: enrichment is additive to the query response.
# =============================================================================

def test_enrichment_does_not_change_rows_columns_ok_or_total(client, origin):
    plain = ingest(client, origin.add(CSV))
    rich = ingest(client, origin.add(CSV), "&enrich=yes")
    assert rich["ok"] is plain["ok"] is True
    assert rich["columns"] == plain["columns"]
    assert rich["rows"] == plain["rows"]
    assert rich["total"] == plain["total"]


def test_enriched_response_still_reports_query_ms(client, origin):
    payload = enriched_payload(client, origin, CSV)
    assert isinstance(payload["query_ms"], (int, float))


def test_enriched_response_adds_exactly_the_two_fields(client, origin):
    payload = enriched_payload(client, origin, CSV)
    assert set(payload) == {"ok", "columns", "rows", "total", "query_ms",
                            "dataset_summary", "column_details"}


def test_query_controls_still_apply_to_an_enriched_dataset(client, origin):
    url = origin.add("a,b\n1,2\n3,4\n5,6\n")
    endpoint = endpoint_of(convert(client, url, "&enrich=yes"))
    payload = body_of(client, endpoint, {"_size": "2", "_shape": "objects",
                                         "_rowid": "hide", "_sort_desc": "a"})
    assert payload["rows"] == [{"a": 5, "b": 6}, {"a": 3, "b": 4}]
    assert payload["total"] == 3


def test_export_of_an_enriched_dataset_is_unchanged(client, origin):
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url, "&enrich=yes"))
    response = client.get(endpoint + "/export")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "name,qty\r\nwidget,3\r\nbolt,7\r\n"


# =============================================================================
# Phrase: "`enrich=yes` on a cached non-enriched dataset forces re-ingestion and
#          upgrades stored state."
# Context: the missing metadata is worth a re-download.
# =============================================================================

def test_enrich_on_a_cached_plain_dataset_re_downloads(client, origin):
    url = origin.add(CSV)
    convert(client, url)
    assert origin.hits(url) == 1
    convert(client, url, "&enrich=yes")
    assert origin.hits(url) == 2


def test_enrich_on_a_cached_plain_dataset_upgrades_stored_state(client, origin):
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url))
    assert "dataset_summary" not in body_of(client, endpoint)
    convert(client, url, "&enrich=yes")
    assert "dataset_summary" in body_of(client, endpoint)


def test_the_upgrade_survives_into_later_plain_requests(client, origin):
    url = origin.add(CSV)
    convert(client, url)
    endpoint = endpoint_of(convert(client, url, "&enrich=yes"))
    convert(client, url)
    assert "dataset_summary" in body_of(client, endpoint)


# =============================================================================
# Phrase: "`enrich=yes` on a cached enriched dataset may use cache."
# Context: the second enriching request is an ordinary cache hit (T89).
# =============================================================================

def test_second_enrich_request_does_not_re_download(client, origin):
    url = origin.add(CSV)
    convert(client, url, "&enrich=yes")
    assert origin.hits(url) == 1
    convert(client, url, "&enrich=yes")
    assert origin.hits(url) == 1


def test_second_enrich_request_keeps_the_metadata(client, origin):
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url, "&enrich=yes"))
    convert(client, url, "&enrich=yes")
    assert body_of(client, endpoint)["dataset_summary"]["row_count"] == 2


# =============================================================================
# Phrase: "Requests without re-ingestion do not change stored enrichment state."
# Context: a cache hit never downgrades (or upgrades) what is stored.
# =============================================================================

def test_plain_cache_hit_does_not_downgrade_an_enriched_dataset(client, origin):
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url, "&enrich=yes"))
    response = convert(client, url)
    assert response.status_code == 200
    assert origin.hits(url) == 1  # no re-ingestion happened
    assert "dataset_summary" in body_of(client, endpoint)


def test_plain_cache_hit_does_not_enrich_a_plain_dataset(client, origin):
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url))
    convert(client, url)
    assert "dataset_summary" not in body_of(client, endpoint)


def test_querying_the_dataset_does_not_change_stored_state(client, origin):
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url, "&enrich=yes"))
    body_of(client, endpoint)
    assert "dataset_summary" in body_of(client, endpoint)


def test_enrichment_state_survives_a_restart_over_the_same_storage_dir(
    make_app, origin, tmp_path
):
    store = str(tmp_path / "store")
    first = make_app(STORAGE_DIR=store).test_client()
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(first, url, "&enrich=yes"))
    second = make_app(STORAGE_DIR=store).test_client()
    payload = body_of(second, endpoint)
    assert payload["dataset_summary"]["row_count"] == 2
    assert payload["column_details"]["qty"]["type"] == "integer"


# =============================================================================
# Phrase: "Re-ingestion recomputes metadata from current source bytes."
# Context: refreshed content produces refreshed metadata (T88).
# =============================================================================

def test_forced_re_ingestion_recomputes_metadata(client, origin):
    url = origin.add("a\n1\n")
    endpoint = endpoint_of(convert(client, url, "&enrich=yes"))
    assert body_of(client, endpoint)["dataset_summary"]["row_count"] == 1
    origin.update(url, "a,b\n1,2\n3,4\n")
    convert(client, url, "&enrich=yes&force")
    payload = body_of(client, endpoint)
    assert payload["dataset_summary"]["row_count"] == 2
    assert payload["dataset_summary"]["column_count"] == 2
    assert set(payload["column_details"]) == {"a", "b"}


def test_upgrade_re_ingestion_sees_the_current_bytes(client, origin):
    url = origin.add("a\n1\n")
    endpoint = endpoint_of(convert(client, url))
    origin.update(url, "a\n1\n2\n3\n")
    convert(client, url, "&enrich=yes")
    payload = body_of(client, endpoint)
    assert payload["rows"] == [[1], [2], [3]]
    assert payload["dataset_summary"]["row_count"] == 3


def test_re_ingestion_without_enrich_stores_a_plain_dataset(client, origin):
    # The request that re-ingests decides the stored state (T88).
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url, "&enrich=yes"))
    convert(client, url, "&force")
    assert "dataset_summary" not in body_of(client, endpoint)


def test_with_caching_off_each_request_sets_the_state(client_factory, origin):
    client = client_factory("false")
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url, "&enrich=yes"))
    assert "dataset_summary" in body_of(client, endpoint)
    convert(client, url)
    assert "dataset_summary" not in body_of(client, endpoint)
    convert(client, url, "&enrich=yes")
    assert "dataset_summary" in body_of(client, endpoint)


# =============================================================================
# Phrase: "`enrich` applies only on `/convert`."
# Context: other routes ignore the parameter entirely (T90).
# =============================================================================

def test_upload_ignores_enrich(client):
    import io

    response = client.post(
        "/upload",
        data={"file": (io.BytesIO(CSV.encode()), "d.csv")},
        content_type="multipart/form-data",
        query_string="enrich=yes",
    )
    assert response.status_code == 200
    payload = body_of(client, response.get_json()["endpoint"])
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


def test_dataset_query_enrich_does_not_add_metadata(client, origin):
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url))
    payload = body_of(client, endpoint, {"enrich": "yes"})
    assert "dataset_summary" not in payload


def test_dataset_query_enrich_does_not_remove_metadata(client, origin):
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url, "&enrich=yes"))
    assert "dataset_summary" in body_of(client, endpoint, {"enrich": "no"})


def test_export_accepts_enrich_without_changing_the_bytes(client, origin):
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url, "&enrich=yes"))
    plain = client.get(endpoint + "/export")
    with_flag = client.get(endpoint + "/export", query_string={"enrich": "yes"})
    assert with_flag.status_code == 200
    assert with_flag.get_data() == plain.get_data()


# =============================================================================
# Phrase: "Enrichment failures return standard JSON errors and must not downgrade
#          to non-enriched storage."
# Context: the usual envelope and status; the store is never the loser (T91).
# =============================================================================

def test_enriching_convert_of_a_bad_url_is_the_standard_400(client):
    response = client.get("/convert", query_string="source=not a url&enrich=yes")
    assert_error_envelope(response, 400)


def test_enriching_convert_of_an_unreachable_source_is_the_standard_404(client, origin):
    response = convert(client, origin.url_for("/missing.csv"), "&enrich=yes")
    assert_error_envelope(response, 404)


def test_enriching_convert_of_non_tabular_bytes_is_the_standard_400(client, origin):
    url = origin.add("just one line, no data rows\n")
    assert_error_envelope(convert(client, url, "&enrich=yes"), 400)


def test_a_failed_upgrade_leaves_the_plain_dataset_intact(client, origin):
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url))
    origin.remove(url)
    assert_error_envelope(convert(client, url, "&enrich=yes"), 404)
    payload = body_of(client, endpoint)
    assert payload["rows"] == [["widget", 3], ["bolt", 7]]
    assert "dataset_summary" not in payload


def test_a_failed_refresh_does_not_downgrade_an_enriched_dataset(client, origin):
    url = origin.add(CSV)
    endpoint = endpoint_of(convert(client, url, "&enrich=yes"))
    origin.update(url, "not a table at all")
    assert_error_envelope(convert(client, url, "&enrich=yes&force"), 400)
    payload = body_of(client, endpoint)
    assert payload["rows"] == [["widget", 3], ["bolt", 7]]
    assert payload["dataset_summary"]["row_count"] == 2
    assert payload["column_details"]["qty"]["type"] == "integer"


def test_a_metadata_failure_stores_nothing(client, origin, monkeypatch):
    url = origin.add(CSV)

    def boom(*args, **kwargs):
        raise RuntimeError("metadata exploded")

    monkeypatch.setattr(datagate, "build_metadata", boom)
    response = convert(client, url, "&enrich=yes")
    assert_error_envelope(response, 500)
    assert client.get("/datasets/" + datagate.dataset_id(url)).status_code == 404
