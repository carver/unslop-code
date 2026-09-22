"""Optional ingestion enrichment: `/convert?enrich=yes` and the metadata it adds.

Each test serves its CSV at a path of its own, so the session-wide origin's hit
counter for that path counts only this test's downloads.
"""

CSV = "name,age\nada,36\ngrace,45\n"
SECOND = "name,age\nada,36\ngrace,45\nlin,29\n"
ENRICHED = {"enrich": "yes"}


def convert(client, source, **params):
    """GET /convert for `source`; a list value repeats the parameter."""
    return client.get("/convert", query_string={"source": source, **params})


def read(client, endpoint, **query):
    return client.get(endpoint, query_string=query).get_json()


def without_timing(payload):
    """A response payload minus the field that differs between two reads."""
    return {name: value for name, value in payload.items() if name != "query_ms"}


def endpoint_of(client, source, **params):
    return convert(client, source, **params).get_json()["endpoint"]


# Spec: "`/convert` supports optional ingestion enrichment with `enrich=yes`."
# Context: the flag is accepted on the ingestion route and the conversion
# succeeds exactly as it does without it.
def test_enrich_is_accepted_on_convert(client, origin):
    source = origin.serve("/enrich-accepted.csv", CSV)
    plain = convert(client, source).get_json()
    enriched = convert(client, source, **ENRICHED, force="")
    assert enriched.status_code == 200
    assert enriched.get_json() == plain


# Spec: "Success response remains: {"ok": true, "endpoint": "/datasets/<id>"}"
# Context: an enriched conversion carries no extra envelope fields — the
# metadata belongs to the query response, not this one.
def test_success_envelope_is_unchanged_by_enrichment(client, origin):
    source = origin.serve("/enrich-envelope.csv", CSV)
    body = convert(client, source, **ENRICHED).get_json()
    assert set(body) == {"ok", "endpoint"}
    assert body["ok"] is True
    assert body["endpoint"].startswith("/datasets/")


# Spec: "Only a single, exact `enrich=yes` enables enrichment."
# Context: the exact token, given once, is what turns the metadata on.
def test_exact_enrich_yes_enables_enrichment(client, origin):
    source = origin.serve("/enrich-exact.csv", CSV)
    payload = read(client, endpoint_of(client, source, **ENRICHED))
    assert "dataset_summary" in payload
    assert "column_details" in payload


# Spec: "All other states keep enrichment off."
# Context: near-misses on the value — case, padding, other spellings of yes,
# and an empty value — leave the dataset non-enriched (AMBIGUITIES T72).
def test_other_enrich_values_keep_enrichment_off(client, origin):
    values = ["YES", "Yes", "yEs", " yes", "yes ", "1", "true", "on", "no", "y", ""]
    for index, value in enumerate(values):
        source = origin.serve(f"/enrich-off-{index}.csv", CSV)
        payload = read(client, endpoint_of(client, source, enrich=value))
        assert "dataset_summary" not in payload, value
        assert "column_details" not in payload, value


# Spec: "All other states keep enrichment off."
# Context: the parameter absent altogether.
def test_an_absent_enrich_keeps_enrichment_off(client, origin):
    source = origin.serve("/enrich-absent.csv", CSV)
    assert "column_details" not in read(client, endpoint_of(client, source))


# Spec: "All other states keep enrichment off."
# Context: a value the flag does not recognise is not a caller error; the
# conversion succeeds, unenriched (AMBIGUITIES T72).
def test_an_unrecognised_enrich_value_is_not_an_error(client, origin):
    source = origin.serve("/enrich-not-an-error.csv", CSV)
    assert convert(client, source, enrich="maybe").status_code == 200
    assert convert(client, source, enrich="", force="").status_code == 200


# Spec: "Only a single, exact `enrich=yes` enables enrichment."
# Context: the parameter repeated is no longer a single one, so enrichment
# stays off and the request still succeeds (AMBIGUITIES T73).
def test_repeated_enrich_keeps_enrichment_off(client, origin):
    source = origin.serve("/enrich-repeated.csv", CSV)
    response = convert(client, source, enrich=["yes", "yes"])
    assert response.status_code == 200
    assert "dataset_summary" not in read(client, response.get_json()["endpoint"])


# Spec: "For enriched CSV datasets, add: `dataset_summary` with at least
# `filetype`, `row_count`, `column_count`"
# Context: a two-column CSV with two data rows; the header is not a row
# (AMBIGUITIES T74).
def test_dataset_summary_of_a_csv(client, origin):
    source = origin.serve("/enrich-summary.csv", CSV)
    summary = read(client, endpoint_of(client, source, **ENRICHED))["dataset_summary"]
    assert summary["filetype"] == "csv"
    assert summary["row_count"] == 2
    assert summary["column_count"] == 2


# Spec: "`column_details` keyed by column name with at least `type`,
# `distinct_count`, `missing_count`"
# Context: every column of the dataset is described, under its own name.
def test_column_details_are_keyed_by_column_name(client, origin):
    source = origin.serve("/enrich-columns.csv", CSV)
    payload = read(client, endpoint_of(client, source, **ENRICHED))
    details = payload["column_details"]
    assert set(details) == set(payload["columns"]) == {"name", "age"}
    for column in details.values():
        assert {"type", "distinct_count", "missing_count"} <= set(column)


# Spec: "`column_details` ... `distinct_count`, `missing_count`"
# Context: a column with a repeat and a column with a hole, including a row
# short enough to be padded out (AMBIGUITIES T78, T79).
def test_distinct_and_missing_counts(client, origin):
    body = "city,note\nmalmo,a\nmalmo,\noslo,  \nlund\n"
    source = origin.serve("/enrich-counts.csv", body)
    details = read(client, endpoint_of(client, source, **ENRICHED))["column_details"]
    assert details["city"] == {"type": "text", "distinct_count": 3, "missing_count": 0}
    assert details["note"]["missing_count"] == 3
    assert details["note"]["distinct_count"] == 1


# Spec: "Type labels: `text`, `number`, `integer`, `float`."
# Context: one column per label — whole numbers, fractions, the two mixed, and
# a column holding anything non-numeric (AMBIGUITIES T76).
def test_the_four_type_labels(client, origin):
    body = "whole,fraction,mixed,words,coded\n1,1.5,1,ada,08:30\n2,2.5,2.5,grace,9:15\n"
    source = origin.serve("/enrich-types.csv", body)
    details = read(client, endpoint_of(client, source, **ENRICHED))["column_details"]
    assert details["whole"]["type"] == "integer"
    assert details["fraction"]["type"] == "float"
    assert details["mixed"]["type"] == "number"
    assert details["words"]["type"] == "text"
    assert details["coded"]["type"] == "text"


# Spec: "Type labels: `text`, `number`, `integer`, `float`."
# Context: a blank cell says nothing about the column's type, and a column with
# no values at all falls back to `text`. A wholly blank record is not a row at
# all, so every row here carries something (AMBIGUITIES T77).
def test_blanks_do_not_change_a_column_type(client, origin):
    body = "age,note,empty\n36,,\n,x,\n45,,\n"
    source = origin.serve("/enrich-blank-types.csv", body)
    details = read(client, endpoint_of(client, source, **ENRICHED))["column_details"]
    assert details["age"] == {"type": "integer", "distinct_count": 2, "missing_count": 1}
    assert details["note"] == {"type": "text", "distinct_count": 1, "missing_count": 2}
    assert details["empty"] == {"type": "text", "distinct_count": 0, "missing_count": 3}


# Spec: "`dataset_summary` with at least ... `row_count`, `column_count`"
# Context: rows are squared off to the header's width, and the counts describe
# the dataset as it is served, not the source text.
def test_counts_describe_the_stored_table(client, origin):
    body = "a,b,c\n1,2,3,4\n5,6\n"
    source = origin.serve("/enrich-ragged.csv", body)
    payload = read(client, endpoint_of(client, source, **ENRICHED))
    assert payload["dataset_summary"]["column_count"] == len(payload["columns"]) == 3
    assert payload["dataset_summary"]["row_count"] == 2


# Spec: "For enriched spreadsheet datasets, add only `dataset_summary` with
# `filetype: "excel"`."
# Context: both workbook formats, fetched through /convert (AMBIGUITIES T75).
def test_enriched_workbooks_carry_only_a_summary(client, origin, xlsx, xls):
    rows = [["name", "age"], ["ada", 36], ["grace", 45]]
    for label, book in (("xlsx", xlsx(rows)), ("xls", xls(rows))):
        source = origin.serve(f"/enrich-{label}", book, content_type="application/octet-stream")
        payload = read(client, endpoint_of(client, source, **ENRICHED))
        assert payload["dataset_summary"]["filetype"] == "excel", label
        assert payload["dataset_summary"]["row_count"] == 2, label
        assert payload["dataset_summary"]["column_count"] == 2, label
        assert "column_details" not in payload, label


# Spec: "Non-enriched responses omit both metadata fields (no `null`/empty
# objects)."
# Context: a conversion that did not ask for enrichment, for a CSV and for a
# workbook.
def test_non_enriched_responses_omit_the_metadata(client, origin, xlsx):
    book = xlsx([["name", "age"], ["ada", 36]])
    sources = [
        origin.serve("/plain-table.csv", CSV),
        origin.serve("/plain-book.xlsx", book, content_type="application/octet-stream"),
    ]
    for source in sources:
        payload = read(client, endpoint_of(client, source))
        assert "dataset_summary" not in payload, source
        assert "column_details" not in payload, source


# Spec: "`rows`, `columns`, `ok`, `query_ms`, and `total` do not change."
# Context: the same dataset read enriched and non-enriched, with the controls
# that vary the shape of those fields.
def test_enrichment_does_not_disturb_the_other_fields(client, origin):
    body = "name,age\nada,36\ngrace,45\nlin,29\n"
    plain = origin.serve("/enrich-untouched-plain.csv", body)
    enriched = origin.serve("/enrich-untouched-rich.csv", body)
    query = {"_shape": "objects", "_size": "2", "_sort": "age", "age__greater": "20"}
    before = read(client, endpoint_of(client, plain), **query)
    after = read(client, endpoint_of(client, enriched, **ENRICHED), **query)

    assert set(after) - set(before) == {"dataset_summary", "column_details"}
    assert isinstance(after["query_ms"], float)
    for field in ("ok", "columns", "rows", "total"):
        assert after[field] == before[field], field


# Spec: "`enrich=yes` on a cached non-enriched dataset forces re-ingestion and
# upgrades stored state."
# Context: a source converted plainly, then asked for enrichment — the second
# request downloads again, and the stored dataset is enriched afterwards.
def test_enrich_upgrades_a_cached_non_enriched_dataset(client, origin):
    source = origin.serve("/enrich-upgrade.csv", CSV)
    endpoint = endpoint_of(client, source)
    assert "dataset_summary" not in read(client, endpoint)

    assert endpoint_of(client, source, **ENRICHED) == endpoint
    assert origin.hits["/enrich-upgrade.csv"] == 2
    assert read(client, endpoint)["dataset_summary"]["row_count"] == 2


# Spec: "`enrich=yes` on a cached enriched dataset may use cache."
# Context: a second enriched request for an already enriched source is served
# from the store without re-downloading (AMBIGUITIES T83).
def test_enrich_on_an_enriched_dataset_uses_the_cache(client, origin):
    source = origin.serve("/enrich-cached.csv", CSV)
    first = convert(client, source, **ENRICHED).get_json()
    second = convert(client, source, **ENRICHED)
    assert second.get_json() == first
    assert origin.hits["/enrich-cached.csv"] == 1
    assert read(client, first["endpoint"])["dataset_summary"]["row_count"] == 2


# Spec: "Requests without re-ingestion do not change stored enrichment state."
# Context: a plain request that hits the cache leaves an enriched dataset
# enriched.
def test_a_cache_hit_keeps_a_dataset_enriched(client, origin):
    source = origin.serve("/enrich-keep-on.csv", CSV)
    endpoint = endpoint_of(client, source, **ENRICHED)
    assert convert(client, source).get_json()["endpoint"] == endpoint
    assert origin.hits["/enrich-keep-on.csv"] == 1
    assert "dataset_summary" in read(client, endpoint)


# Spec: "Requests without re-ingestion do not change stored enrichment state."
# Context: the mirror case — a cache hit on a non-enriched dataset does not
# enrich it.
def test_a_cache_hit_keeps_a_dataset_non_enriched(client, origin):
    source = origin.serve("/enrich-keep-off.csv", CSV)
    endpoint = endpoint_of(client, source)
    convert(client, source)
    assert origin.hits["/enrich-keep-off.csv"] == 1
    assert "dataset_summary" not in read(client, endpoint)


# Spec: "`enrich=yes` on a cached non-enriched dataset forces re-ingestion"
# Context: a re-ingestion that does not ask for enrichment stores the dataset
# as the request describes it, so the metadata goes away (AMBIGUITIES T81).
def test_a_forced_plain_reingestion_downgrades(client, origin):
    source = origin.serve("/enrich-downgrade.csv", CSV)
    endpoint = endpoint_of(client, source, **ENRICHED)
    convert(client, source, force="")
    assert origin.hits["/enrich-downgrade.csv"] == 2
    assert "dataset_summary" not in read(client, endpoint)


# Spec: "Re-ingestion recomputes metadata from current source bytes."
# Context: the remote body grows between two enriched conversions, and the
# forced re-ingestion reports the new shape.
def test_reingestion_recomputes_the_metadata(client, origin):
    source = origin.serve("/enrich-recompute.csv", CSV)
    endpoint = endpoint_of(client, source, **ENRICHED)
    assert read(client, endpoint)["dataset_summary"]["row_count"] == 2

    origin.serve("/enrich-recompute.csv", SECOND)
    convert(client, source, **ENRICHED, force="")
    assert read(client, endpoint)["dataset_summary"]["row_count"] == 3


# Spec: "Re-ingestion recomputes metadata from current source bytes." /
# "`enrich=yes` on a cached non-enriched dataset forces re-ingestion"
# Context: the upgrade of a stale cached dataset reads the bytes as they are
# now, not the ones the first conversion stored.
def test_the_upgrade_reads_the_current_bytes(client, origin):
    source = origin.serve("/enrich-stale.csv", CSV)
    endpoint = endpoint_of(client, source)
    origin.serve("/enrich-stale.csv", SECOND)
    convert(client, source, **ENRICHED)
    payload = read(client, endpoint)
    assert payload["dataset_summary"]["row_count"] == 3
    assert payload["column_details"]["name"]["distinct_count"] == 3


# Spec: "Re-ingestion recomputes metadata from current source bytes."
# Context: with caching off every request re-ingests, so every enriched request
# carries metadata computed afresh.
def test_metadata_is_recomputed_when_caching_is_off(configured_client, origin):
    client = configured_client("off")
    source = origin.serve("/enrich-uncached.csv", CSV)
    endpoint = endpoint_of(client, source, **ENRICHED)
    origin.serve("/enrich-uncached.csv", SECOND)
    convert(client, source, **ENRICHED)
    assert origin.hits["/enrich-uncached.csv"] == 2
    assert read(client, endpoint)["dataset_summary"]["row_count"] == 3


# Spec: "`enrich` applies only on `/convert`."
# Context: an upload naming the flag ingests as an ordinary upload
# (AMBIGUITIES T82).
def test_upload_ignores_enrich(upload, client):
    response = upload(CSV, params={"enrich": "yes"})
    assert response.status_code == 200
    assert "dataset_summary" not in read(client, response.get_json()["endpoint"])


# Spec: "`enrich` applies only on `/convert`."
# Context: the flag on a dataset read neither enriches the response nor is
# rejected as an unknown parameter (AMBIGUITIES T82).
def test_the_dataset_route_ignores_enrich(client, origin):
    source = origin.serve("/enrich-read-only.csv", CSV)
    endpoint = endpoint_of(client, source)
    response = client.get(endpoint, query_string={"enrich": "yes"})
    assert response.status_code == 200
    assert without_timing(response.get_json()) == without_timing(read(client, endpoint))


# Spec: "`enrich` applies only on `/convert`."
# Context: the export of an enriched dataset is still just the source columns
# and rows.
def test_export_is_unaffected_by_enrichment(client, origin):
    source = origin.serve("/enrich-export.csv", CSV)
    endpoint = endpoint_of(client, source, **ENRICHED)
    body = client.get(f"{endpoint}/export").get_data(as_text=True)
    assert body.splitlines() == ["name,age", "ada,36", "grace,45"]


# Spec: "Enrichment failures return standard JSON errors and must not downgrade
# to non-enriched storage."
# Context: an enriched re-ingestion whose source has since broken — the error
# keeps its status and envelope, and the stored dataset stays enriched
# (AMBIGUITIES T84).
def test_a_failed_enriched_reingestion_keeps_the_stored_metadata(client, origin):
    source = origin.serve("/enrich-failure.csv", CSV)
    endpoint = endpoint_of(client, source, **ENRICHED)
    origin.serve("/enrich-failure.csv", b"<html>not a table</html>")

    response = convert(client, source, **ENRICHED, force="")
    assert response.status_code == 400
    assert set(response.get_json()) == {"ok", "error"}
    assert response.get_json()["ok"] is False
    assert read(client, endpoint)["dataset_summary"]["row_count"] == 2


# Spec: "Enrichment failures return standard JSON errors and must not downgrade
# to non-enriched storage."
# Context: the same guarantee when the failure is the download rather than the
# content, and when caching is off so the request re-ingests unasked.
def test_an_unreachable_enriched_reingestion_keeps_the_stored_metadata(
    configured_client, origin
):
    client = configured_client("no")
    source = origin.serve("/enrich-failure-http.csv", CSV)
    endpoint = endpoint_of(client, source, **ENRICHED)
    origin.serve("/enrich-failure-http.csv", CSV, status=500)

    response = convert(client, source, **ENRICHED)
    assert response.status_code == 404
    assert response.get_json()["ok"] is False
    assert "dataset_summary" in read(client, endpoint)


# Spec: "Enrichment failures return standard JSON errors"
# Context: a failure while computing the metadata is reported through the same
# envelope, and leaves nothing stored (AMBIGUITIES T84).
def test_a_metadata_failure_is_a_json_error(client, origin, monkeypatch):
    from gateway import ingestion

    def explode(_table):
        raise ArithmeticError("boom")

    monkeypatch.setattr(ingestion, "describe", explode)
    source = origin.serve("/enrich-metadata-failure.csv", CSV)
    response = convert(client, source, **ENRICHED)
    assert response.status_code == 500
    assert response.get_json()["ok"] is False
    assert set(response.get_json()) == {"ok", "error"}

    monkeypatch.undo()
    assert "dataset_summary" in read(client, endpoint_of(client, source, **ENRICHED))
    assert origin.hits["/enrich-metadata-failure.csv"] == 2
