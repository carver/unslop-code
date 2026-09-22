"""Spec section: Optional Dataset Enrichment."""
from urllib.parse import quote

import pytest

from conftest import (
    assert_error_envelope,
    convert_ok,
    free_port,
    read_csv_text,
    upload_ok,
    xls_bytes,
    xlsx_bytes,
)

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLS_CT = "application/vnd.ms-excel"

SIMPLE = "name,age\nAlice,30\nBob,41\n"

# name: text, 2 distinct, 0 missing        age: integer, 2 distinct, 1 missing
# score: float, 3 distinct, 0 missing      note: text, 2 distinct, 1 missing
PROFILE = (
    "name,age,score,note\n"
    "Alice,30,1.5,x\n"
    "Bob,41,2.0,\n"
    "Alice,,3.25,y\n"
)

PEOPLE_ROWS = [["name", "age", "city"], ["Ada", 36, "London"], ["Grace", 45, "NYC"]]


def raw_convert(gate, source, extra=""):
    """GET /convert with a hand-built query string (presence flags need one)."""
    query = "source=" + quote(source, safe="")
    if extra:
        query += "&" + extra
    return gate.get("/convert?" + query)


def enrich_ok(gate, source, **params):
    """Convert with enrichment on; return the dataset endpoint."""
    return convert_ok(gate, source, enrich="yes", **params)


def query(gate, endpoint, **params):
    resp = gate.get(endpoint, params=params or None)
    assert resp.status_code == 200, resp.text
    return resp.json()


def enriched_payload(gate, origin, path, body, **params):
    """Register a source, convert it with enrichment, and query it."""
    url = origin.add(path, body, **params)
    return query(gate, enrich_ok(gate, url))


# ---------------------------------------------------------------------------
# Phrase: "`/convert` supports optional ingestion enrichment with `enrich=yes`."
# Context: the enrichment trigger is a /convert query parameter.
# ---------------------------------------------------------------------------
def test_convert_accepts_enrich_yes(gate, origin):
    url = origin.add("/enr-accept.csv", SIMPLE)
    resp = gate.convert(source=url, enrich="yes")
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


def test_enrich_is_optional(gate, origin):
    url = origin.add("/enr-optional.csv", SIMPLE)
    resp = gate.convert(source=url)
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# Phrase: "Only a single, exact `enrich=yes` enables enrichment."
# Context: exactly one occurrence, spelled exactly `yes`, turns enrichment on.
# ---------------------------------------------------------------------------
def test_single_exact_enrich_yes_enables_enrichment(gate, origin):
    url = origin.add("/enr-on.csv", SIMPLE)
    payload = query(gate, enrich_ok(gate, url))
    assert "dataset_summary" in payload
    assert "column_details" in payload


# ---------------------------------------------------------------------------
# Phrase: "All other states keep enrichment off."
# Context: any value other than the exact string `yes`.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value",
    ["YES", "Yes", "yEs", "yes ", " yes", "y", "no", "1", "true", "on", "", "yess"],
)
def test_other_enrich_values_keep_enrichment_off(gate, origin, value):
    url = origin.add(f"/enr-off-{abs(hash(value))}.csv", SIMPLE)
    resp = gate.convert(source=url, enrich=value)
    assert resp.status_code == 200, resp.text
    payload = query(gate, resp.json()["endpoint"])
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


# ---------------------------------------------------------------------------
# Phrase: "All other states keep enrichment off." (absent / valueless forms)
# Context: `enrich` omitted entirely, or present with no `=` at all.
# ---------------------------------------------------------------------------
def test_absent_enrich_keeps_enrichment_off(gate, origin):
    url = origin.add("/enr-absent.csv", SIMPLE)
    payload = query(gate, convert_ok(gate, url))
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


def test_bare_enrich_flag_keeps_enrichment_off(gate, origin):
    url = origin.add("/enr-bare.csv", SIMPLE)
    resp = raw_convert(gate, url, "enrich")
    assert resp.status_code == 200, resp.text
    payload = query(gate, resp.json()["endpoint"])
    assert "dataset_summary" not in payload


# ---------------------------------------------------------------------------
# Phrase: "Only a *single* ... `enrich=yes`" (repeats are another state)
# Context: the parameter given more than once, however it is spelled.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "extra",
    ["enrich=yes&enrich=yes", "enrich=yes&enrich=no", "enrich=no&enrich=yes"],
)
def test_repeated_enrich_keeps_enrichment_off(gate, origin, extra):
    url = origin.add(f"/enr-rep-{abs(hash(extra))}.csv", SIMPLE)
    resp = raw_convert(gate, url, extra)
    assert resp.status_code == 200, resp.text
    payload = query(gate, resp.json()["endpoint"])
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


# ---------------------------------------------------------------------------
# Phrase: 'Success response remains: {"ok": true, "endpoint": "/datasets/<id>"}'
# Context: enrichment does not change the /convert envelope.
# ---------------------------------------------------------------------------
def test_enriched_convert_envelope_is_unchanged(gate, origin):
    url = origin.add("/enr-envelope.csv", SIMPLE)
    resp = gate.convert(source=url, enrich="yes")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"ok", "endpoint"}
    assert body["ok"] is True
    assert body["endpoint"].startswith("/datasets/")
    assert body["endpoint"] != "/datasets/"


def test_enrich_does_not_change_the_endpoint_for_a_source(gate, origin):
    url = origin.add("/enr-same-endpoint.csv", SIMPLE)
    plain = convert_ok(gate, url)
    assert enrich_ok(gate, url) == plain


# ---------------------------------------------------------------------------
# Phrase: "For enriched CSV datasets, add: `dataset_summary` with at least
#          `filetype`, `row_count`, `column_count`"
# Context: GET /datasets/<id> for a dataset converted with enrich=yes.
# ---------------------------------------------------------------------------
def test_enriched_csv_has_dataset_summary(gate, origin):
    payload = enriched_payload(gate, origin, "/enr-summary.csv", PROFILE)
    summary = payload["dataset_summary"]
    assert isinstance(summary, dict)
    assert {"filetype", "row_count", "column_count"} <= set(summary)


def test_enriched_csv_summary_filetype_is_csv(gate, origin):
    payload = enriched_payload(gate, origin, "/enr-filetype.csv", PROFILE)
    assert payload["dataset_summary"]["filetype"] == "csv"


def test_enriched_csv_summary_counts_the_stored_table(gate, origin):
    payload = enriched_payload(gate, origin, "/enr-counts.csv", PROFILE)
    summary = payload["dataset_summary"]
    assert summary["row_count"] == 3       # data rows, header excluded (T82)
    assert summary["column_count"] == 4
    assert summary["row_count"] == len(payload["rows"])
    assert summary["column_count"] == len(payload["columns"])


# ---------------------------------------------------------------------------
# Phrase: "`dataset_summary` ... `row_count`" (a dataset-level fact)
# Context: the summary describes the dataset, not the current query window.
# ---------------------------------------------------------------------------
def test_summary_counts_ignore_filtering_and_pagination(gate, origin):
    url = origin.add("/enr-window.csv", PROFILE)
    endpoint = enrich_ok(gate, url)
    payload = query(gate, endpoint, _size=1, name__exact="Bob")
    assert len(payload["rows"]) == 1
    assert payload["dataset_summary"]["row_count"] == 3
    assert payload["dataset_summary"]["column_count"] == 4


# ---------------------------------------------------------------------------
# Phrase: "`column_details` keyed by column name with at least `type`,
#          `distinct_count`, `missing_count`"
# Context: one entry per column of an enriched CSV dataset.
# ---------------------------------------------------------------------------
def test_column_details_are_keyed_by_column_name(gate, origin):
    payload = enriched_payload(gate, origin, "/enr-details-keys.csv", PROFILE)
    details = payload["column_details"]
    assert isinstance(details, dict)
    assert list(details) == payload["columns"] or set(details) == set(payload["columns"])


def test_column_details_entries_have_the_required_keys(gate, origin):
    payload = enriched_payload(gate, origin, "/enr-details-shape.csv", PROFILE)
    for name, entry in payload["column_details"].items():
        assert isinstance(entry, dict), name
        assert {"type", "distinct_count", "missing_count"} <= set(entry), name


def test_missing_count_counts_empty_cells(gate, origin):
    payload = enriched_payload(gate, origin, "/enr-missing.csv", PROFILE)
    details = payload["column_details"]
    assert details["name"]["missing_count"] == 0
    assert details["age"]["missing_count"] == 1
    assert details["score"]["missing_count"] == 0
    assert details["note"]["missing_count"] == 1


def test_distinct_count_counts_distinct_values(gate, origin):
    payload = enriched_payload(gate, origin, "/enr-distinct.csv", PROFILE)
    details = payload["column_details"]
    assert details["name"]["distinct_count"] == 2   # Alice, Bob
    assert details["score"]["distinct_count"] == 3  # 1.5, 2.0, 3.25
    # Missing cells are not a distinct value (T75).
    assert details["age"]["distinct_count"] == 2    # 30, 41
    assert details["note"]["distinct_count"] == 2   # x, y


# ---------------------------------------------------------------------------
# Phrase: "Type labels: `text`, `number`, `integer`, `float`."
# Context: the `type` of each column_details entry.
# ---------------------------------------------------------------------------
def test_type_labels_come_from_the_documented_set(gate, origin):
    payload = enriched_payload(gate, origin, "/enr-labels.csv", PROFILE)
    for entry in payload["column_details"].values():
        assert entry["type"] in ("text", "number", "integer", "float")


def test_text_and_integer_and_float_labels(gate, origin):
    payload = enriched_payload(gate, origin, "/enr-types.csv", PROFILE)
    details = payload["column_details"]
    assert details["name"]["type"] == "text"
    assert details["age"]["type"] == "integer"     # blanks do not demote (T76)
    assert details["score"]["type"] == "float"
    assert details["note"]["type"] == "text"


def test_mixed_integer_and_float_column_is_number(gate, origin):
    body = "qty\n1\n2.5\n3\n"
    payload = enriched_payload(gate, origin, "/enr-number.csv", body)
    assert payload["column_details"]["qty"]["type"] == "number"


def test_all_blank_column_is_text(gate, origin):
    body = "a,b\n1,\n2,\n"
    payload = enriched_payload(gate, origin, "/enr-blank-col.csv", body)
    details = payload["column_details"]
    assert details["a"]["type"] == "integer"
    assert details["b"]["type"] == "text"
    assert details["b"]["missing_count"] == 2
    assert details["b"]["distinct_count"] == 0


# ---------------------------------------------------------------------------
# Phrase: "For enriched spreadsheet datasets, add only `dataset_summary` with
#          `filetype: \"excel\"`."
# Context: .xlsx and .xls sources converted with enrich=yes.
# ---------------------------------------------------------------------------
def test_enriched_xlsx_summary_filetype_is_excel(gate, origin):
    data = xlsx_bytes([("Sheet1", PEOPLE_ROWS)])
    url = origin.add("/enr-book.xlsx", data, content_type=XLSX_CT)
    payload = query(gate, enrich_ok(gate, url))
    assert payload["dataset_summary"]["filetype"] == "excel"


def test_enriched_xls_summary_filetype_is_excel(gate, origin):
    data = xls_bytes([("Sheet1", PEOPLE_ROWS)])
    url = origin.add("/enr-book.xls", data, content_type=XLS_CT)
    payload = query(gate, enrich_ok(gate, url))
    assert payload["dataset_summary"]["filetype"] == "excel"


def test_enriched_spreadsheet_has_no_column_details(gate, origin):
    data = xlsx_bytes([("Sheet1", PEOPLE_ROWS)])
    url = origin.add("/enr-book-nodetails.xlsx", data, content_type=XLSX_CT)
    payload = query(gate, enrich_ok(gate, url))
    assert "column_details" not in payload


def test_enriched_spreadsheet_summary_keeps_the_counts(gate, origin):
    # "only dataset_summary" excludes column_details, not the summary keys (T78).
    data = xlsx_bytes([("Sheet1", PEOPLE_ROWS)])
    url = origin.add("/enr-book-counts.xlsx", data, content_type=XLSX_CT)
    payload = query(gate, enrich_ok(gate, url))
    summary = payload["dataset_summary"]
    assert {"filetype", "row_count", "column_count"} <= set(summary)
    assert summary["row_count"] == 2
    assert summary["column_count"] == 3


# ---------------------------------------------------------------------------
# Phrase: "Non-enriched responses omit both metadata fields
#          (no `null`/empty objects)."
# Context: a dataset converted without enrich=yes.
# ---------------------------------------------------------------------------
def test_non_enriched_response_omits_both_fields(gate, origin):
    url = origin.add("/enr-omit.csv", PROFILE)
    payload = query(gate, convert_ok(gate, url))
    assert "dataset_summary" not in payload
    assert "column_details" not in payload
    assert set(payload) == {"ok", "columns", "rows", "total", "query_ms"}


def test_non_enriched_upload_omits_both_fields(gate):
    payload = query(gate, upload_ok(gate, PROFILE, filename="p.csv"))
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


# ---------------------------------------------------------------------------
# Phrase: "`rows`, `columns`, `ok`, `query_ms`, and `total` do not change."
# Context: the same source converted with and without enrichment.
# ---------------------------------------------------------------------------
def test_enrichment_does_not_change_the_other_response_fields(gate, origin):
    plain_url = origin.add("/enr-same-plain.csv", PROFILE)
    rich_url = origin.add("/enr-same-rich.csv", PROFILE)
    plain = query(gate, convert_ok(gate, plain_url))
    rich = query(gate, enrich_ok(gate, rich_url))

    assert rich["ok"] is plain["ok"] is True
    assert rich["columns"] == plain["columns"]
    assert rich["rows"] == plain["rows"]
    assert rich["total"] == plain["total"]
    assert isinstance(rich["query_ms"], (int, float))
    assert set(rich) == set(plain) | {"dataset_summary", "column_details"}


def test_enriched_query_controls_still_work(gate, origin):
    url = origin.add("/enr-controls.csv", PROFILE)
    endpoint = enrich_ok(gate, url)
    payload = query(gate, endpoint, _shape="objects", _size=2, _sort="name")
    assert payload["total"] == 3
    assert [row["name"] for row in payload["rows"]] == ["Alice", "Alice"]
    assert "dataset_summary" in payload


# ---------------------------------------------------------------------------
# Phrase: "`enrich=yes` on a cached non-enriched dataset forces re-ingestion
#          and upgrades stored state."
# Context: the dataset was already converted without enrichment.
# ---------------------------------------------------------------------------
def test_enrich_on_cached_non_enriched_refetches_the_source(gate, origin):
    path = "/enr-upgrade-fetch.csv"
    url = origin.add(path, SIMPLE)
    convert_ok(gate, url)
    before = origin.hit_count(path)
    enrich_ok(gate, url)
    assert origin.hit_count(path) > before


def test_enrich_on_cached_non_enriched_upgrades_stored_state(gate, origin):
    url = origin.add("/enr-upgrade-state.csv", PROFILE)
    endpoint = convert_ok(gate, url)
    assert "dataset_summary" not in query(gate, endpoint)
    assert enrich_ok(gate, url) == endpoint
    payload = query(gate, endpoint)
    assert payload["dataset_summary"]["row_count"] == 3
    assert payload["column_details"]["age"]["type"] == "integer"


# ---------------------------------------------------------------------------
# Phrase: "`enrich=yes` on a cached enriched dataset may use cache."
# Context: a second enriched conversion of the same source.
# ---------------------------------------------------------------------------
def test_enrich_twice_stays_enriched(gate, origin):
    url = origin.add("/enr-twice.csv", PROFILE)
    first = enrich_ok(gate, url)
    second = enrich_ok(gate, url)
    assert second == first
    payload = query(gate, second)
    assert payload["dataset_summary"]["row_count"] == 3
    assert "column_details" in payload


# ---------------------------------------------------------------------------
# Phrase: "Requests without re-ingestion do not change stored enrichment state."
# Context: a plain /convert that hits the cache for an enriched dataset.
# ---------------------------------------------------------------------------
def test_cached_plain_convert_does_not_downgrade(gate, origin):
    path = "/enr-no-downgrade.csv"
    url = origin.add(path, PROFILE)
    endpoint = enrich_ok(gate, url)
    before = origin.hit_count(path)

    assert convert_ok(gate, url) == endpoint  # cache hit: no re-ingestion
    assert origin.hit_count(path) == before
    assert "dataset_summary" in query(gate, endpoint)


def test_cached_plain_convert_does_not_upgrade(gate, origin):
    path = "/enr-no-upgrade.csv"
    url = origin.add(path, PROFILE)
    endpoint = convert_ok(gate, url)
    before = origin.hit_count(path)

    assert convert_ok(gate, url) == endpoint
    assert origin.hit_count(path) == before
    assert "dataset_summary" not in query(gate, endpoint)


# ---------------------------------------------------------------------------
# Phrase: "Re-ingestion recomputes metadata from current source bytes."
# Context: the origin serves different bytes, and `force` re-ingests.
# ---------------------------------------------------------------------------
def test_forced_re_ingestion_recomputes_metadata(gate, origin):
    path = "/enr-recompute.csv"
    url = origin.add(path, PROFILE)
    endpoint = enrich_ok(gate, url)
    assert query(gate, endpoint)["dataset_summary"]["row_count"] == 3

    origin.add(path, "name,age\nZoe,7\n")  # the source now has one data row
    resp = raw_convert(gate, url, "force&enrich=yes")
    assert resp.status_code == 200, resp.text
    payload = query(gate, endpoint)
    assert payload["dataset_summary"]["row_count"] == 1
    assert payload["dataset_summary"]["column_count"] == 2
    assert set(payload["column_details"]) == {"name", "age"}


def test_enrich_upgrade_uses_the_current_source_bytes(gate, origin):
    path = "/enr-upgrade-current.csv"
    url = origin.add(path, SIMPLE)
    endpoint = convert_ok(gate, url)

    origin.add(path, PROFILE)  # upgrading re-ingests, so the new bytes win
    assert enrich_ok(gate, url) == endpoint
    payload = query(gate, endpoint)
    assert payload["columns"] == ["name", "age", "score", "note"]
    assert payload["dataset_summary"]["column_count"] == 4


# ---------------------------------------------------------------------------
# Phrase: "Requests without re-ingestion do not change stored enrichment
#          state." (contrapositive, see T79)
# Context: a forced re-ingestion that does not ask for enrichment.
# ---------------------------------------------------------------------------
def test_forced_plain_re_ingestion_stores_non_enriched(gate, origin):
    path = "/enr-force-plain.csv"
    url = origin.add(path, PROFILE)
    endpoint = enrich_ok(gate, url)
    assert "dataset_summary" in query(gate, endpoint)

    resp = raw_convert(gate, url, "force")
    assert resp.status_code == 200, resp.text
    payload = query(gate, endpoint)
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


# ---------------------------------------------------------------------------
# Phrase: "`enrich=yes` on a cached non-enriched dataset forces re-ingestion"
# Context: caching disabled -- every /convert re-ingests anyway.
# ---------------------------------------------------------------------------
def test_enrichment_with_caching_disabled(fresh_gate, origin):
    g = fresh_gate(port=free_port(), address="127.0.0.1", env={"CACHE_ENABLED": "no"})
    url = origin.add("/enr-nocache.csv", PROFILE)
    endpoint = convert_ok(g, url)
    assert "dataset_summary" not in query(g, endpoint)
    assert convert_ok(g, url, enrich="yes") == endpoint
    assert query(g, endpoint)["dataset_summary"]["row_count"] == 3


# ---------------------------------------------------------------------------
# Phrase: "`enrich` applies only on `/convert`."
# Context: the other endpoints treat it as an ordinary unknown parameter.
# ---------------------------------------------------------------------------
def test_enrich_on_upload_does_not_enrich(gate):
    endpoint = upload_ok(gate, PROFILE, filename="e.csv", enrich="yes")
    payload = query(gate, endpoint)
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


def test_enrich_on_the_dataset_query_is_ignored(gate, origin):
    url = origin.add("/enr-query-param.csv", PROFILE)
    endpoint = convert_ok(gate, url)
    payload = query(gate, endpoint, enrich="yes")
    assert "dataset_summary" not in payload
    assert "column_details" not in payload


def test_enrich_on_the_export_is_ignored(gate, origin):
    url = origin.add("/enr-export.csv", PROFILE)
    endpoint = enrich_ok(gate, url)
    resp = gate.get(endpoint + "/export", params={"enrich": "yes"})
    assert resp.status_code == 200, resp.text
    header, rows = read_csv_text(resp.text)
    assert header == ["name", "age", "score", "note"]
    assert len(rows) == 3


# ---------------------------------------------------------------------------
# Phrase: "Enrichment failures return standard JSON errors"
# Context: an enriched conversion whose source cannot be ingested.
# ---------------------------------------------------------------------------
def test_enriched_conversion_of_a_bad_source_is_a_json_error(gate, origin):
    url = origin.add("/enr-bad.csv", "just one line of prose that is not tabular\n")
    resp = gate.convert(source=url, enrich="yes")
    body = assert_error_envelope(resp, 400)
    assert set(body) == {"ok", "error"}


def test_enriched_conversion_of_a_missing_source_is_a_json_error(gate, origin):
    url = origin.url("/enr-never-served.csv")
    origin.remove("/enr-never-served.csv")
    resp = gate.convert(source=url, enrich="yes")
    body = assert_error_envelope(resp, 404)
    assert set(body) == {"ok", "error"}


# ---------------------------------------------------------------------------
# Phrase: "... and must not downgrade to non-enriched storage."
# Context: a failing re-ingestion of an already-enriched dataset.
# ---------------------------------------------------------------------------
def test_failed_re_ingestion_keeps_the_enriched_dataset(gate, origin):
    path = "/enr-keep.csv"
    url = origin.add(path, PROFILE)
    endpoint = enrich_ok(gate, url)

    origin.remove(path)  # the source is gone; a forced re-ingestion must fail
    assert_error_envelope(raw_convert(gate, url, "force&enrich=yes"), 404)

    payload = query(gate, endpoint)
    assert payload["dataset_summary"]["row_count"] == 3
    assert payload["column_details"]["age"]["type"] == "integer"
    assert payload["rows"] == [
        ["Alice", 30, 1.5, "x"],
        ["Bob", 41, 2.0, ""],
        ["Alice", "", 3.25, "y"],
    ]


def test_failed_enriched_re_ingestion_of_bad_bytes_keeps_metadata(gate, origin):
    path = "/enr-keep-bad.csv"
    url = origin.add(path, PROFILE)
    endpoint = enrich_ok(gate, url)

    origin.add(path, b"%PDF-1.4 not a table at all")
    assert_error_envelope(raw_convert(gate, url, "force&enrich=yes"), 400)
    assert query(gate, endpoint)["dataset_summary"]["column_count"] == 4
