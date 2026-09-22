"""Spec section: Optional Dataset Enrichment."""

import io

import pytest

from datagate_core.store import dataset_id
from tests.conftest import (
    SIMPLE_CSV,
    TEAMS_SHEET,
    numbered_csv,
    xls_bytes,
    xlsx_bytes,
)

ENRICH = "&enrich=yes"

#: Four columns, one per type label: text, integer, number (mixed), and a
#: text column with a blank cell for the missing/distinct counts.
TYPED_CSV = "name,age,score,note\nada,36,1.5,first\ngrace,45,2,\nalan,36,3.25,third\n"

METADATA_FIELDS = ("dataset_summary", "column_details")


def convert_url(client, url, query=""):
    """Convert an already-served URL, so the same source can be requested twice."""
    return client.get(f"/convert?source={url}{query}")


def payload_of(client, response):
    """The dataset body behind a `/convert` response's endpoint."""
    return client.get(response.get_json()["endpoint"]).get_json()


def enriched(dataset, body, **serve_kwargs):
    """The dataset body of `body` converted with `enrich=yes`."""
    return dataset(body, query=ENRICH, **serve_kwargs)


# Phrase: "`/convert` supports optional ingestion enrichment with `enrich=yes`."
def test_enrich_yes_is_accepted_by_convert(convert):
    assert convert(SIMPLE_CSV, query=ENRICH).status_code == 200


# Phrase: "Only exact `enrich=yes` enables enrichment."
def test_enrich_yes_enables_enrichment(dataset):
    body = enriched(dataset, SIMPLE_CSV)

    assert body["dataset_summary"]["row_count"] == 2
    assert set(body["column_details"]) == {"name", "age"}


# Phrase: "All other states keep enrichment off." - absent parameter.
def test_absent_enrich_keeps_enrichment_off(dataset):
    body = dataset(SIMPLE_CSV)

    assert not any(field in body for field in METADATA_FIELDS)


# Phrase: "Only exact `enrich=yes` enables enrichment. All other states keep
# enrichment off." - other spellings, values and shapes of the parameter (T73).
@pytest.mark.parametrize(
    "query",
    ["&enrich=YES", "&enrich=Yes", "&enrich=yes%20", "&enrich=1", "&enrich=true",
     "&enrich=on", "&enrich=no", "&enrich=", "&enrich"],
)
def test_other_enrich_states_keep_enrichment_off(dataset, query):
    body = dataset(SIMPLE_CSV, query=query)

    assert not any(field in body for field in METADATA_FIELDS)


# Phrase: "All other states keep enrichment off." - an unrecognised value is
# not a client error, it simply leaves enrichment off (T73).
@pytest.mark.parametrize("query", ["&enrich=maybe", "&enrich=", "&enrich"])
def test_unrecognised_enrich_values_are_not_errors(convert, query):
    assert convert(SIMPLE_CSV, query=query).status_code == 200


# Phrase: "Only exact `enrich=yes` enables enrichment." - with the parameter
# repeated, the first occurrence decides (T73).
def test_repeated_enrich_is_decided_by_the_first_value(dataset):
    assert "dataset_summary" in dataset(SIMPLE_CSV, query="&enrich=yes&enrich=no")
    assert "dataset_summary" not in dataset(SIMPLE_CSV, query="&enrich=no&enrich=yes")


# Phrase: "Success response remains: {"ok": true, "endpoint": "/datasets/<id>"}"
def test_enriched_convert_returns_the_unchanged_success_body(convert):
    body = convert(SIMPLE_CSV, query=ENRICH, path="/enrich-body.csv").get_json()

    assert set(body) == {"ok", "endpoint"}
    assert body["ok"] is True
    assert body["endpoint"].startswith("/datasets/")


# Phrase: "Success response remains" - enrichment does not change which id a
# source maps to, so the same URL keeps its endpoint (T78).
def test_enrichment_does_not_change_the_endpoint(client, origin):
    url = origin.serve("/enrich-same-id.csv", SIMPLE_CSV)

    plain = convert_url(client, url)
    upgraded = convert_url(client, url, ENRICH)

    assert upgraded.get_json()["endpoint"] == plain.get_json()["endpoint"]


# Phrase: "For enriched CSV datasets, add: `dataset_summary` with at least
# `filetype`, `row_count`, `column_count`"
def test_enriched_csv_carries_a_dataset_summary(dataset):
    summary = enriched(dataset, TYPED_CSV)["dataset_summary"]

    assert summary["filetype"] == "csv"
    assert summary["row_count"] == 3
    assert summary["column_count"] == 4


# Phrase: "`row_count`" - the header row is not a data row.
def test_row_count_counts_data_rows_only(dataset):
    summary = enriched(dataset, numbered_csv(7))["dataset_summary"]

    assert summary["row_count"] == 7


# Phrase: "`column_details` keyed by column name with at least `type`,
# `distinct_count`, `missing_count`"
def test_enriched_csv_carries_column_details_keyed_by_name(dataset):
    details = enriched(dataset, TYPED_CSV)["column_details"]

    assert set(details) == {"name", "age", "score", "note"}
    assert details["age"] == {"type": "integer", "distinct_count": 2, "missing_count": 0}


# Phrase: "`missing_count`" - blank cells are the missing ones, and they are
# not counted among the distinct values (T77).
def test_blank_cells_are_missing_and_not_distinct(dataset):
    details = enriched(dataset, TYPED_CSV)["column_details"]

    assert details["note"] == {"type": "text", "distinct_count": 2, "missing_count": 1}


# Phrase: "`missing_count`" - a row shorter than the header is padded, and the
# padding counts as missing.
def test_short_rows_count_as_missing(dataset):
    details = enriched(dataset, "a,b\n1,2\n3\n")["column_details"]

    assert details["b"]["missing_count"] == 1


# Phrase: "Type labels: `text`, `number`, `integer`, `float`." (T76)
@pytest.mark.parametrize(
    "values,label",
    [(["1", "2", "3"], "integer"), (["1.5", "2.0", "0.25"], "float"),
     (["1", "2.5", "3"], "number"), (["ada", "grace", "alan"], "text"),
     (["1", "2", "x"], "text"), (["08:30", "9:15", "12:00"], "text")],
)
def test_column_type_labels(dataset, values, label):
    rows = "".join(f"{value},filler\n" for value in values)
    details = enriched(dataset, f"value,other\n{rows}")["column_details"]

    assert details["value"]["type"] == label


# Phrase: "Type labels: `text`, ..." - a column holding nothing but blanks has
# no values to type, and reads as text (T76).
def test_an_empty_column_is_text(dataset):
    details = enriched(dataset, "a,b\n1,\n2,\n")["column_details"]

    assert details["b"] == {"type": "text", "distinct_count": 0, "missing_count": 2}


# Phrase: "`distinct_count`" - repeated values collapse.
def test_distinct_count_counts_unique_values(dataset):
    details = enriched(dataset, "tag,n\nred,1\nblue,2\nred,3\nred,4\n")["column_details"]

    assert details["tag"] == {"type": "text", "distinct_count": 2, "missing_count": 0}


# Phrase: "For enriched spreadsheet datasets, add only `dataset_summary` with
# `filetype: "excel"`." - xlsx.
def test_enriched_xlsx_carries_only_a_summary(dataset):
    body = enriched(dataset, xlsx_bytes(TEAMS_SHEET), content_type="application/vnd.ms-excel")

    assert body["dataset_summary"]["filetype"] == "excel"
    assert "column_details" not in body


# Phrase: "For enriched spreadsheet datasets, add only `dataset_summary` with
# `filetype: "excel"`." - legacy xls.
def test_enriched_xls_carries_only_a_summary(dataset):
    body = enriched(dataset, xls_bytes(TEAMS_SHEET), content_type="application/vnd.ms-excel")

    assert body["dataset_summary"]["filetype"] == "excel"
    assert "column_details" not in body


# Phrase: "add only `dataset_summary`" - the summary keeps the shape it has for
# CSV, counts included (T75).
def test_the_spreadsheet_summary_counts_rows_and_columns(dataset):
    body = enriched(dataset, xlsx_bytes(TEAMS_SHEET), content_type="application/vnd.ms-excel")

    assert body["dataset_summary"] == {"filetype": "excel", "row_count": 4, "column_count": 3}


# Phrase: "Non-enriched responses omit both metadata fields (no `null`/empty
# objects)."
def test_non_enriched_responses_omit_both_fields(endpoint):
    body = endpoint(TYPED_CSV)().get_json()

    assert "dataset_summary" not in body
    assert "column_details" not in body


# Phrase: "`rows`, `columns`, `ok`, `query_ms`, and `total` do not change."
def test_enrichment_leaves_the_rest_of_the_body_unchanged(client, origin):
    plain = payload_of(client, convert_url(client, origin.serve("/enrich-plain.csv", TYPED_CSV)))
    rich = payload_of(client, convert_url(client, origin.serve("/enrich-rich.csv", TYPED_CSV), ENRICH))

    assert {key: rich[key] for key in ("ok", "columns", "rows", "total")} == {
        key: plain[key] for key in ("ok", "columns", "rows", "total")
    }
    assert isinstance(rich["query_ms"], (int, float))


# Phrase: "`rows`, `columns`, ... do not change." - the controls and filters of
# an enriched dataset behave exactly as before.
def test_controls_still_apply_to_an_enriched_dataset(dataset):
    body = dataset(TYPED_CSV, query=ENRICH, dataset_query="?age__exact=36&_size=1")

    assert body["rows"] == [["ada", 36, 1.5, "first"]]
    assert body["total"] == 2


# Phrase: "`dataset_summary` with at least ... `row_count`" - the summary
# describes the dataset, not the filtered page (T80).
def test_the_summary_ignores_filtering_and_pagination(dataset):
    body = dataset(TYPED_CSV, query=ENRICH, dataset_query="?age__exact=45&_size=1")

    assert body["dataset_summary"]["row_count"] == 3
    assert body["total"] == 1


# Phrase: "`enrich=yes` on a cached non-enriched dataset forces re-ingestion
# and upgrades stored state."
def test_enrich_on_a_cached_plain_dataset_re_ingests(client, origin):
    url = origin.serve("/enrich-upgrade.csv", SIMPLE_CSV)
    convert_url(client, url)
    downloads = origin.hits("/enrich-upgrade.csv")

    upgraded = convert_url(client, url, ENRICH)

    assert origin.hits("/enrich-upgrade.csv") == downloads + 1
    assert "dataset_summary" in payload_of(client, upgraded)


# Phrase: "upgrades stored state." - the upgrade is stored, so a later plain
# query still sees the metadata.
def test_the_upgrade_is_stored(client, origin):
    url = origin.serve("/enrich-stored.csv", SIMPLE_CSV)
    convert_url(client, url)
    convert_url(client, url, ENRICH)

    assert "dataset_summary" in payload_of(client, convert_url(client, url))


# Phrase: "`enrich=yes` on a cached enriched dataset may use cache." - the
# second enriching request answers from the store (T-choice: it does).
def test_enrich_on_a_cached_enriched_dataset_uses_the_cache(client, origin):
    url = origin.serve("/enrich-cached.csv", SIMPLE_CSV)
    convert_url(client, url, ENRICH)
    downloads = origin.hits("/enrich-cached.csv")

    repeated = convert_url(client, url, ENRICH)

    assert origin.hits("/enrich-cached.csv") == downloads
    assert "dataset_summary" in payload_of(client, repeated)


# Phrase: "Requests without re-ingestion do not change stored enrichment
# state." - a plain cache hit leaves an enriched dataset enriched.
def test_a_plain_cache_hit_keeps_the_stored_enrichment(client, origin):
    url = origin.serve("/enrich-keep.csv", SIMPLE_CSV)
    convert_url(client, url, ENRICH)

    plain = convert_url(client, url)

    assert origin.hits("/enrich-keep.csv") == 1
    assert "dataset_summary" in payload_of(client, plain)


# Phrase: "Requests without re-ingestion do not change stored enrichment
# state." - a plain cache hit on a plain dataset does not enrich it either.
def test_a_plain_cache_hit_keeps_a_plain_dataset_plain(client, origin):
    url = origin.serve("/enrich-plain-hit.csv", SIMPLE_CSV)
    convert_url(client, url)

    assert "dataset_summary" not in payload_of(client, convert_url(client, url))


# Phrase: "Re-ingestion recomputes metadata from current source bytes." - a
# forced enriching re-ingestion picks up the replaced body.
def test_forced_re_ingestion_recomputes_the_metadata(client, origin):
    url = origin.serve("/enrich-recompute.csv", SIMPLE_CSV)
    convert_url(client, url, ENRICH)
    origin.serve("/enrich-recompute.csv", "a,b,c\n1,2,3\n4,5,6\n7,8,9\n")

    refreshed = convert_url(client, url, ENRICH + "&force")

    assert payload_of(client, refreshed)["dataset_summary"] == {
        "filetype": "csv",
        "row_count": 3,
        "column_count": 3,
    }


# Phrase: "Re-ingestion recomputes metadata from current source bytes." - with
# caching off every request re-ingests, so the metadata follows the source.
def test_re_ingestion_with_caching_off_recomputes_the_metadata(cached_client, origin):
    client = cached_client("off")
    url = origin.serve("/enrich-nocache.csv", SIMPLE_CSV)
    convert_url(client, url, ENRICH)
    origin.serve("/enrich-nocache.csv", "a,b\n1,2\n3,4\n5,6\n")

    assert payload_of(client, convert_url(client, url, ENRICH))["dataset_summary"]["row_count"] == 3


# Phrase: "Requests without re-ingestion do not change stored enrichment
# state." - a request that *does* re-ingest stores what it asked for, so a
# forced plain re-ingestion drops the metadata (T78).
def test_forced_plain_re_ingestion_downgrades_the_stored_dataset(client, origin):
    url = origin.serve("/enrich-downgrade.csv", SIMPLE_CSV)
    convert_url(client, url, ENRICH)

    convert_url(client, url, "&force")

    assert "dataset_summary" not in payload_of(client, convert_url(client, url))


# Phrase: "`enrich` applies only on `/convert`." - the dataset endpoint ignores
# it (T79).
def test_enrich_is_ignored_on_the_dataset_endpoint(endpoint):
    response = endpoint(SIMPLE_CSV)("?enrich=yes")

    assert response.status_code == 200
    assert "dataset_summary" not in response.get_json()


# Phrase: "`enrich` applies only on `/convert`." - an upload is never enriched
# (T79).
def test_enrich_is_ignored_on_upload(client):
    response = client.post(
        "/upload?enrich=yes",
        data={"file": (io.BytesIO(SIMPLE_CSV.encode()), "data.csv")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    body = client.get(response.get_json()["endpoint"]).get_json()
    assert "dataset_summary" not in body


# Phrase: "Enrichment failures return standard JSON errors" - an enriching
# request whose source is unreachable keeps the ingestion status and envelope.
def test_enriching_an_unreachable_source_returns_the_standard_error(client, origin):
    response = convert_url(client, origin.url_for("/enrich-missing.csv"), ENRICH)

    assert response.status_code == 404
    assert response.get_json()["ok"] is False


# Phrase: "Enrichment failures return standard JSON errors" - a non-tabular
# source is still a 400 when enrichment is asked for.
def test_enriching_a_non_tabular_source_is_still_a_client_error(convert):
    response = convert("{\"not\": \"a table\"}", query=ENRICH)

    assert response.status_code == 400
    assert response.get_json()["ok"] is False


# Phrase: "must not downgrade to non-enriched storage." - a failed enriching
# re-ingestion leaves the stored enriched dataset untouched.
def test_a_failed_enriching_re_ingestion_keeps_the_enriched_dataset(client, origin):
    url = origin.serve("/enrich-fail.csv", SIMPLE_CSV)
    convert_url(client, url, ENRICH)
    origin.serve("/enrich-fail.csv", "not a table at all")

    assert convert_url(client, url, ENRICH + "&force").status_code == 400

    body = payload_of(client, convert_url(client, url, ENRICH))
    assert body["dataset_summary"]["row_count"] == 2
    assert body["rows"] == [["ada", 36], ["grace", 45]]


# Phrase: "must not downgrade to non-enriched storage." - the same holds when
# the enriching request is the one that would have created the dataset.
def test_a_failed_first_enrichment_stores_nothing(client, origin):
    url = origin.serve("/enrich-first-fail.csv", "not a table at all")

    response = convert_url(client, url, ENRICH)

    assert response.status_code == 400
    assert client.get(f"/datasets/{dataset_id(url)}").status_code == 404
