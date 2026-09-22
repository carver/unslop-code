"""Spec section: Optional Dataset Enrichment."""

from urllib.parse import quote

import pytest
from conftest import SIMPLE_CSV, SIMPLE_SHEET, SOURCE_URL, xls_bytes, xlsx_bytes

from datagate_app import ingestion
from datagate_app.errors import DataGateError
from datagate_app.store import dataset_id

METADATA_FIELDS = ("dataset_summary", "column_details")

# name: repeated text; age: whole numbers with a gap; score: decimals; amount: whole and decimal mixed.
MIXED_CSV = "name,age,score,amount\nada,36,4.5,2\ngrace,45,3.25,1.5\nada,,4.5,3\n"

OTHER_URL = "https://example.test/other.csv"


def convert(client, source=SOURCE_URL, **params):
    return client.get("/convert", query_string={"source": source, **params})


def convert_raw(client, suffix, source=SOURCE_URL):
    """Convert with a hand-built query string, for flag states a dict cannot express."""
    return client.get(f"/convert?source={quote(source, safe='')}&{suffix}")


def body_of(client, response):
    """Follow a `/convert` response through to its dataset payload."""
    assert response.status_code == 200, response.get_json()
    return client.get(response.get_json()["endpoint"]).get_json()


@pytest.fixture
def enriched(client, serve):
    """Convert a payload with `enrich=yes` and return its dataset payload."""

    def _enriched(body, content_type="text/csv", url=SOURCE_URL):
        return body_of(client, convert(client, serve(body, url, content_type), enrich="yes"))

    return _enriched


def _explode(*_args, **_kwargs):
    raise DataGateError("Enrichment failed", 400)


# Phrase: "`/convert` supports optional ingestion enrichment with `enrich=yes`."
def test_convert_accepts_enrich_yes(client, serve):
    assert convert(client, serve(SIMPLE_CSV), enrich="yes").status_code == 200


# Phrase: "Only a single, exact `enrich=yes` enables enrichment."
def test_exact_enrich_yes_enables_enrichment(enriched):
    assert "dataset_summary" in enriched(SIMPLE_CSV)


# Phrase: "All other states keep enrichment off." (context: values other than the exact `yes`)
@pytest.mark.parametrize("value", ["", "no", "1", "0", "true", "false", "YES", "Yes", "yess", " yes", "yes "])
def test_other_enrich_values_keep_enrichment_off(client, serve, value):
    body = body_of(client, convert(client, serve(SIMPLE_CSV), enrich=value))

    assert not [field for field in METADATA_FIELDS if field in body]


# Phrase: "All other states keep enrichment off." (context: the flag with no `=value` at all)
def test_valueless_enrich_keeps_enrichment_off(client, serve):
    serve(SIMPLE_CSV)

    body = body_of(client, convert_raw(client, "enrich"))

    assert not [field for field in METADATA_FIELDS if field in body]


# Phrase: "Only a single, exact `enrich=yes` ..." (context: "single" -- a repeated flag is not single)
@pytest.mark.parametrize("suffix", ["enrich=yes&enrich=yes", "enrich=yes&enrich=no", "enrich=no&enrich=yes"])
def test_repeated_enrich_keeps_enrichment_off(client, serve, suffix):
    serve(SIMPLE_CSV)

    body = body_of(client, convert_raw(client, suffix))

    assert not [field for field in METADATA_FIELDS if field in body]


# Phrase: "All other states keep enrichment off." (context: an unusable state is still a success)
@pytest.mark.parametrize("suffix", ["enrich=maybe", "enrich", "enrich=yes&enrich=yes"])
def test_other_enrich_states_are_not_errors(client, serve, suffix):
    serve(SIMPLE_CSV)

    assert convert_raw(client, suffix).status_code == 200


# Phrase: "Success response remains: {"ok": true, "endpoint": "/datasets/<id>"}"
def test_enriched_convert_keeps_the_success_envelope(client, serve):
    response = convert(client, serve(SIMPLE_CSV), enrich="yes")

    body = response.get_json()
    assert set(body) == {"ok", "endpoint"}
    assert body["ok"] is True
    assert body["endpoint"] == f"/datasets/{dataset_id(SOURCE_URL)}"


# Phrase: "Success response remains ..." (context: the id does not depend on enrichment)
def test_enrichment_does_not_change_the_dataset_id(client, serve):
    serve(SIMPLE_CSV, url=OTHER_URL)
    serve(SIMPLE_CSV)

    plain = convert(client, OTHER_URL).get_json()["endpoint"]
    rich = convert(client, SOURCE_URL, enrich="yes").get_json()["endpoint"]

    assert plain != rich and rich == f"/datasets/{dataset_id(SOURCE_URL)}"


# Phrase: "For enriched CSV datasets, add: `dataset_summary` with at least `filetype`, `row_count`, `column_count`"
def test_enriched_csv_has_a_dataset_summary(enriched):
    summary = enriched(MIXED_CSV)["dataset_summary"]

    assert {"filetype", "row_count", "column_count"} <= set(summary)


# Phrase: "`dataset_summary` with at least `filetype` ..." (context: CSV is not the `excel` filetype, T73)
def test_csv_summary_reports_the_csv_filetype(enriched):
    assert enriched(MIXED_CSV)["dataset_summary"]["filetype"] == "csv"


# Phrase: "`dataset_summary` with at least ... `row_count`, `column_count`" (T78: the whole stored table)
def test_summary_counts_describe_the_whole_table(enriched):
    summary = enriched(MIXED_CSV)["dataset_summary"]

    assert summary["row_count"] == 3 and summary["column_count"] == 4


# Phrase: "... `row_count` ..." (context: the header row is not a data row)
def test_row_count_excludes_the_header_row(enriched):
    assert enriched(SIMPLE_CSV)["dataset_summary"]["row_count"] == 2


# Phrase: "`column_details` keyed by column name"
def test_column_details_are_keyed_by_column_name(enriched):
    body = enriched(MIXED_CSV)

    assert set(body["column_details"]) == set(body["columns"])


# Phrase: "`column_details` ... with at least `type`, `distinct_count`, `missing_count`"
def test_every_column_detail_carries_the_three_fields(enriched):
    details = enriched(MIXED_CSV)["column_details"]

    assert all({"type", "distinct_count", "missing_count"} <= set(detail) for detail in details.values())


# Phrase: "Type labels: `text`, `number`, `integer`, `float`." (T75: the numeric labels refine `number`)
@pytest.mark.parametrize(
    ("column", "label"),
    [("name", "text"), ("age", "integer"), ("score", "float"), ("amount", "number")],
)
def test_column_type_labels(enriched, column, label):
    assert enriched(MIXED_CSV)["column_details"][column]["type"] == label


# Phrase: "Type labels: ..." (context: a column mixing words and numbers is text)
def test_a_column_mixing_numbers_and_words_is_text(enriched):
    body = enriched("code\n7\nseven\n")

    assert body["column_details"]["code"]["type"] == "text"


# Phrase: "Type labels: ..." (T76: gaps do not decide the type; T77: nor are they distinct values)
def test_missing_cells_do_not_change_a_numeric_type(enriched):
    detail = enriched(MIXED_CSV)["column_details"]["age"]

    assert detail == {"type": "integer", "distinct_count": 2, "missing_count": 1}


# Phrase: "... `distinct_count` ..." (context: repeated values count once)
def test_distinct_count_counts_each_value_once(enriched):
    details = enriched(MIXED_CSV)["column_details"]

    assert details["name"]["distinct_count"] == 2 and details["score"]["distinct_count"] == 2


# Phrase: "... `missing_count`" (context: a column with no gaps reports zero)
def test_missing_count_is_zero_without_gaps(enriched):
    assert enriched(MIXED_CSV)["column_details"]["name"]["missing_count"] == 0


# Phrase: "... `missing_count`" (T76: short rows are padded, and the padding is missing)
def test_short_rows_count_as_missing(enriched):
    detail = enriched("name,age\nada,36\ngrace\n")["column_details"]["age"]

    assert detail["missing_count"] == 1


# Phrase: "For enriched spreadsheet datasets, add only `dataset_summary` with `filetype: "excel"`."
@pytest.mark.parametrize("workbook", [xlsx_bytes, xls_bytes], ids=["xlsx", "xls"])
def test_enriched_workbook_reports_the_excel_filetype(enriched, workbook):
    body = enriched(workbook(SIMPLE_SHEET), content_type="application/octet-stream")

    assert body["dataset_summary"]["filetype"] == "excel"


# Phrase: "... add only `dataset_summary` ..." (context: a workbook gets no column details)
@pytest.mark.parametrize("workbook", [xlsx_bytes, xls_bytes], ids=["xlsx", "xls"])
def test_enriched_workbook_has_no_column_details(enriched, workbook):
    assert "column_details" not in enriched(workbook(SIMPLE_SHEET), content_type="application/octet-stream")


# Phrase: "... add only `dataset_summary` ..." (T74: the summary keeps the shape it has for CSV)
def test_workbook_summary_still_carries_the_counts(enriched):
    summary = enriched(xlsx_bytes(SIMPLE_SHEET), content_type="application/octet-stream")["dataset_summary"]

    assert summary["row_count"] == 2 and summary["column_count"] == 2


# Phrase: "Non-enriched responses omit both metadata fields (no `null`/empty objects)."
def test_non_enriched_response_omits_both_fields(dataset):
    body = dataset(MIXED_CSV)

    assert "dataset_summary" not in body and "column_details" not in body


# Phrase: "`rows`, `columns`, `ok`, `query_ms`, and `total` do not change."
def test_enrichment_leaves_the_other_fields_alone(client, serve):
    serve(SIMPLE_CSV, url=OTHER_URL)
    serve(MIXED_CSV)
    plain = body_of(client, convert(client, OTHER_URL))
    rich = body_of(client, convert(client, SOURCE_URL, enrich="yes"))

    assert set(rich) - set(plain) == set(METADATA_FIELDS)
    assert rich["ok"] is True
    assert rich["columns"] == ["name", "age", "score", "amount"]
    assert rich["rows"] == [["ada", 36, 4.5, 2], ["grace", 45, 3.25, 1.5], ["ada", "", 4.5, 3]]
    assert rich["total"] == 3
    assert isinstance(rich["query_ms"], float) and isinstance(plain["query_ms"], float)


# Phrase: "`rows`, `columns`, ... and `total` do not change." (context: controls and filters still apply)
def test_controls_still_apply_to_an_enriched_dataset(client, serve):
    endpoint = convert(client, serve(MIXED_CSV), enrich="yes").get_json()["endpoint"]

    body = client.get(endpoint + "?age__greater=40&_shape=objects").get_json()

    assert body["rows"] == [{"rowid": 3, "name": "grace", "age": 45, "score": 3.25, "amount": 1.5}]
    assert body["total"] == 1


# Phrase: "`total` does not change." (T78: a filtered query does not change the summary counts)
def test_filters_do_not_change_the_summary(client, serve):
    endpoint = convert(client, serve(MIXED_CSV), enrich="yes").get_json()["endpoint"]

    body = client.get(endpoint + "?age__greater=40").get_json()

    assert body["dataset_summary"]["row_count"] == 3 and body["total"] == 1


# Phrase: "`enrich=yes` on a cached non-enriched dataset forces re-ingestion ..."
def test_enrich_on_a_cached_plain_dataset_re_ingests(client, serve, remote):
    serve(SIMPLE_CSV)
    serve(SIMPLE_CSV)
    convert(client, SOURCE_URL)

    convert(client, SOURCE_URL, enrich="yes")

    assert len(remote.calls) == 2


# Phrase: "... and upgrades stored state."
def test_enrich_upgrades_the_stored_dataset(client, serve):
    serve(SIMPLE_CSV)
    serve(SIMPLE_CSV)
    convert(client, SOURCE_URL)

    body = body_of(client, convert(client, SOURCE_URL, enrich="yes"))

    assert body["dataset_summary"]["row_count"] == 2


# Phrase: "... upgrades stored state." (context: the upgrade outlives the request that asked for it)
def test_the_upgrade_is_visible_to_later_plain_requests(client, serve):
    serve(SIMPLE_CSV)
    serve(SIMPLE_CSV)
    convert(client, SOURCE_URL)
    convert(client, SOURCE_URL, enrich="yes")

    assert "dataset_summary" in body_of(client, convert(client, SOURCE_URL))


# Phrase: "`enrich=yes` on a cached enriched dataset may use cache."
def test_enrich_on_a_cached_enriched_dataset_uses_the_cache(client, serve, remote):
    serve(SIMPLE_CSV)
    serve(SIMPLE_CSV)
    convert(client, SOURCE_URL, enrich="yes")

    convert(client, SOURCE_URL, enrich="yes")

    assert len(remote.calls) == 1


# Phrase: "... may use cache." (context: the cached answer is still the enriched one)
def test_the_cached_enriched_dataset_still_reports_metadata(client, serve):
    serve(SIMPLE_CSV)
    convert(client, SOURCE_URL, enrich="yes")

    assert "dataset_summary" in body_of(client, convert(client, SOURCE_URL, enrich="yes"))


# Phrase: "Requests without re-ingestion do not change stored enrichment state."
def test_a_plain_cache_hit_keeps_the_dataset_enriched(client, serve, remote):
    serve(SIMPLE_CSV)
    convert(client, SOURCE_URL, enrich="yes")

    body = body_of(client, convert(client, SOURCE_URL))

    assert "dataset_summary" in body and len(remote.calls) == 1


# Phrase: "Requests without re-ingestion do not change stored enrichment state." (context: still non-enriched)
def test_a_plain_cache_hit_keeps_the_dataset_non_enriched(client, serve, remote):
    serve(SIMPLE_CSV)
    convert(client, SOURCE_URL)

    body = body_of(client, convert(client, SOURCE_URL))

    assert "dataset_summary" not in body and len(remote.calls) == 1


# Phrase: "Re-ingestion recomputes metadata from current source bytes."
def test_re_ingestion_recomputes_the_metadata(client, serve):
    serve(SIMPLE_CSV)
    serve("name,age,city\nada,36,london\n")
    convert(client, SOURCE_URL, enrich="yes")

    body = body_of(client, convert(client, SOURCE_URL, enrich="yes", force=""))

    assert body["dataset_summary"] == {"filetype": "csv", "row_count": 1, "column_count": 3}


# Phrase: "Re-ingestion recomputes metadata ..." (context: the upgrade reads the bytes now on offer)
def test_the_upgrade_reads_the_current_bytes(client, serve):
    serve(SIMPLE_CSV)
    serve("name,age\nada,36\ngrace,45\nlinus,52\n")
    convert(client, SOURCE_URL)

    body = body_of(client, convert(client, SOURCE_URL, enrich="yes"))

    assert body["dataset_summary"]["row_count"] == 3 and body["total"] == 3


# Phrase: "Re-ingestion recomputes metadata ..." (T79: a re-ingestion that did not ask to enrich does not)
def test_a_forced_plain_re_ingestion_drops_the_metadata(client, serve):
    serve(SIMPLE_CSV)
    serve(SIMPLE_CSV)
    convert(client, SOURCE_URL, enrich="yes")

    body = body_of(client, convert(client, SOURCE_URL, force=""))

    assert "dataset_summary" not in body


# Phrase: "`enrich` applies only on `/convert`." (context: uploads are never enriched)
def test_enrich_is_ignored_on_upload(uploaded):
    body = uploaded(MIXED_CSV.encode(), query={"enrich": "yes"})

    assert "dataset_summary" not in body and "column_details" not in body


# Phrase: "`enrich` applies only on `/convert`." (context: a query cannot enrich a stored dataset)
def test_enrich_is_ignored_on_a_dataset_query(client, serve):
    endpoint = convert(client, serve(SIMPLE_CSV)).get_json()["endpoint"]

    body = client.get(endpoint + "?enrich=yes").get_json()

    assert body["ok"] is True and "dataset_summary" not in body


# Phrase: "Enrichment failures return standard JSON errors ..."
def test_an_enrichment_failure_is_a_json_error(client, serve, monkeypatch):
    monkeypatch.setattr(ingestion, "describe", _explode)

    response = convert(client, serve(SIMPLE_CSV), enrich="yes")

    assert response.status_code == 400
    assert response.get_json() == {"ok": False, "error": "Enrichment failed"}


# Phrase: "Enrichment failures return standard JSON errors ..." (context: a failing enriched re-ingestion)
def test_a_failing_enriched_re_ingestion_reports_its_usual_status(client, serve):
    serve(SIMPLE_CSV)
    serve("<html><body>gone</body></html>", content_type="text/html")
    convert(client, SOURCE_URL)

    response = convert(client, SOURCE_URL, enrich="yes")

    assert response.status_code == 400 and response.get_json()["ok"] is False


# Phrase: "... and must not downgrade to non-enriched storage."
def test_a_failed_enrichment_leaves_the_stored_dataset_enriched(client, serve, monkeypatch):
    serve(SIMPLE_CSV)
    serve(SIMPLE_CSV)
    convert(client, SOURCE_URL, enrich="yes")
    monkeypatch.setattr(ingestion, "describe", _explode)

    assert convert(client, SOURCE_URL, enrich="yes", force="").status_code == 400
    assert "dataset_summary" in client.get(f"/datasets/{dataset_id(SOURCE_URL)}").get_json()


# Phrase: "... must not downgrade to non-enriched storage." (context: the previous rows stay queryable)
def test_a_failed_enrichment_keeps_the_previous_rows(client, serve, monkeypatch):
    serve(SIMPLE_CSV)
    serve("name,age\nlinus,52\n")
    convert(client, SOURCE_URL, enrich="yes")
    monkeypatch.setattr(ingestion, "describe", _explode)

    convert(client, SOURCE_URL, enrich="yes", force="")

    assert client.get(f"/datasets/{dataset_id(SOURCE_URL)}").get_json()["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "... must not downgrade ..." (context: a failed upgrade does not replace a plain dataset either)
def test_a_failed_upgrade_leaves_the_plain_dataset_alone(client, serve, monkeypatch):
    serve(SIMPLE_CSV)
    serve(SIMPLE_CSV)
    convert(client, SOURCE_URL)
    monkeypatch.setattr(ingestion, "describe", _explode)

    assert convert(client, SOURCE_URL, enrich="yes").status_code == 400
    assert client.get(f"/datasets/{dataset_id(SOURCE_URL)}").get_json()["rows"] == [["ada", 36], ["grace", 45]]
